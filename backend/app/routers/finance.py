"""财务管理：回款、应收与账龄、发票、返利"""
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import (
    Payment, Invoice, Order, Customer, User, RebatePolicy, RebateRecord,
)
from app.schemas import PaymentCreate, InvoiceCreate, RebatePolicyCreate, RebateRecordCreate
from app.deps import get_current_user, require_roles, is_manager_or_above
from app.utils import ser, ser_list, money, log, gen_no, scope_ids, apply_scope
from app.crud import create_obj, update_obj, delete_obj, parse_date

router = APIRouter(prefix="/api", tags=["finance"])
FINANCE = ("finance", "super_admin", "sales_director")


def _names(db):
    return ({c.id: c.name for c in db.query(Customer).all()},
            {u.id: u.name for u in db.query(User).all()},
            {o.id: o.order_no for o in db.query(Order).all()})


def term_days(term: str) -> int:
    if not term:
        return 0
    if "60" in term:
        return 60
    if "30" in term:
        return 30
    if "90" in term:
        return 90
    return 0


# ================================================================ 回款
@router.get("/payments")
def list_payments(q: str = "", pay_method: str = "", scope: str = "auto",
                  db: Session = Depends(get_db), user=Depends(get_current_user)):
    qs = apply_scope(db.query(Payment), Payment, db, user, scope)
    if pay_method:
        qs = qs.filter(Payment.pay_method == pay_method)
    cmap, umap, omap = _names(db)
    rows = []
    for p in qs.order_by(Payment.id.desc()).all():
        d = ser(p, customer_name=cmap.get(p.customer_id, ""), owner_name=umap.get(p.owner_id, ""),
                order_no=omap.get(p.order_id, ""))
        if q and q not in (d["customer_name"] or "") and q not in (d["order_no"] or "") \
                and q not in (d["pay_no"] or ""):
            continue
        rows.append(d)
    return rows


