"""系统能力：全局搜索、审批中心、消息通知、操作日志、下拉选项"""
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from app.database import get_db
from app.models import (
    Customer, Lead, Contact, Order, Opportunity, Product, Quotation, SampleApplication,
    Complaint, Contract, Payment, User, Region, ChannelType, CustomerLevel,
    ProductCategory, DictItem, Message, AuditLog, RebateRecord,
)
from app.deps import get_current_user
from app.utils import ser, ser_list, money, scope_ids, ROLE_LABELS
from app.crud import create_obj, update_obj, delete_obj

router = APIRouter(prefix="/api", tags=["system"])


def leaf_categories_with_path(db: Session):
    """产品分类下拉：仅返回叶子节点（类目三），name 显示为完整路径 类目一 / 类目二 / 类目三"""
    cats = db.query(ProductCategory).all()
    by_id = {c.id: c for c in cats}
    child_ids = {c.parent_id for c in cats if c.parent_id}
    out = []
    for c in cats:
        if c.id in child_ids:
            continue
        names, cur, guard = [], by_id.get(c.id), 0
        while cur and guard < 10:
            names.insert(0, cur.name)
            cur = by_id.get(cur.parent_id)
            guard += 1
        out.append({"id": c.id, "name": " / ".join(names)})
    return out


# ================================================================ 业务关注（待办）
@router.get("/focus")
def focus(scope: str = "auto", limit: int = 12, db: Session = Depends(get_db),
          user=Depends(get_current_user)):
    from app.routers.analytics import _focus
    return _focus(db, user, scope, limit)


# ================================================================ 全局搜索
@router.get("/search")
def global_search(q: str = "", db: Session = Depends(get_db), user=Depends(get_current_user)):
    if not q or len(q.strip()) < 1:
        return {"groups": [], "total": 0}
    kw = q.strip()
    groups = []

    cids = None
    ids = scope_ids(db, user, "auto")

    cust = db.query(Customer).filter(Customer.status == 1,
                                     or_(Customer.name.contains(kw), Customer.phone.contains(kw),
                                         Customer.credit_code.contains(kw)))
    if ids is not None:
        cust = cust.filter(Customer.owner_id.in_(ids))
    rows = cust.limit(6).all()
    if rows:
        groups.append({"type": "客户", "icon": "customers", "link": "customers",
                       "items": [{"id": c.id, "title": c.name, "desc": f"{c.payment_term or ''} · ID {c.id}"}
                                 for c in rows]})

    leads = db.query(Lead).filter(or_(Lead.customer_name.contains(kw), Lead.phone.contains(kw),
                                      Lead.contact.contains(kw)))
    if ids is not None:
        leads = leads.filter(Lead.owner_id.in_(ids))
    rows = leads.limit(5).all()
    if rows:
        groups.append({"type": "线索", "icon": "leads", "link": "leads",
                       "items": [{"id": l.id, "title": l.customer_name, "desc": l.status} for l in rows]})

    orders = db.query(Order).filter(Order.order_no.contains(kw))
    if ids is not None:
        orders = orders.filter(Order.owner_id.in_(ids))
    rows = orders.limit(5).all()
    if rows:
        cmap = {c.id: c.name for c in db.query(Customer).filter(Customer.id.in_([r.customer_id for r in rows])).all()}
        groups.append({"type": "订单", "icon": "orders", "link": "orders",
                       "items": [{"id": o.id, "title": o.order_no,
                                  "desc": f"{cmap.get(o.customer_id, '')} · ¥{money(o.total_amount)}"}
                                 for o in rows]})

    opps = db.query(Opportunity).filter(Opportunity.name.contains(kw))
    if ids is not None:
        opps = opps.filter(Opportunity.owner_id.in_(ids))
    rows = opps.limit(4).all()
    if rows:
        groups.append({"type": "商机", "icon": "opps", "link": "opportunities",
                       "items": [{"id": o.id, "title": o.name, "desc": f"{o.stage} · ¥{money(o.amount)}"}
                                 for o in rows]})

    prods = db.query(Product).filter(or_(Product.name.contains(kw), Product.code.contains(kw))).limit(4).all()
    if prods:
        groups.append({"type": "产品", "icon": "products", "link": "products",
                       "items": [{"id": p.id, "title": p.name, "desc": f"{p.code} · ¥{money(p.supply_price)}"}
                                 for p in prods]})

    total = sum(len(g["items"]) for g in groups)
    return {"groups": groups, "total": total}


