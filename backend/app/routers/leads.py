"""线索管理 + 公海池"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Lead, Customer, User, Region, FollowUp
from app.schemas import LeadCreate, LeadOut
from app.deps import get_current_user, visible_user_ids
from app.utils import ser, ser_list, scope_ids, apply_scope, log, gen_no
from app.crud import create_obj, update_obj, delete_obj

router = APIRouter(prefix="/api", tags=["leads"])


def _enrich(db, rows):
    owners = {u.id: u.name for u in db.query(User).all()}
    regions = {r.id: r.name for r in db.query(Region).all()}
    out = []
    for l in rows:
        d = ser(l, owner_name=owners.get(l.owner_id, "未分配"),
                region_name=regions.get(l.region_id, ""))
        if l.next_follow_at:
            d["overdue_days"] = max((datetime.now() - l.next_follow_at).days, 0)
            d["is_overdue"] = l.next_follow_at < datetime.now()
        else:
            d["overdue_days"] = (datetime.now() - (l.created_at or datetime.now())).days
            d["is_overdue"] = d["overdue_days"] > 7
        out.append(d)
    return out


@router.get("/leads")
def list_leads(pool: bool = False, q: str = "", status: str = "", source: str = "",
               scope: str = "auto", db: Session = Depends(get_db), user=Depends(get_current_user)):
    qs = db.query(Lead)
    if pool:
        qs = qs.filter(Lead.is_pool == True)  # noqa
    else:
        ids = visible_user_ids(db, user)
        if ids is not None:
            qs = qs.filter(Lead.owner_id.in_(ids), Lead.is_pool == False)  # noqa
        if scope == "mine":
            qs = qs.filter(Lead.owner_id == user.id)
    if q:
        qs = qs.filter(Lead.customer_name.contains(q) | Lead.contact.contains(q) | Lead.phone.contains(q))
    if status:
        qs = qs.filter(Lead.status == status)
    if source:
        qs = qs.filter(Lead.source == source)
    return _enrich(db, qs.order_by(Lead.created_at.desc()).all())


@router.get("/leads/{lid}")
def get_lead(lid: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    l = db.query(Lead).filter(Lead.id == lid).first()
    if not l:
        raise HTTPException(status_code=404, detail="线索不存在")
    follows = db.query(FollowUp).filter(FollowUp.lead_id == lid).order_by(FollowUp.created_at.desc()).all()
    return {"lead": _enrich(db, [l])[0], "followups": ser_list(follows)}


@router.post("/leads")
def create_lead(d: LeadCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    data = d.model_dump(exclude_none=True)
    data.setdefault("status", "待跟进")
    lead = create_obj(db, Lead, data, user, "线索", {"owner_id": user.id, "last_follow_at": datetime.now()})
    return _enrich(db, [lead])[0]


@router.put("/leads/{lid}")
def update_lead(lid: int, data: dict = Body(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    l = db.query(Lead).filter(Lead.id == lid).first()
    if not l:
        raise HTTPException(status_code=404, detail="线索不存在")
    return _enrich(db, [update_obj(db, l, data, user, "线索")])[0]


@router.delete("/leads/{lid}")
def delete_lead(lid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    l = db.query(Lead).filter(Lead.id == lid).first()
    if not l:
        raise HTTPException(status_code=404, detail="线索不存在")
    return delete_obj(db, l, user, "线索")


@router.post("/leads/{lid}/claim")
def claim_lead(lid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    lead = db.query(Lead).filter(Lead.id == lid, Lead.is_pool == True).first()  # noqa
    if not lead:
        raise HTTPException(status_code=404, detail="公海线索不存在或被抢先认领")
    lead.is_pool = False
    lead.owner_id = user.id
    lead.status = "跟进中"
    lead.last_follow_at = datetime.now()
    db.commit()
    log(db, user, "认领", "线索公海", lid, f"认领线索 {lead.customer_name}")
    return {"ok": True}


@router.post("/leads/batch-claim")
def batch_claim(ids: list[int] = Body(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    n = 0
    for lid in ids:
        lead = db.query(Lead).filter(Lead.id == lid, Lead.is_pool == True).first()  # noqa
        if lead:
            lead.is_pool = False; lead.owner_id = user.id; lead.status = "跟进中"
            n += 1
    db.commit()
    return {"ok": True, "count": n}


@router.post("/leads/{lid}/to-pool")
def to_pool(lid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    lead = db.query(Lead).filter(Lead.id == lid).first()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    lead.is_pool = True
    lead.owner_id = None
    db.commit()
    log(db, user, "释放", "线索公海", lid, f"线索 {lead.customer_name} 放入公海")
    return {"ok": True}


@router.post("/leads/{lid}/convert")
def convert_lead(lid: int, data: dict = Body(default={}), db: Session = Depends(get_db),
                 user=Depends(get_current_user)):
    """有效线索转为正式客户"""
    lead = db.query(Lead).filter(Lead.id == lid).first()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    if lead.status == "有效":
        raise HTTPException(status_code=400, detail="该线索已转为客户")
    cust = Customer(
        name=data.get("name") or lead.customer_name,
        address=lead.address, phone=lead.phone, wechat=lead.wechat,
        region_id=lead.region_id, owner_id=lead.owner_id or user.id,
        source=lead.source, customer_type=data.get("customer_type", "dealer"),
        channel_type_id=data.get("channel_type_id"), level_id=data.get("level_id"),
        payment_term=data.get("payment_term"), credit_limit=data.get("credit_limit"),
        status=1,
    )
    db.add(cust); db.flush()
    lead.status = "有效"
    db.commit()
    log(db, user, "转化", "线索", lid, f"线索 {lead.customer_name} 转为客户 #{cust.id}")
    return {"ok": True, "customer_id": cust.id}


@router.post("/leads/{lid}/assign")
def assign_lead(lid: int, owner_id: int = Body(..., embed=True), db: Session = Depends(get_db),
                user=Depends(get_current_user)):
    lead = db.query(Lead).filter(Lead.id == lid).first()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    lead.owner_id = owner_id
    lead.is_pool = False
    db.commit()
    log(db, user, "分配", "线索", lid, f"线索分配给 #{owner_id}")
    return {"ok": True}