@router.post("/payments")
def add_payment(d: PaymentCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    data = d.model_dump(exclude_none=True)
    data["pay_date"] = d.pay_date or date.today()
    data["pay_no"] = gen_no("HK")
    p = create_obj(db, Payment, data, user, "回款", {"owner_id": user.id})
    return ser(p, order_no=(db.query(Order).filter(Order.id == p.order_id).first().order_no
                            if p.order_id else ""))


@router.put("/payments/{pid}")
def update_payment(pid: int, data: dict = Body(...), db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    p = db.query(Payment).filter(Payment.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="回款记录不存在")
    return ser(update_obj(db, p, data, user, "回款"))


@router.delete("/payments/{pid}")
def del_payment(pid: int, db: Session = Depends(get_db),
                user=Depends(require_roles("super_admin", "sales_director", "finance"))):
    p = db.query(Payment).filter(Payment.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="回款记录不存在")
    return delete_obj(db, p, user, "回款")


# ================================================================ 应收 / 账龄
@router.get("/receivables")
def receivables(q: str = "", scope: str = "auto", only_overdue: bool = False,
                db: Session = Depends(get_db), user=Depends(get_current_user)):
    """应收台账（订单维度，含账龄）"""
    qs = db.query(Order).filter(Order.status != "已取消")
    ids = scope_ids(db, user, scope)
    if ids is not None and not is_manager_or_above(user.role):
        qs = qs.filter(Order.owner_id.in_(ids))
    cmap, umap, _ = _names(db)
    paid_map = {oid: money(a) for oid, a in
                db.query(Payment.order_id, func.coalesce(func.sum(Payment.amount), 0))
                .group_by(Payment.order_id).all()}
    today = date.today()
    rows, seen = [], set()
    for o in qs.all():
        paid = paid_map.get(o.id, 0)
        remain = money((o.total_amount or 0) - paid)
        if remain <= 0.01:
            continue
        due = (o.created_at.date() if o.created_at else today) + timedelta(days=term_days(o.account_term))
        overdue = (today - due).days
        if overdue <= 0:
            bucket = "未到期"
        elif overdue <= 30:
            bucket = "逾期1-30天"
        elif overdue <= 60:
            bucket = "逾期31-60天"
        elif overdue <= 90:
            bucket = "逾期61-90天"
        else:
            bucket = "逾期90天以上"
        row = ser(o, customer_name=cmap.get(o.customer_id, ""), owner_name=umap.get(o.owner_id, ""),
                  paid=paid, remain=remain, due_date=due.isoformat(), overdue_days=max(overdue, 0),
                  bucket=bucket)
        if q and q not in (row["customer_name"] or "") and q not in (row["order_no"] or ""):
            continue
        if only_overdue and overdue <= 0:
            continue
        rows.append(row)
        seen.add(o.id)
    rows.sort(key=lambda r: -r["overdue_days"])
    return rows


@router.get("/receivables/summary")
def receivables_summary(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = receivables(db=db, user=user)
    buckets = ["未到期", "逾期1-30天", "逾期31-60天", "逾期61-90天", "逾期90天以上"]
    out = {b: {"bucket": b, "amount": 0.0, "count": 0} for b in buckets}
    for r in rows:
        b = out.get(r["bucket"])
        if b:
            b["amount"] = money(b["amount"] + r["remain"])
            b["count"] += 1
    total = money(sum(r["remain"] for r in rows))
    overdue = money(sum(r["remain"] for r in rows if r["overdue_days"] > 0))
    return {"buckets": list(out.values()), "total": total, "overdue": overdue,
            "overdue_rate": round(overdue / total * 100, 1) if total else 0,
            "count": len(rows)}


# ================================================================ 发票
@router.get("/invoices")
def list_invoices(q: str = "", status: str = "", db: Session = Depends(get_db),
                  user=Depends(get_current_user)):
    qs = db.query(Invoice)
    if status:
        qs = qs.filter(Invoice.status == status)
    cmap, _, omap = _names(db)
    rows = []
    for inv in qs.order_by(Invoice.id.desc()).all():
        d = ser(inv, customer_name=cmap.get(inv.customer_id, ""), order_no=omap.get(inv.order_id, ""))
        if q and q not in (d["customer_name"] or "") and q not in (d["invoice_no"] or ""):
            continue
        rows.append(d)
    return rows


@router.post("/invoices")
def add_invoice(d: InvoiceCreate, db: Session = Depends(get_db),
                user=Depends(require_roles(*FINANCE))):
    data = d.model_dump(exclude_none=True)
    data["invoice_no"] = d.invoice_no or gen_no("FP")
    data.setdefault("invoice_date", date.today())
    return ser(create_obj(db, Invoice, data, user, "发票"))


@router.put("/invoices/{iid}")
def update_invoice(iid: int, data: dict = Body(...), db: Session = Depends(get_db),
                   user=Depends(require_roles(*FINANCE))):
    inv = db.query(Invoice).filter(Invoice.id == iid).first()
    if not inv:
        raise HTTPException(status_code=404, detail="发票不存在")
    return ser(update_obj(db, inv, data, user, "发票"))


@router.delete("/invoices/{iid}")
def del_invoice(iid: int, db: Session = Depends(get_db), user=Depends(require_roles(*FINANCE))):
    inv = db.query(Invoice).filter(Invoice.id == iid).first()
    if not inv:
        raise HTTPException(status_code=404, detail="发票不存在")
    return delete_obj(db, inv, user, "发票")


# ================================================================ 返利
@router.get("/rebate-policies")
def list_policies(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return ser_list(db.query(RebatePolicy).order_by(RebatePolicy.id.desc()).all())


@router.post("/rebate-policies")
def add_policy(d: RebatePolicyCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return ser(create_obj(db, RebatePolicy, d.model_dump(), user, "返利政策"))


@router.put("/rebate-policies/{pid}")
def upd_policy(pid: int, data: dict = Body(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    p = db.query(RebatePolicy).filter(RebatePolicy.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="政策不存在")
    return ser(update_obj(db, p, data, user, "返利政策"))


@router.delete("/rebate-policies/{pid}")
def del_policy(pid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    p = db.query(RebatePolicy).filter(RebatePolicy.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="政策不存在")
    return delete_obj(db, p, user, "返利政策")


@router.get("/rebate-records")
def list_rebates(status: str = "", db: Session = Depends(get_db), _=Depends(get_current_user)):
    qs = db.query(RebateRecord)
    if status:
        qs = qs.filter(RebateRecord.status == status)
    cmap = {c.id: c.name for c in db.query(Customer).all()}
    pmap = {p.id: p.name for p in db.query(RebatePolicy).all()}
    return [ser(r, customer_name=cmap.get(r.customer_id, ""), policy_name=pmap.get(r.policy_id, ""))
            for r in qs.order_by(RebateRecord.id.desc()).all()]


@router.post("/rebate-records")
def add_rebate(d: RebateRecordCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return ser(create_obj(db, RebateRecord, d.model_dump(), user, "返利"))


@router.put("/rebate-records/{rid}")
def upd_rebate(rid: int, data: dict = Body(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    r = db.query(RebateRecord).filter(RebateRecord.id == rid).first()
    if not r:
        raise HTTPException(status_code=404, detail="返利记录不存在")
    return ser(update_obj(db, r, data, user, "返利"))


@router.delete("/rebate-records/{rid}")
def del_rebate(rid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    r = db.query(RebateRecord).filter(RebateRecord.id == rid).first()
    if not r:
        raise HTTPException(status_code=404, detail="返利记录不存在")
    return delete_obj(db, r, user, "返利")


# ================================================================ 财务概览
@router.get("/finance/summary")
def finance_summary(db: Session = Depends(get_db), user=Depends(get_current_user)):
    now = datetime.now()
    month_start = datetime(now.year, now.month, 1)
    order_total = money(db.query(func.coalesce(func.sum(Order.total_amount), 0))
                        .filter(Order.status != "已取消").scalar() or 0)
    paid_total = money(db.query(func.coalesce(func.sum(Payment.amount), 0)).scalar() or 0)
    month_paid = money(db.query(func.coalesce(func.sum(Payment.amount), 0))
                       .filter(Payment.pay_date >= month_start.date()).scalar() or 0)
    month_order = money(db.query(func.coalesce(func.sum(Order.total_amount), 0))
                        .filter(Order.created_at >= month_start).scalar() or 0)
    inv_total = money(db.query(func.coalesce(func.sum(Invoice.amount), 0))
                      .filter(Invoice.status != "已作废").scalar() or 0)
    return {
        "order_total": order_total, "paid_total": paid_total,
        "receivable": money(order_total - paid_total),
        "month_order": month_order, "month_paid": month_paid,
        "collection_rate": round(paid_total / order_total * 100, 1) if order_total else 0,
        "invoice_total": inv_total,
        "uninvoiced": money(order_total - inv_total),
    }