# ================================================================ 审批中心
@router.get("/approvals")
def approvals(db: Session = Depends(get_db), user=Depends(get_current_user)):
    cmap = {c.id: c.name for c in db.query(Customer).all()}
    umap = {u.id: u.name for u in db.query(User).all()}
    items = []
    for s in db.query(SampleApplication).filter(SampleApplication.status == "待审批").all():
        items.append({"type": "样品申请", "id": s.id, "no": s.apply_no,
                      "customer": cmap.get(s.customer_id, ""), "applicant": umap.get(s.owner_id, ""),
                      "amount": money(s.total_cost), "amount_label": "样品成本",
                      "summary": f"{s.purpose or ''} · 运费{s.freight_payer or '-'}",
                      "created_at": s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else ""})
    for q in db.query(Quotation).filter(Quotation.status == "待审批").all():
        items.append({"type": "特价报价", "id": q.id, "no": q.quote_no,
                      "customer": cmap.get(q.customer_id, ""), "applicant": umap.get(q.owner_id, ""),
                      "amount": money(q.total_amount), "amount_label": "报价金额",
                      "summary": "低于建议供货价，需特价审批",
                      "created_at": q.created_at.strftime("%Y-%m-%d %H:%M") if q.created_at else ""})
    for r in db.query(RebateRecord).filter(RebateRecord.status == "待审批").all():
        items.append({"type": "返利兑现", "id": r.id, "no": f"FL{r.id:04d}",
                      "customer": cmap.get(r.customer_id, ""), "applicant": "系统",
                      "amount": money(r.amount), "amount_label": "返利金额",
                      "summary": f"{r.period or ''} · {r.redeem_type or ''}",
                      "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else ""})
    for o in db.query(Order).filter(Order.status == "待确认", Order.total_amount >= 50000).all():
        items.append({"type": "大额订单", "id": o.id, "no": o.order_no,
                      "customer": cmap.get(o.customer_id, ""), "applicant": umap.get(o.owner_id, ""),
                      "amount": money(o.total_amount), "amount_label": "订单金额",
                      "summary": "金额 ≥ 5 万元，需销售总监确认",
                      "created_at": o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else ""})
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items


@router.post("/approvals/act")
def approval_act(data: dict = Body(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    t, rid, approve = data.get("type"), data.get("id"), bool(data.get("approve"))
    if user.role not in ("super_admin", "sales_director", "regional_manager") and t != "大额订单":
        raise HTTPException(status_code=403, detail="无审批权限")
    if t == "样品申请":
        obj = db.query(SampleApplication).filter(SampleApplication.id == rid).first()
        obj.status = "已通过" if approve else "已驳回"
        obj.approver_id = user.id
        obj.approved_at = datetime.now()
    elif t == "特价报价":
        obj = db.query(Quotation).filter(Quotation.id == rid).first()
        obj.status = "已通过" if approve else "已驳回"
        obj.discount_approved = approve
    elif t == "返利兑现":
        obj = db.query(RebateRecord).filter(RebateRecord.id == rid).first()
        obj.status = "已批准" if approve else "待核算"
    elif t == "大额订单":
        obj = db.query(Order).filter(Order.id == rid).first()
        obj.status = "待发货" if approve else "已取消"
    else:
        raise HTTPException(status_code=400, detail="未知审批类型")
    db.commit()
    from app.utils import log
    log(db, user, "审批", "审批中心", rid, f"{t} {'通过' if approve else '驳回'}")
    return {"ok": True}


# ================================================================ 消息通知
@router.get("/notifications")
def notifications(db: Session = Depends(get_db), user=Depends(get_current_user)):
    ids = scope_ids(db, user, "auto")
    out = []
    today = date.today()
    soon = today + timedelta(days=30)

    # 逾期应收
    q = db.query(Order).filter(Order.status != "已取消")
    if ids is not None:
        q = q.filter(Order.owner_id.in_(ids))
    paid_map = {oid: money(a) for oid, a in
                db.query(Payment.order_id, func.coalesce(func.sum(Payment.amount), 0))
                .group_by(Payment.order_id).all()}
    overdue_n, overdue_amt = 0, 0.0
    for o in q.all():
        remain = money((o.total_amount or 0) - paid_map.get(o.id, 0))
        if remain > 0 and o.created_at and (today - o.created_at.date()).days > 45:
            overdue_n += 1
            overdue_amt = money(overdue_amt + remain)
    if overdue_n:
        out.append({"key": "overdue", "level": "danger", "title": f"{overdue_n} 笔订单逾期未回款",
                    "desc": f"合计 ¥{overdue_amt}，请及时催收", "link": "receivables"})

    # 待审批
    pend = db.query(SampleApplication).filter(SampleApplication.status == "待审批").count()
    pend += db.query(Quotation).filter(Quotation.status == "待审批").count()
    if pend and user.role in ("super_admin", "sales_director", "regional_manager"):
        out.append({"key": "approval", "level": "warning", "title": f"{pend} 项审批待处理",
                    "desc": "样品申请 / 特价报价", "link": "approvals"})

    # 合同到期
    ct = db.query(Contract).filter(Contract.end_date.isnot(None), Contract.end_date <= soon,
                                   Contract.status == "执行中").count()
    if ct:
        out.append({"key": "contract", "level": "warning", "title": f"{ct} 份合同 30 天内到期",
                    "desc": "请提前安排续签", "link": "contracts"})

    # 高优先级客诉
    cp = db.query(Complaint).filter(Complaint.status != "已结案", Complaint.urgency == "高").count()
    if cp:
        out.append({"key": "complaint", "level": "danger", "title": f"{cp} 个高优先级客诉未结案",
                    "desc": "建议 24 小时内响应", "link": "complaints"})

    # 今日待跟进
    end = datetime.now().replace(hour=23, minute=59, second=59)
    fq = db.query(Customer).filter(Customer.status == 1, Customer.next_follow_at.isnot(None),
                                   Customer.next_follow_at <= end)
    if ids is not None:
        fq = fq.filter(Customer.owner_id.in_(ids))
    fn = fq.count()
    if fn:
        out.append({"key": "follow", "level": "info", "title": f"今日 {fn} 位客户待跟进",
                    "desc": "进入客户列表查看跟进计划", "link": "customers"})
    return out


@router.get("/messages")
def list_messages(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return ser_list(db.query(Message).filter(Message.user_id == user.id)
                    .order_by(Message.created_at.desc()).limit(50).all())


@router.post("/messages/{mid}/read")
def read_message(mid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    m = db.query(Message).filter(Message.id == mid, Message.user_id == user.id).first()
    if m:
        m.is_read = True
        db.commit()
    return {"ok": True}


@router.post("/messages/read-all")
def read_all(db: Session = Depends(get_db), user=Depends(get_current_user)):
    db.query(Message).filter(Message.user_id == user.id, Message.is_read == False).update({"is_read": True})  # noqa
    db.commit()
    return {"ok": True}


# ================================================================ 操作日志
@router.get("/audit-logs")
def audit_logs(q: str = "", module: str = "", action: str = "",
               db: Session = Depends(get_db), user=Depends(get_current_user)):
    qs = db.query(AuditLog)
    if user.role not in ("super_admin", "sales_director"):
        qs = qs.filter(AuditLog.user_id == user.id)
    if q:
        qs = qs.filter(or_(AuditLog.detail.contains(q), AuditLog.user_name.contains(q)))
    if module:
        qs = qs.filter(AuditLog.module == module)
    if action:
        qs = qs.filter(AuditLog.action == action)
    return ser_list(qs.order_by(AuditLog.id.desc()).limit(500).all())


# ================================================================ 下拉选项（一次取全）
@router.get("/options")
def options(db: Session = Depends(get_db), _=Depends(get_current_user)):
    dicts = {}
    for d in db.query(DictItem).filter(DictItem.active == 1).order_by(DictItem.sort).all():
        dicts.setdefault(d.dtype, []).append(d.name)
    return {
        "customers": [{"id": c.id, "name": c.name, "payment_term": c.payment_term,
                       "credit_limit": c.credit_limit} for c in
                      db.query(Customer).filter(Customer.status == 1).order_by(Customer.name).all()],
        "products": [{"id": p.id, "name": p.name, "code": p.code, "spec": p.spec,
                      "supply_price": p.supply_price, "cost": p.cost, "unit": p.unit}
                     for p in db.query(Product).filter(Product.status == 1).all()],
        "users": [{"id": u.id, "name": u.name, "role": u.role,
                   "role_label": ROLE_LABELS.get(u.role, u.role)}
                  for u in db.query(User).filter(User.status == 1).all()],
        "regions": ser_list(db.query(Region).all()),
        "channels": ser_list(db.query(ChannelType).all()),
        "levels": ser_list(db.query(CustomerLevel).all()),
        "categories": leaf_categories_with_path(db),
        "dicts": dicts,
        "orders": [{"id": o.id, "order_no": o.order_no, "customer_id": o.customer_id,
                    "total_amount": o.total_amount}
                   for o in db.query(Order).filter(Order.status != "已取消")
                   .order_by(Order.id.desc()).limit(300).all()],
    }
