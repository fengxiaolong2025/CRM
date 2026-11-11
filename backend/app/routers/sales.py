"""销售流程：跟进记录、商机、报价、订单、样品、拜访"""
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import (
    FollowUp, Opportunity, Quotation, QuotationItem, Order, OrderItem,
    Payment, Product, Customer, User, Lead, SampleApplication, SampleItem,
    SampleRecord, Visit, OPP_STAGES,
)
from app.schemas import (
    VisitCreate, SampleApplicationCreate, SampleRecordCreate, OpportunityCreate,
    QuotationCreate, OrderCreate,
)
from app.deps import get_current_user, require_roles, customer_owner_filter, is_manager_or_above
from app.utils import ser, ser_list, money, log, apply_scope, gen_no, scope_ids
from app.crud import create_obj, update_obj, delete_obj

router = APIRouter(prefix="/api", tags=["sales"])


def _cust_scope(qs, db, user):
    owners, _ = customer_owner_filter(db, user)
    if owners is not None:
        qs = qs.filter(Customer.owner_id.in_(owners))
    return qs


def _names(db):
    return ({c.id: c.name for c in db.query(Customer).all()},
            {u.id: u.name for u in db.query(User).all()},
            {p.id: p.name for p in db.query(Product).all()})


# ================================================================ 跟进记录
@router.get("/followups")
def list_followups(q: str = "", customer_id: int = 0, lead_id: int = 0, ftype: str = "",
                   scope: str = "auto", limit: int = 500,
                   db: Session = Depends(get_db), user=Depends(get_current_user)):
    qs = apply_scope(db.query(FollowUp), FollowUp, db, user, scope)
    if customer_id:
        qs = qs.filter(FollowUp.customer_id == customer_id)
    if lead_id:
        qs = qs.filter(FollowUp.lead_id == lead_id)
    if ftype:
        qs = qs.filter(FollowUp.ftype == ftype)
    if q:
        qs = qs.filter(FollowUp.content.contains(q) | FollowUp.result.contains(q))
    cmap, umap, _ = _names(db)
    lmap = {l.id: l.customer_name for l in db.query(Lead).all()}
    rows = qs.order_by(FollowUp.created_at.desc()).limit(limit).all()
    return [ser(f, customer_name=cmap.get(f.customer_id, ""), lead_name=lmap.get(f.lead_id, ""),
                owner_name=umap.get(f.owner_id, "")) for f in rows]


def _touch_follow_target(db, f):
    now = datetime.now()
    if f.customer_id:
        c = db.query(Customer).filter(Customer.id == f.customer_id).first()
        if c:
            c.last_follow_at = now
            if f.next_at:
                c.next_follow_at = f.next_at
    if f.lead_id:
        l = db.query(Lead).filter(Lead.id == f.lead_id).first()
        if l:
            l.last_follow_at = now
            if f.next_at:
                l.next_follow_at = f.next_at
            if l.status == "待跟进":
                l.status = "跟进中"
    if f.opportunity_id:
        o = db.query(Opportunity).filter(Opportunity.id == f.opportunity_id).first()
        if o:
            o.last_follow_at = now


