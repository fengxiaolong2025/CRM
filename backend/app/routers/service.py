"""售后：客诉工单、窜货登记"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import Complaint, CrossSale, Customer, User
from app.schemas import ComplaintCreate, CrossSaleCreate
from app.deps import get_current_user, require_roles
from app.utils import ser, ser_list, money, log, gen_no
from app.crud import create_obj, update_obj, delete_obj

router = APIRouter(prefix="/api", tags=["service"])


def _enrich(db, rows):
    cmap = {c.id: c.name for c in db.query(Customer).all()}
    umap = {u.id: u.name for u in db.query(User).all()}
    out = []
    for c in rows:
        d = ser(c, customer_name=cmap.get(c.customer_id, ""), owner_name=umap.get(c.owner_id, ""),
                assignee_name=umap.get(c.assignee_id, ""))
        if c.created_at and c.closed_at:
            d["handle_hours"] = round((c.closed_at - c.created_at).total_seconds() / 3600, 1)
        out.append(d)
    return out


@router.get("/complaints")
def list_complaints(q: str = "", status: str = "", urgency: str = "", ctype: str = "",
                    db: Session = Depends(get_db), _=Depends(get_current_user)):
    qs = db.query(Complaint)
    if status:
        qs = qs.filter(Complaint.status == status)
    if urgency:
        qs = qs.filter(Complaint.urgency == urgency)
    if ctype:
        qs = qs.filter(Complaint.ctype == ctype)
    if q:
        qs = qs.filter(Complaint.description.contains(q) | Complaint.complaint_no.contains(q))
    return _enrich(db, qs.order_by(Complaint.id.desc()).all())


@router.post("/complaints")
def add_complaint(d: ComplaintCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    data = d.model_dump(exclude_none=True)
    data["complaint_no"] = gen_no("KS")
    data.setdefault("status", "新建")
    c = create_obj(db, Complaint, data, user, "客诉", {"owner_id": user.id})
    return _enrich(db, [c])[0]


@router.put("/complaints/{cid}")
def update_complaint(cid: int, data: dict = Body(...), db: Session = Depends(get_db),
                     user=Depends(get_current_user)):
    c = db.query(Complaint).filter(Complaint.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="客诉工单不存在")
    if data.get("status") == "已结案" and not c.closed_at:
        c.closed_at = datetime.now()
    return _enrich(db, [update_obj(db, c, data, user, "客诉")])[0]


@router.post("/complaints/{cid}/close")
def close_complaint(cid: int, data: dict = Body(default={}), db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    c = db.query(Complaint).filter(Complaint.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="客诉工单不存在")
    c.status = "已结案"
    c.closed_at = datetime.now()
    if data.get("solution"):
        c.solution = data["solution"]
    if data.get("result"):
        c.result = data["result"]
    db.commit()
    log(db, user, "结案", "客诉", cid, f"客诉 {c.complaint_no} 结案")
    return _enrich(db, [c])[0]


@router.delete("/complaints/{cid}")
def del_complaint(cid: int, db: Session = Depends(get_db),
                  user=Depends(require_roles("super_admin", "after_sales"))):
    c = db.query(Complaint).filter(Complaint.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="客诉工单不存在")
    return delete_obj(db, c, user, "客诉")


@router.get("/complaints/stats")
def complaint_stats(db: Session = Depends(get_db), _=Depends(get_current_user)):
    by_type = db.query(Complaint.ctype, func.count(Complaint.id)).group_by(Complaint.ctype).all()
    by_status = db.query(Complaint.status, func.count(Complaint.id)).group_by(Complaint.status).all()
    by_urgency = db.query(Complaint.urgency, func.count(Complaint.id)).group_by(Complaint.urgency).all()
    closed = db.query(Complaint).filter(Complaint.closed_at.isnot(None)).all()
    avg_hours = round(sum((c.closed_at - c.created_at).total_seconds() / 3600 for c in closed) / len(closed), 1) \
        if closed else 0
    total = db.query(Complaint).count()
    closed_n = db.query(Complaint).filter(Complaint.status == "已结案").count()
    return {
        "total": total, "closed": closed_n,
        "close_rate": round(closed_n / total * 100, 1) if total else 0,
        "avg_handle_hours": avg_hours,
        "by_type": [{"name": t or "其他", "value": c} for t, c in by_type],
        "by_status": [{"name": s, "value": c} for s, c in by_status],
        "by_urgency": [{"name": u or "中", "value": c} for u, c in by_urgency],
    }


# ================================================================ 窜货
@router.get("/cross-sales")
def list_cross(db: Session = Depends(get_db), _=Depends(get_current_user)):
    cmap = {c.id: c.name for c in db.query(Customer).all()}
    umap = {u.id: u.name for u in db.query(User).all()}
    return [ser(x, dealer_name=cmap.get(x.dealer_id, ""), reporter_name=umap.get(x.reporter_id, ""))
            for x in db.query(CrossSale).order_by(CrossSale.id.desc()).all()]


@router.post("/cross-sales")
def add_cross(d: CrossSaleCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = create_obj(db, CrossSale, d.model_dump(exclude_none=True), user, "窜货", {"reporter_id": user.id})
    return ser(c)


@router.put("/cross-sales/{cid}")
def upd_cross(cid: int, data: dict = Body(...), db: Session = Depends(get_db),
              user=Depends(get_current_user)):
    c = db.query(CrossSale).filter(CrossSale.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="记录不存在")
    return ser(update_obj(db, c, data, user, "窜货"))


@router.delete("/cross-sales/{cid}")
def del_cross(cid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = db.query(CrossSale).filter(CrossSale.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="记录不存在")
    return delete_obj(db, c, user, "窜货")
