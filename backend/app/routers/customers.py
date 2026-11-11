"""客户档案（核心）：客户、公海、联系人、标签、合同、360 视图"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import (
    Customer, Contact, CustomerTag, Contract, Visit, SampleApplication,
    Opportunity, Order, Payment, Complaint, RebateRecord, CrossSale, Invoice,
    CustomerLevel, ChannelType, Region, User, FollowUp,
)
from app.schemas import CustomerCreate, CustomerOut, ContactCreate, ContractCreate
from app.deps import get_current_user, customer_owner_filter
from app.utils import ser, ser_list, money, log, apply_scope
from app.crud import create_obj, update_obj, delete_obj

router = APIRouter(prefix="/api", tags=["customers"])


def _apply_scope(qs, db, user, scope="auto"):
    if scope in ("dept", "mine"):
        return apply_scope(qs, Customer, db, user, scope)
    owners, _ = customer_owner_filter(db, user)
    if owners is not None:
        qs = qs.filter(Customer.owner_id.in_(owners))
    return qs


def _maps(db):
    return (
        {u.id: u.name for u in db.query(User).all()},
        {l.id: (l.code, l.name) for l in db.query(CustomerLevel).all()},
        {c.id: c.name for c in db.query(ChannelType).all()},
        {r.id: r.name for r in db.query(Region).all()},
    )


def _order_stat(db):
    rows = db.query(Order.customer_id, func.coalesce(func.sum(Order.total_amount), 0),
                    func.count(Order.id)).filter(Order.status != "已取消") \
        .group_by(Order.customer_id).all()
    return {cid: (money(amt), cnt) for cid, amt, cnt in rows}


def _paid_stat(db):
    rows = db.query(Payment.customer_id, func.coalesce(func.sum(Payment.amount), 0)) \
        .group_by(Payment.customer_id).all()
    return {cid: money(amt) for cid, amt in rows}


def _enrich(db, rows, with_stat=True):
    owners, levels, channels, regions = _maps(db)
    ostat, paid = (_order_stat(db), _paid_stat(db)) if with_stat else ({}, {})
    out = []
    for c in rows:
        lv = levels.get(c.level_id, ("", ""))
        amt, cnt = ostat.get(c.id, (0, 0))
        d = ser(c, owner_name=owners.get(c.owner_id, "未分配"),
                level_code=lv[0], level_name=lv[1],
                channel_name=channels.get(c.channel_type_id, ""),
                region_name=regions.get(c.region_id, ""),
                order_amount=amt, order_count=cnt, paid_amount=paid.get(c.id, 0),
                receivable=money(amt - paid.get(c.id, 0)))
        if c.next_follow_at:
            d["is_overdue"] = c.next_follow_at < datetime.now()
        out.append(d)
    return out


@router.get("/customers")
def list_customers(q: str = "", level_id: int = 0, customer_type: str = "", channel_type_id: int = 0,
                   pool: bool = False, owner_id: int = 0, scope: str = "auto",
                   db: Session = Depends(get_db), user=Depends(get_current_user)):
    qs = db.query(Customer)
    if pool:
        qs = qs.filter(Customer.is_pool == True, Customer.status == 1)  # noqa
    else:
        qs = _apply_scope(qs, db, user, scope).filter(Customer.is_pool == False)  # noqa
    if q:
        qs = qs.filter(Customer.name.contains(q) | Customer.credit_code.contains(q) |
                       Customer.phone.contains(q))
    if level_id:
        qs = qs.filter(Customer.level_id == level_id)
    if customer_type:
        qs = qs.filter(Customer.customer_type == customer_type)
    if channel_type_id:
        qs = qs.filter(Customer.channel_type_id == channel_type_id)
    if owner_id:
        qs = qs.filter(Customer.owner_id == owner_id)
    return _enrich(db, qs.filter(Customer.status == 1).order_by(Customer.id.desc()).all())


@router.post("/customers")
def create_customer(d: CustomerCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    data = d.model_dump(exclude_none=True)
    data.setdefault("owner_id", user.id)
    c = create_obj(db, Customer, data, user, "客户")
    return _enrich(db, [c])[0]


@router.put("/customers/{cid}")
def update_customer(cid: int, data: dict = Body(...), db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    c = _apply_scope(db.query(Customer), db, user).filter(Customer.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="客户不可见或不存在")
    return _enrich(db, [update_obj(db, c, data, user, "客户")])[0]


@router.delete("/customers/{cid}")
def delete_customer(cid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = _apply_scope(db.query(Customer), db, user).filter(Customer.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="客户不可见或不存在")
    c.status = 0
    db.commit()
    log(db, user, "删除", "客户", cid, f"逻辑删除客户 {c.name}")
    return {"ok": True}


@router.post("/customers/{cid}/transfer")
def transfer_customer(cid: int, owner_id: int = Body(..., embed=True), db: Session = Depends(get_db),
                      user=Depends(get_current_user)):
    c = db.query(Customer).filter(Customer.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    c.owner_id = owner_id
    db.commit()
    log(db, user, "转移", "客户", cid, f"客户 {c.name} 负责人改为 #{owner_id}")
    return {"ok": True}


@router.post("/customers/{cid}/to-pool")
def customer_to_pool(cid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = db.query(Customer).filter(Customer.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    c.is_pool = True
    c.pool_at = datetime.now()
    db.commit()
    log(db, user, "释放", "客户公海", cid, f"客户 {c.name} 放入公海")
    return {"ok": True}


@router.post("/customers/{cid}/claim")
def claim_customer(cid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = db.query(Customer).filter(Customer.id == cid, Customer.is_pool == True).first()  # noqa
    if not c:
        raise HTTPException(status_code=404, detail="公海客户不存在")
    c.is_pool = False
    c.owner_id = user.id
    db.commit()
    log(db, user, "认领", "客户公海", cid, f"认领客户 {c.name}")
    return {"ok": True}


# ---------------------------------------------------------------- 联系人
@router.get("/contacts")
def list_contacts(q: str = "", customer_id: int = 0, db: Session = Depends(get_db),
                  user=Depends(get_current_user)):
    qs = db.query(Contact)
    if customer_id:
        qs = qs.filter(Contact.customer_id == customer_id)
    else:
        cids = [c.id for c in _apply_scope(db.query(Customer), db, user).all()]
        qs = qs.filter(Contact.customer_id.in_(cids))
    if q:
        qs = qs.filter(Contact.name.contains(q) | Contact.phone.contains(q))
    cmap = {c.id: c.name for c in db.query(Customer).all()}
    rows = qs.order_by(Contact.id.desc()).all()
    return [ser(x, customer_name=cmap.get(x.customer_id, "")) for x in rows]


@router.post("/contacts")
def create_contact(d: ContactCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return ser(create_obj(db, Contact, d.model_dump(), user, "联系人"))


@router.get("/customers/{cid}/contacts")
def list_cust_contacts(cid: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return ser_list(db.query(Contact).filter(Contact.customer_id == cid).all())


@router.post("/customers/{cid}/contacts")
def add_contact(cid: int, d: ContactCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return ser(create_obj(db, Contact, d.model_dump(), user, "联系人", {"customer_id": cid}))


@router.put("/contacts/{tid}")
def update_contact(tid: int, data: dict = Body(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = db.query(Contact).filter(Contact.id == tid).first()
    if not c:
        raise HTTPException(status_code=404, detail="联系人不存在")
    return ser(update_obj(db, c, data, user, "联系人"))


@router.delete("/contacts/{tid}")
def del_contact(tid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = db.query(Contact).filter(Contact.id == tid).first()
    if not c:
        raise HTTPException(status_code=404, detail="联系人不存在")
    return delete_obj(db, c, user, "联系人")


# ---------------------------------------------------------------- 标签
@router.get("/customers/{cid}/tags")
def list_tags(cid: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return [t.tag for t in db.query(CustomerTag).filter(CustomerTag.customer_id == cid).all()]


@router.post("/customers/{cid}/tags")
def add_tag(cid: int, tag: str = Body(..., embed=True), db: Session = Depends(get_db),
            user=Depends(get_current_user)):
    if not db.query(CustomerTag).filter(CustomerTag.customer_id == cid, CustomerTag.tag == tag).first():
        db.add(CustomerTag(customer_id=cid, tag=tag)); db.commit()
    return {"ok": True}


@router.delete("/customers/{cid}/tags")
def del_tag(cid: int, tag: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    db.query(CustomerTag).filter(CustomerTag.customer_id == cid, CustomerTag.tag == tag).delete()
    db.commit(); return {"ok": True}


# ---------------------------------------------------------------- 合同
@router.get("/contracts")
def list_contracts(q: str = "", status: str = "", customer_id: int = 0,
                   db: Session = Depends(get_db), user=Depends(get_current_user)):
    qs = db.query(Contract)
    if customer_id:
        qs = qs.filter(Contract.customer_id == customer_id)
    else:
        cids = [c.id for c in _apply_scope(db.query(Customer), db, user).all()]
        qs = qs.filter(Contract.customer_id.in_(cids))
    if q:
        qs = qs.filter(Contract.title.contains(q) | Contract.contract_no.contains(q))
    if status:
        qs = qs.filter(Contract.status == status)
    cmap = {c.id: c.name for c in db.query(Customer).all()}
    owners = {u.id: u.name for u in db.query(User).all()}
    out = []
    for c in qs.order_by(Contract.id.desc()).all():
        days = None
        if c.end_date:
            days = (c.end_date - datetime.now().date()).days
        out.append(ser(c, customer_name=cmap.get(c.customer_id, ""),
                       owner_name=owners.get(c.owner_id, ""), remain_days=days))
    return out


@router.post("/contracts")
def add_contract(data: dict = Body(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    if not data.get("contract_no"):
        from app.utils import gen_no
        data["contract_no"] = gen_no("HT")
    return ser(create_obj(db, Contract, data, user, "合同", {"owner_id": user.id}))


@router.put("/contracts/{cid}")
def update_contract(cid: int, data: dict = Body(...), db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    c = db.query(Contract).filter(Contract.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="合同不存在")
    return ser(update_obj(db, c, data, user, "合同"))


@router.delete("/contracts/{cid}")
def del_contract(cid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = db.query(Contract).filter(Contract.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="合同不存在")
    return delete_obj(db, c, user, "合同")


@router.get("/customers/{cid}/contracts")
def cust_contracts(cid: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return ser_list(db.query(Contract).filter(Contract.customer_id == cid).all())


# ---------------------------------------------------------------- 360 视图
@router.get("/customers/{cid}/360")
def customer_360(cid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = _apply_scope(db.query(Customer), db, user).filter(Customer.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="客户不可见或不存在")

    def q(model, *crit):
        return db.query(model).filter(*crit)

    orders = q(Order, Order.customer_id == cid).order_by(Order.created_at.desc()).all()
    order_total = money(sum(o.total_amount or 0 for o in orders if o.status != "已取消"))
    paid_total = money(sum(p.amount or 0 for p in q(Payment, Payment.customer_id == cid).all()))
    followups = q(FollowUp, FollowUp.customer_id == cid).order_by(FollowUp.created_at.desc()).limit(50).all()
    products = {}
    from app.models import OrderItem, Product, QuotationItem, Quotation
    for it in db.query(OrderItem).join(Order, Order.id == OrderItem.order_id) \
            .filter(Order.customer_id == cid).all():
        products[it.product_id] = products.get(it.product_id, 0) + (it.amount or 0)
    pmap = {p.id: p.name for p in db.query(Product).all()}
    top_products = sorted(
        [{"name": pmap.get(k, f"产品{k}"), "amount": money(v)} for k, v in products.items()],
        key=lambda x: -x["amount"])[:5]

    timeline = []
    for f in followups[:10]:
        timeline.append({"type": "跟进", "time": f.created_at.strftime("%Y-%m-%d %H:%M") if f.created_at else "",
                         "title": f"{f.ftype}跟进", "content": f.content or ""})
    for o in orders[:8]:
        timeline.append({"type": "订单", "time": o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "",
                         "title": f"订单 {o.order_no}", "content": f"金额 ¥{money(o.total_amount)} · {o.status}"})
    for cp in q(Complaint, Complaint.customer_id == cid).all()[:5]:
        timeline.append({"type": "客诉", "time": cp.created_at.strftime("%Y-%m-%d %H:%M") if cp.created_at else "",
                         "title": f"客诉 {cp.ctype or ''}", "content": cp.description or ""})
    timeline.sort(key=lambda x: x["time"], reverse=True)

    return {
        "customer": _enrich(db, [c])[0],
        "contacts": ser_list(q(Contact, Contact.customer_id == cid).all()),
        "tags": [t.tag for t in q(CustomerTag, CustomerTag.customer_id == cid).all()],
        "contracts": ser_list(q(Contract, Contract.customer_id == cid).all()),
        "visits": ser_list(q(Visit, Visit.customer_id == cid).order_by(Visit.created_at.desc()).all()),
        "followups": ser_list(followups),
        "samples": ser_list(q(SampleApplication, SampleApplication.customer_id == cid).all()),
        "opportunities": ser_list(q(Opportunity, Opportunity.customer_id == cid).all()),
        "orders": ser_list(orders),
        "payments": ser_list(q(Payment, Payment.customer_id == cid).all()),
        "invoices": ser_list(q(Invoice, Invoice.customer_id == cid).all()),
        "complaints": ser_list(q(Complaint, Complaint.customer_id == cid).all()),
        "rebates": ser_list(q(RebateRecord, RebateRecord.customer_id == cid).all()),
        "cross_sales": ser_list(q(CrossSale, CrossSale.dealer_id == cid).all()),
        "timeline": timeline,
        "top_products": top_products,
        "stats": {
            "order_total": order_total,
            "paid_total": paid_total,
            "receivable": money(order_total - paid_total),
            "order_count": len(orders),
            "avg_order": money(order_total / len(orders)) if orders else 0,
            "complaint_count": q(Complaint, Complaint.customer_id == cid).count(),
            "credit_limit": money(c.credit_limit),
            "credit_used_rate": round((order_total - paid_total) / (c.credit_limit or 1) * 100, 1) if c.credit_limit else 0,
        },
    }