@router.post("/followups")
def add_followup(data: dict = Body(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    f = create_obj(db, FollowUp, data, user, "跟进记录", {"owner_id": user.id})
    _touch_follow_target(db, f)
    db.commit()
    return ser(f)


@router.put("/followups/{fid}")
def update_followup(fid: int, data: dict = Body(...), db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    f = db.query(FollowUp).filter(FollowUp.id == fid).first()
    if not f:
        raise HTTPException(status_code=404, detail="跟进记录不存在")
    return ser(update_obj(db, f, data, user, "跟进记录"))


@router.delete("/followups/{fid}")
def del_followup(fid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    f = db.query(FollowUp).filter(FollowUp.id == fid).first()
    if not f:
        raise HTTPException(status_code=404, detail="跟进记录不存在")
    return delete_obj(db, f, user, "跟进记录")


# ================================================================ 拜访
@router.get("/visits")
def list_visits(customer_id: int = 0, db: Session = Depends(get_db), user=Depends(get_current_user)):
    qs = db.query(Visit)
    if customer_id:
        qs = qs.filter(Visit.customer_id == customer_id)
    else:
        qs = apply_scope(qs, Visit, db, user)
    cmap, umap, _ = _names(db)
    return [ser(v, customer_name=cmap.get(v.customer_id, ""), owner_name=umap.get(v.owner_id, ""))
            for v in qs.order_by(Visit.created_at.desc()).all()]


@router.post("/visits")
def add_visit(d: VisitCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    v = Visit(**d.model_dump(exclude_none=True), owner_id=user.id)
    db.add(v); db.commit(); db.refresh(v)
    return ser(v)


# ================================================================ 商机
@router.get("/opportunities")
def list_opps(customer_id: int = 0, stage: str = "", q: str = "", scope: str = "auto",
              include_lost: bool = True, db: Session = Depends(get_db), user=Depends(get_current_user)):
    qs = apply_scope(db.query(Opportunity), Opportunity, db, user, scope)
    if customer_id:
        qs = qs.filter(Opportunity.customer_id == customer_id)
    if stage:
        qs = qs.filter(Opportunity.stage == stage)
    if q:
        qs = qs.filter(Opportunity.name.contains(q))
    if not include_lost:
        qs = qs.filter(Opportunity.is_lost == False)  # noqa
    cmap, umap, pmap = _names(db)
    out = []
    for o in qs.order_by(Opportunity.created_at.desc()).all():
        out.append(ser(o, customer_name=cmap.get(o.customer_id, ""), owner_name=umap.get(o.owner_id, ""),
                       weighted=money((o.amount or 0) * (o.win_prob or 0) / 100),
                       stage_index=(OPP_STAGES.index(o.stage) + 1) if o.stage in OPP_STAGES else 0,
                       days_open=(datetime.now() - o.created_at).days if o.created_at else 0))
    return out


@router.get("/opportunities/board")
def opp_board(scope: str = "auto", db: Session = Depends(get_db), user=Depends(get_current_user)):
    qs = apply_scope(db.query(Opportunity), Opportunity, db, user, scope) \
        .filter(Opportunity.is_lost == False)  # noqa
    cmap, umap, _ = _names(db)
    stages = list(OPP_STAGES)
    board = {s: {"stage": s, "count": 0, "amount": 0.0, "items": []} for s in stages}
    for o in qs.all():
        s = o.stage if o.stage in board else "初步接触"
        board[s]["count"] += 1
        board[s]["amount"] = money(board[s]["amount"] + (o.amount or 0))
        board[s]["items"].append(ser(o, customer_name=cmap.get(o.customer_id, ""),
                                     owner_name=umap.get(o.owner_id, "")))
    return list(board.values())


@router.post("/opportunities")
def add_opp(d: OpportunityCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    o = create_obj(db, Opportunity, d.model_dump(exclude_none=True), user, "商机", {"owner_id": user.id})
    return ser(o)


@router.put("/opportunities/{oid}")
def update_opp(oid: int, data: dict = Body(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    o = db.query(Opportunity).filter(Opportunity.id == oid).first()
    if not o:
        raise HTTPException(status_code=404, detail="商机不存在")
    stage = data.pop("stage", None)
    exists = db.query(Opportunity).filter(Opportunity.id == oid).first()
    if stage:
        exists.stage = stage
        if stage == "成交":
            exists.is_lost = False
        if stage == "丢单":
            exists.is_lost = True
    return ser(update_obj(db, exists, data, user, "商机"))


@router.post("/opportunities/{oid}/stage")
def move_stage(oid: int, data: dict = Body(...), db: Session = Depends(get_db),
               user=Depends(get_current_user)):
    o = db.query(Opportunity).filter(Opportunity.id == oid).first()
    if not o:
        raise HTTPException(status_code=404, detail="商机不存在")
    stage = data.get("stage")
    if stage not in OPP_STAGES and stage != "丢单":
        raise HTTPException(status_code=400, detail="非法的商机阶段")
    o.stage = stage
    o.is_lost = stage == "丢单"
    if stage == "丢单":
        o.lost_reason = data.get("lost_reason")
    log(db, user, "阶段变更", "商机", oid, f"商机 {o.name} → {stage}")
    db.commit()
    return ser(o)


@router.delete("/opportunities/{oid}")
def del_opp(oid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    o = db.query(Opportunity).filter(Opportunity.id == oid).first()
    if not o:
        raise HTTPException(status_code=404, detail="商机不存在")
    return delete_obj(db, o, user, "商机")


# ================================================================ 报价
def _quote_out(db, q):
    cmap, umap, pmap = _names(db)
    items = db.query(QuotationItem).filter(QuotationItem.quotation_id == q.id).all()
    return ser(q, customer_name=cmap.get(q.customer_id, ""), owner_name=umap.get(q.owner_id, ""),
               items=[ser(i, product_name=pmap.get(i.product_id, "")) for i in items])


@router.get("/quotations")
def list_quotations(customer_id: int = 0, status: str = "", db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    qs = db.query(Quotation)
    if customer_id:
        qs = qs.filter(Quotation.customer_id == customer_id)
    elif not is_manager_or_above(user.role) and user.role not in ("finance",):
        qs = qs.filter(Quotation.owner_id == user.id)
    if status:
        qs = qs.filter(Quotation.status == status)
    return [_quote_out(db, q) for q in qs.order_by(Quotation.id.desc()).all()]


@router.get("/quotations/{qid}")
def get_quotation(qid: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q:
        raise HTTPException(status_code=404, detail="报价单不存在")
    return _quote_out(db, q)


@router.post("/quotations")
def add_quotation(d: QuotationCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = Quotation(customer_id=d.customer_id, opportunity_id=d.opportunity_id,
                  quote_no=gen_no("BJ"), owner_id=user.id, status="草稿")
    db.add(q); db.flush()
    total = 0.0
    for it in d.items:
        prod = db.query(Product).filter(Product.id == it.product_id).first()
        supply = prod.supply_price if prod else 0
        if it.unit_price < supply:
            q.special_price = True
        amt = it.qty * it.unit_price
        total += amt
        db.add(QuotationItem(quotation_id=q.id, product_id=it.product_id,
                             qty=it.qty, unit_price=it.unit_price, amount=amt))
    q.total_amount = total
    if q.special_price:
        q.status = "待审批"
    db.commit(); db.refresh(q)
    log(db, user, "新增", "报价单", q.id, f"报价单 {q.quote_no} 金额 ¥{money(total)}")
    return _quote_out(db, q)


@router.post("/quotations/{qid}/submit")
def submit_quotation(qid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q:
        raise HTTPException(status_code=404, detail="报价单不存在")
    q.status = "待审批"
    db.commit(); return _quote_out(db, q)


@router.post("/quotations/{qid}/approve")
def approve_discount(qid: int, approve: bool = True, db: Session = Depends(get_db),
                     user=Depends(require_roles("regional_manager", "sales_director", "super_admin"))):
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q:
        raise HTTPException(status_code=404, detail="报价单不存在")
    q.discount_approved = approve
    q.status = "已通过" if approve else "已驳回"
    db.commit()
    log(db, user, "审批", "报价单", qid, f"报价单 {q.quote_no} {'通过' if approve else '驳回'}")
    return _quote_out(db, q)


# ================================================================ 订单
def _order_out(db, o):
    cmap, umap, pmap = _names(db)
    items = db.query(OrderItem).filter(OrderItem.order_id == o.id).all()
    paid = money(db.query(func.coalesce(func.sum(Payment.amount), 0))
                 .filter(Payment.order_id == o.id).scalar() or 0)
    return ser(o, customer_name=cmap.get(o.customer_id, ""), owner_name=umap.get(o.owner_id, ""),
               paid_amount=paid, remain=money((o.total_amount or 0) - paid),
               items=[ser(i, product_name=pmap.get(i.product_id, "")) for i in items])


@router.get("/orders")
def list_orders(customer_id: int = 0, status: str = "", q: str = "", scope: str = "auto",
                db: Session = Depends(get_db), user=Depends(get_current_user)):
    qs = db.query(Order)
    if customer_id:
        qs = qs.filter(Order.customer_id == customer_id)
    else:
        ids = scope_ids(db, user, scope)
        if ids is not None and not is_manager_or_above(user.role):
            qs = qs.filter(Order.owner_id.in_(ids))
    if status:
        qs = qs.filter(Order.status == status)
    if q:
        qs = qs.filter(Order.order_no.contains(q))
    return [_order_out(db, o) for o in qs.order_by(Order.id.desc()).all()]


@router.get("/orders/{oid}")
def get_order(oid: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    o = db.query(Order).filter(Order.id == oid).first()
    if not o:
        raise HTTPException(status_code=404, detail="订单不存在")
    return _order_out(db, o)


@router.post("/orders")
def add_order(d: OrderCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    o = Order(order_no=gen_no("SO"), customer_id=d.customer_id, quotation_id=d.quotation_id,
              owner_id=user.id, account_term=d.account_term, ship_date=d.ship_date or None,
              remark=d.remark, status="待确认", receiver=d.receiver,
              receiver_phone=d.receiver_phone, address=d.address)
    db.add(o); db.flush()
    total = 0.0
    for it in d.items:
        amt = it.qty * it.unit_price
        total += amt
        db.add(OrderItem(order_id=o.id, product_id=it.product_id, qty=it.qty,
                         unit_price=it.unit_price, amount=amt))
    o.total_amount = total
    # 金额 ≥ 5 万需总监确认
    db.commit(); db.refresh(o)
    log(db, user, "新增", "订单", o.id, f"订单 {o.order_no} 金额 ¥{money(total)}")
    return _order_out(db, o)


@router.put("/orders/{oid}/status")
def update_order_status(oid: int, status: str = "", data: dict = Body(default={}),
                        db: Session = Depends(get_db), user=Depends(get_current_user)):
    o = db.query(Order).filter(Order.id == oid).first()
    if not o:
        raise HTTPException(status_code=404, detail="订单不存在")
    new_status = status or data.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="缺少状态")
    o.status = new_status
    if new_status == "已发货":
        o.delivery_no = data.get("delivery_no") or o.delivery_no or gen_no("FH")
    if data.get("ship_date"):
        from app.crud import parse_date
        o.ship_date = parse_date(data["ship_date"])
    db.commit()
    log(db, user, "状态变更", "订单", oid, f"订单 {o.order_no} → {new_status}")
    return _order_out(db, o)


@router.delete("/orders/{oid}")
def del_order(oid: int, db: Session = Depends(get_db), user=Depends(require_roles("super_admin", "sales_director"))):
    o = db.query(Order).filter(Order.id == oid).first()
    if not o:
        raise HTTPException(status_code=404, detail="订单不存在")
    db.query(OrderItem).filter(OrderItem.order_id == oid).delete()
    return delete_obj(db, o, user, "订单")


# ================================================================ 样品
def _sample_out(db, s):
    cmap, umap, pmap = _names(db)
    items = db.query(SampleItem).filter(SampleItem.application_id == s.id).all()
    return ser(s, customer_name=cmap.get(s.customer_id, ""), owner_name=umap.get(s.owner_id, ""),
               approver_name=umap.get(s.approver_id, ""),
               items=[ser(i, product_name=pmap.get(i.product_id, "")) for i in items])


@router.get("/samples")
def list_samples(status: str = "", db: Session = Depends(get_db), user=Depends(get_current_user)):
    qs = db.query(SampleApplication)
    if not is_manager_or_above(user.role) and user.role not in ("finance",):
        qs = qs.filter(SampleApplication.owner_id == user.id)
    if status:
        qs = qs.filter(SampleApplication.status == status)
    return [_sample_out(db, s) for s in qs.order_by(SampleApplication.id.desc()).all()]


@router.post("/samples")
def add_sample(d: SampleApplicationCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    total = 0.0
    sa = SampleApplication(customer_id=d.customer_id, owner_id=user.id,
                           purpose=d.purpose, freight_payer=d.freight_payer,
                           apply_no=gen_no("YP"), status="待审批")
    db.add(sa); db.flush()
    for it in d.items:
        prod = db.query(Product).filter(Product.id == it.product_id).first()
        total += (prod.cost if prod else 0) * it.qty
        db.add(SampleItem(application_id=sa.id, product_id=it.product_id, qty=it.qty))
    sa.total_cost = total
    db.commit(); db.refresh(sa)
    log(db, user, "新增", "样品", sa.id, f"样品申请 {sa.apply_no} 成本 ¥{money(total)}")
    return _sample_out(db, sa)


@router.post("/samples/{sid}/approve")
def approve_sample(sid: int, approve: bool = True, db: Session = Depends(get_db),
                   user=Depends(require_roles("regional_manager", "sales_director", "super_admin"))):
    sa = db.query(SampleApplication).filter(SampleApplication.id == sid).first()
    if not sa:
        raise HTTPException(status_code=404, detail="样品申请不存在")
    sa.status = "已通过" if approve else "已驳回"
    sa.approver_id = user.id
    sa.approved_at = datetime.now()
    db.commit()
    log(db, user, "审批", "样品", sid, f"样品申请 {sa.apply_no} {'通过' if approve else '驳回'}")
    return _sample_out(db, sa)


@router.post("/samples/{sid}/ship")
def ship_sample(sid: int, data: dict = Body(default={}), db: Session = Depends(get_db),
                user=Depends(get_current_user)):
    sa = db.query(SampleApplication).filter(SampleApplication.id == sid).first()
    if not sa:
        raise HTTPException(status_code=404, detail="样品申请不存在")
    sa.status = "已寄出"
    sa.express_no = data.get("express_no") or gen_no("SF")
    db.commit()
    return _sample_out(db, sa)


@router.post("/samples/{sid}/record")
def sample_record(sid: int, d: SampleRecordCreate, db: Session = Depends(get_db),
                  user=Depends(get_current_user)):
    rec = SampleRecord(application_id=sid, **d.model_dump(exclude_none=True))
    db.add(rec)
    sa = db.query(SampleApplication).filter(SampleApplication.id == sid).first()
    if sa and d.received:
        sa.status = "已签收"
    db.commit(); db.refresh(rec)
    return ser(rec)
