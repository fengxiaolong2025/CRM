"""工作台与多维度分析看板"""
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import (
    Customer, CustomerLevel, ChannelType, Region, Lead, Opportunity, Order, OrderItem,
    Payment, Product, ProductCategory, SampleApplication, Complaint, Contract, FollowUp,
    User, SalesTarget, Invoice, RebateRecord, OPP_STAGES,
)
from app.deps import get_current_user, is_manager_or_above
from app.utils import (
    ser, ser_list, money, pct, period_range, in_range, scope_ids, apply_scope, PERIODS,
)
from app.crud import create_obj, update_obj, delete_obj

router = APIRouter(prefix="/api", tags=["analytics"])


def _kpi(label, value, prev=None, unit="", icon="", kind="num"):
    return {"label": label, "value": value, "prev": prev, "unit": unit,
            "growth": pct(value, prev) if prev is not None else None, "icon": icon, "kind": kind}


def _scoped(db, model, user, scope, col="owner_id"):
    return apply_scope(db.query(model), model, db, user, scope, col)


# ================================================================ 工作台
@router.get("/dashboard")
def dashboard(scope: str = "auto", period: str = "month",
              db: Session = Depends(get_db), user=Depends(get_current_user)):
    s, e, ps, pe = period_range(period)
    now = datetime.now()

    def cnt(model, col=None, extra=None, rng=(s, e)):
        qs = _scoped(db, model, user, scope)
        if extra is not None:
            qs = qs.filter(extra)
        qs = in_range(qs, col or model.created_at, rng[0], rng[1])
        return qs.count()

    def amt(model, field, extra=None, rng=(s, e)):
        qs = _scoped(db, model, user, scope)
        if extra is not None:
            qs = qs.filter(extra)
        qs = in_range(qs, model.created_at, rng[0], rng[1])
        return money(qs.with_entities(func.coalesce(func.sum(field), 0)).scalar() or 0)

    new_cust = cnt(Customer, Customer.created_at)
    new_cust_p = cnt(Customer, Customer.created_at, rng=(ps, pe))
    new_opp = cnt(Opportunity, Opportunity.created_at)
    new_opp_p = cnt(Opportunity, Opportunity.created_at, rng=(ps, pe))
    opp_amt = amt(Opportunity, Opportunity.amount)
    opp_amt_p = amt(Opportunity, Opportunity.amount, rng=(ps, pe))
    follows = cnt(FollowUp, FollowUp.created_at)
    follows_p = cnt(FollowUp, FollowUp.created_at, rng=(ps, pe))
    sales = amt(Order, Order.total_amount, Order.status != "已取消")
    sales_p = amt(Order, Order.total_amount, Order.status != "已取消", rng=(ps, pe))
    orders_n = cnt(Order, Order.created_at, Order.status != "已取消")
    orders_p = cnt(Order, Order.created_at, Order.status != "已取消", rng=(ps, pe))
    pay_q = in_range(_scoped(db, Payment, user, scope), Payment.pay_date,
                     s.date() if s else None, e.date() if e else None)
    pay = money(pay_q.with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar() or 0)
    pay_pq = in_range(_scoped(db, Payment, user, scope), Payment.pay_date,
                      ps.date() if ps else None, pe.date() if pe else None)
    pay_p = money(pay_pq.with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar() or 0)

    kpis = [
        _kpi("新增客户", new_cust, new_cust_p, "家", "customers"),
        _kpi("新增商机", new_opp, new_opp_p, "个", "opps"),
        _kpi("商机预计金额", opp_amt, opp_amt_p, "元", "money"),
        _kpi("跟进次数", follows, follows_p, "次", "follow"),
        _kpi("销售额", sales, sales_p, "元", "money"),
        _kpi("回款额", pay, pay_p, "元", "money"),
        _kpi("订单数", orders_n, orders_p, "笔", "orders"),
    ]

    # 漏斗
    funnel = []
    base = _scoped(db, Opportunity, user, scope).filter(Opportunity.is_lost == False)  # noqa
    for st in OPP_STAGES:
        q = base.filter(Opportunity.stage == st)
        funnel.append({"stage": st, "count": q.count(),
                       "amount": money(q.with_entities(func.coalesce(func.sum(Opportunity.amount), 0)).scalar() or 0)})

    # 渠道销售占比
    channel = db.query(ChannelType.name, func.coalesce(func.sum(Order.total_amount), 0)) \
        .join(Customer, Customer.channel_type_id == ChannelType.id) \
        .join(Order, Order.customer_id == Customer.id) \
        .filter(Order.status != "已取消").group_by(ChannelType.name).all()

    # 订单状态
    ostatus = db.query(Order.status, func.count(Order.id)).group_by(Order.status).all()

    # 近 12 个月趋势
    trend = _monthly_trend(db, user, scope)

    # 业务关注（待办）
    todo = _focus(db, user, scope)

    # Top 客户
    top_cust = _top_customers(db, user, scope, 5)

    return {
        "scope": scope, "period": period, "period_label": PERIODS.get(period, period),
        "kpis": kpis,
        "funnel": funnel,
        "channel_sales": [{"name": c or "未分类", "value": money(a)} for c, a in channel],
        "order_status": [{"name": st, "value": n} for st, n in ostatus],
        "trend": trend,
        "todo": todo,
        "top_customers": top_cust,
        "pipeline": {
            "amount": money(base.with_entities(func.coalesce(func.sum(Opportunity.amount), 0)).scalar() or 0),
            "weighted": money(base.with_entities(
                func.coalesce(func.sum(Opportunity.amount * Opportunity.win_prob / 100), 0)).scalar() or 0),
            "count": base.count(),
        },
    }


def _monthly_trend(db, user, scope, months=12):
    ids = scope_ids(db, user, scope)
    start = datetime.now().replace(day=1) - timedelta(days=31 * (months - 1))
    start = datetime(start.year, start.month, 1)

    oq = db.query(func.strftime("%Y-%m", Order.created_at), func.coalesce(func.sum(Order.total_amount), 0)) \
        .filter(Order.created_at >= start, Order.status != "已取消")
    pq = db.query(func.strftime("%Y-%m", Payment.pay_date), func.coalesce(func.sum(Payment.amount), 0)) \
        .filter(Payment.pay_date >= start.date())
    if ids is not None:
        oq = oq.filter(Order.owner_id.in_(ids))
        pq = pq.filter(Payment.owner_id.in_(ids))
    omap = {m: money(a) for m, a in oq.group_by(func.strftime("%Y-%m", Order.created_at)).all()}
    pmap = {m: money(a) for m, a in pq.group_by(func.strftime("%Y-%m", Payment.pay_date)).all()}

    labels, sales, pays = [], [], []
    cur = start
    for _ in range(months):
        key = cur.strftime("%Y-%m")
        labels.append(key[2:])
        sales.append(omap.get(key, 0))
        pays.append(pmap.get(key, 0))
        cur = (cur.replace(day=28) + timedelta(days=5)).replace(day=1)
    return {"labels": labels, "sales": sales, "payments": pays}


def _focus(db, user, scope, limit=8):
    """业务关注：待办聚合"""
    now = datetime.now()
    today_end = datetime(now.year, now.month, now.day) + timedelta(days=1)
    items = []

    # 1. 今日/逾期待跟进客户
    q = _scoped(db, Customer, user, scope).filter(
        Customer.status == 1, Customer.next_follow_at.isnot(None),
        Customer.next_follow_at < today_end, Customer.is_pool == False)  # noqa
    for c in q.order_by(Customer.next_follow_at).limit(limit).all():
        items.append({"type": "待跟进", "level": "high" if c.next_follow_at < now else "normal",
                      "title": c.name, "desc": f"计划跟进 {c.next_follow_at.strftime('%m-%d %H:%M')}",
                      "link": "customers", "id": c.id})

    # 2. 逾期应收
    rows = db.query(Order).filter(Order.status != "已取消")
    ids = scope_ids(db, user, scope)
    if ids is not None:
        rows = rows.filter(Order.owner_id.in_(ids))
    paid_map = {oid: money(a) for oid, a in
                db.query(Payment.order_id, func.coalesce(func.sum(Payment.amount), 0))
                .group_by(Payment.order_id).all()}
    for o in rows.order_by(Order.created_at).limit(200).all():
        remain = money((o.total_amount or 0) - paid_map.get(o.id, 0))
        if remain <= 0.01:
            continue
        days = (date.today() - (o.created_at.date() if o.created_at else date.today())).days
        if days > 45:
            cust = db.query(Customer).filter(Customer.id == o.customer_id).first()
            items.append({"type": "逾期应收", "level": "high",
                          "title": f"{cust.name if cust else '客户'} · ¥{remain}",
                          "desc": f"订单 {o.order_no} 已 {days} 天未结清", "link": "receivables", "id": o.id})

    # 3. 待审批
    if is_manager_or_above(user.role):
        for s in db.query(SampleApplication).filter(SampleApplication.status == "待审批").limit(5).all():
            cust = db.query(Customer).filter(Customer.id == s.customer_id).first()
            items.append({"type": "待审批", "level": "normal",
                          "title": f"样品申请 {s.apply_no or ''}", "desc": cust.name if cust else "",
                          "link": "approvals", "id": s.id})
    # 4. 高优先级客诉
    for c in db.query(Complaint).filter(Complaint.status != "已结案",
                                        Complaint.urgency == "高").limit(5).all():
        cust = db.query(Customer).filter(Customer.id == c.customer_id).first()
        items.append({"type": "紧急客诉", "level": "high",
                      "title": f"{c.ctype or '客诉'} · {cust.name if cust else ''}",
                      "desc": (c.description or "")[:40], "link": "complaints", "id": c.id})
    # 5. 合同即将到期
    soon = date.today() + timedelta(days=30)
    for ct in db.query(Contract).filter(Contract.end_date.isnot(None), Contract.end_date <= soon,
                                        Contract.status == "执行中").limit(5).all():
        cust = db.query(Customer).filter(Customer.id == ct.customer_id).first()
        items.append({"type": "合同到期", "level": "normal",
                      "title": ct.title, "desc": f"{cust.name if cust else ''} · {ct.end_date} 到期",
                      "link": "contracts", "id": ct.id})
    order_key = {"high": 0, "normal": 1}
    items.sort(key=lambda x: order_key.get(x["level"], 1))
    return items[:limit]


def _top_customers(db, user, scope, limit=5):
    ids = scope_ids(db, user, scope)
    q = db.query(Customer.id, Customer.name, func.coalesce(func.sum(Order.total_amount), 0)) \
        .join(Order, Order.customer_id == Customer.id).filter(Order.status != "已取消")
    if ids is not None:
        q = q.filter(Customer.owner_id.in_(ids))
    rows = q.group_by(Customer.id, Customer.name).order_by(
        func.sum(Order.total_amount).desc()).limit(limit).all()
    return [{"id": i, "name": n, "amount": money(a)} for i, n, a in rows]


# ================================================================ 客户分析
@router.get("/analysis/customer")
def analysis_customer(period: str = "all", scope: str = "auto",
                      db: Session = Depends(get_db), user=Depends(get_current_user)):
    s, e, ps, pe = period_range(period)
    base = _scoped(db, Customer, user, scope).filter(Customer.status == 1, Customer.is_pool == False)  # noqa
    total = base.count()
    new_in = in_range(base, Customer.created_at, s, e).count() if s else total
    prev_in = in_range(base, Customer.created_at, ps, pe).count() if ps else 0

    # 活跃/沉睡（90 天无跟进）
    cut = datetime.now() - timedelta(days=90)
    active_ids = {f.customer_id for f in db.query(FollowUp).filter(
        FollowUp.created_at >= cut, FollowUp.customer_id.isnot(None)).all()}
    active_ids |= {o.customer_id for o in db.query(Order).filter(Order.created_at >= cut).all()}
    active = len([c.id for c in base.all() if c.id in active_ids])
    sleeping = max(total - active, 0)

    level_map = {l.id: l.name for l in db.query(CustomerLevel).all()}
    by_level = {}
    by_type = {}
    by_channel = {}
    ch_map = {c.id: c.name for c in db.query(ChannelType).all()}
    type_label = {"dealer": "经销商", "restaurant": "餐饮门店", "supermarket": "商超", "group": "企业团购"}
    for c in base.all():
        by_level[level_map.get(c.level_id, "未分级")] = by_level.get(level_map.get(c.level_id, "未分级"), 0) + 1
        tl = type_label.get(c.customer_type, c.customer_type or "其他")
        by_type[tl] = by_type.get(tl, 0) + 1
        cn = ch_map.get(c.channel_type_id, "未分类")
        by_channel[cn] = by_channel.get(cn, 0) + 1

    # 月度新增
    months = db.query(func.strftime("%Y-%m", Customer.created_at), func.count(Customer.id)) \
        .filter(Customer.status == 1).group_by(func.strftime("%Y-%m", Customer.created_at)).all()
    months = sorted(months, key=lambda x: x[0])[-12:]

    # 客户贡献
    contrib = _top_customers(db, user, scope, 10)
    contrib_total = money(sum(c["amount"] for c in contrib))
    for c in contrib:
        c["rate"] = round(c["amount"] / contrib_total * 100, 1) if contrib_total else 0

    return {
        "total": total, "new": new_in, "new_prev": prev_in, "new_growth": pct(new_in, prev_in),
        "active": active, "sleeping": sleeping,
        "active_rate": round(active / total * 100, 1) if total else 0,
        "by_level": [{"name": k, "value": v} for k, v in by_level.items()],
        "by_type": [{"name": k, "value": v} for k, v in by_type.items()],
        "by_channel": [{"name": k, "value": v} for k, v in by_channel.items()],
        "monthly_new": {"labels": [m[2:] for m, _ in months], "values": [v for _, v in months]},
        "top_customers": contrib,
        "pool_count": db.query(Customer).filter(Customer.is_pool == True, Customer.status == 1).count(),  # noqa
    }


# ================================================================ 销售分析
@router.get("/analysis/sales")
def analysis_sales(period: str = "year", scope: str = "auto",
                   db: Session = Depends(get_db), user=Depends(get_current_user)):
    s, e, ps, pe = period_range(period)
    ids = scope_ids(db, user, scope)

    def oq():
        q = db.query(Order).filter(Order.status != "已取消")
        if ids is not None:
            q = q.filter(Order.owner_id.in_(ids))
        return in_range(q, Order.created_at, s, e)

    total = money(oq().with_entities(func.coalesce(func.sum(Order.total_amount), 0)).scalar() or 0)
    cnt = oq().count()
    pq = db.query(Payment)
    if ids is not None:
        pq = pq.filter(Payment.owner_id.in_(ids))
    paid = money(in_range(pq, Payment.pay_date, s.date() if s else None, e.date() if e else None)
                 .with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar() or 0)

    # 品类销售
    cat = db.query(Product.category, func.coalesce(func.sum(OrderItem.amount), 0)) \
        .join(OrderItem, OrderItem.product_id == Product.id) \
        .join(Order, Order.id == OrderItem.order_id).filter(Order.status != "已取消")
    if ids is not None:
        cat = cat.filter(Order.owner_id.in_(ids))
    cat = in_range(cat, Order.created_at, s, e).group_by(Product.category).all()

    # Top 产品
    tp = db.query(Product.name, func.coalesce(func.sum(OrderItem.amount), 0),
                  func.coalesce(func.sum(OrderItem.qty), 0)) \
        .join(OrderItem, OrderItem.product_id == Product.id) \
        .join(Order, Order.id == OrderItem.order_id).filter(Order.status != "已取消")
    if ids is not None:
        tp = tp.filter(Order.owner_id.in_(ids))
    tp = in_range(tp, Order.created_at, s, e).group_by(Product.name) \
        .order_by(func.sum(OrderItem.amount).desc()).limit(8).all()

    # Top 业务员
    tr = db.query(User.name, func.coalesce(func.sum(Order.total_amount), 0), func.count(Order.id)) \
        .join(Order, Order.owner_id == User.id).filter(Order.status != "已取消")
    tr = in_range(tr, Order.created_at, s, e).group_by(User.name) \
        .order_by(func.sum(Order.total_amount).desc()).limit(8).all()

    # 订单状态
    st = oq().with_entities(Order.status, func.count(Order.id)).group_by(Order.status).all()
    # 月度趋势
    trend = _monthly_trend(db, user, scope, 12)

    return {
        "total": total, "orders": cnt, "paid": paid,
        "avg_order": money(total / cnt) if cnt else 0,
        "collection_rate": round(paid / total * 100, 1) if total else 0,
        "categories": [{"name": c or "未分类", "value": money(a)} for c, a in cat],
        "top_products": [{"name": n, "amount": money(a), "qty": q} for n, a, q in tp],
        "top_reps": [{"name": n, "amount": money(a), "orders": c} for n, a, c in tr],
        "order_status": [{"name": k, "value": v} for k, v in st],
        "trend": trend,
    }


# ================================================================ 财务分析
@router.get("/analysis/finance")
def analysis_finance(period: str = "year", scope: str = "auto",
                     db: Session = Depends(get_db), user=Depends(get_current_user)):
    from app.routers.finance import receivables
    rows = receivables(scope=scope, db=db, user=user)
    buckets = ["未到期", "逾期1-30天", "逾期31-60天", "逾期61-90天", "逾期90天以上"]
    aging = {b: 0.0 for b in buckets}
    for r in rows:
        aging[r["bucket"]] = money(aging.get(r["bucket"], 0) + r["remain"])
    debtors = {}
    for r in rows:
        debtors[r["customer_name"]] = money(debtors.get(r["customer_name"], 0) + r["remain"])
    top_debtors = sorted([{"name": k, "amount": v} for k, v in debtors.items()],
                         key=lambda x: -x["amount"])[:8]

    trend = _monthly_trend(db, user, scope, 12)
    total_order = money(sum(trend["sales"]))
    total_paid = money(sum(trend["payments"]))
    inv = money(db.query(func.coalesce(func.sum(Invoice.amount), 0))
                .filter(Invoice.status != "已作废").scalar() or 0)
    return {
        "receivable_total": money(sum(r["remain"] for r in rows)),
        "overdue_total": money(sum(r["remain"] for r in rows if r["overdue_days"] > 0)),
        "overdue_count": len([r for r in rows if r["overdue_days"] > 0]),
        "aging": [{"name": k, "value": v} for k, v in aging.items()],
        "top_debtors": top_debtors,
        "trend": trend,
        "collection_rate": round(total_paid / total_order * 100, 1) if total_order else 0,
        "invoice_total": inv,
        "uninvoiced": money(total_order - inv),
    }


# ================================================================ 业绩目标
@router.get("/analysis/target")
def analysis_target(year: int = 0, db: Session = Depends(get_db), user=Depends(get_current_user)):
    year = year or datetime.now().year
    rows = []
    for t in db.query(SalesTarget).filter(SalesTarget.year == year).order_by(SalesTarget.month).all():
        u = db.query(User).filter(User.id == t.user_id).first() if t.user_id else None
        # 实际业绩
        q = db.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(Order.status != "已取消")
        if t.user_id:
            q = q.filter(Order.owner_id == t.user_id)
        if t.month:
            start = datetime(year, t.month, 1)
            end = datetime(year + 1, 1, 1) if t.month == 12 else datetime(year, t.month + 1, 1)
            q = q.filter(Order.created_at >= start, Order.created_at < end)
        else:
            q = q.filter(Order.created_at >= datetime(year, 1, 1),
                         Order.created_at < datetime(year + 1, 1, 1))
        actual = money(q.scalar() or 0)
        rows.append(ser(t, user_name=u.name if u else "全公司",
                        actual=actual,
                        rate=round(actual / (t.target_amount or 1) * 100, 1) if t.target_amount else 0,
                        gap=money((t.target_amount or 0) - actual)))
    # 月度达成（全公司）
    monthly = []
    for m in range(1, 13):
        start = datetime(year, m, 1)
        end = datetime(year + 1, 1, 1) if m == 12 else datetime(year, m + 1, 1)
        actual = money(db.query(func.coalesce(func.sum(Order.total_amount), 0))
                       .filter(Order.status != "已取消", Order.created_at >= start,
                               Order.created_at < end).scalar() or 0)
        tgt = money(db.query(func.coalesce(func.sum(SalesTarget.target_amount), 0))
                    .filter(SalesTarget.year == year, SalesTarget.month == m,
                            SalesTarget.user_id.is_(None)).scalar() or 0)
        monthly.append({"month": f"{m}月", "actual": actual, "target": tgt})
    total_target = money(sum(m["target"] for m in monthly))
    total_actual = money(sum(m["actual"] for m in monthly))
    return {"year": year, "rows": rows, "monthly": monthly,
            "total_target": total_target, "total_actual": total_actual,
            "total_rate": round(total_actual / total_target * 100, 1) if total_target else 0}


@router.get("/targets")
def list_targets(year: int = 0, db: Session = Depends(get_db), _=Depends(get_current_user)):
    qs = db.query(SalesTarget)
    if year:
        qs = qs.filter(SalesTarget.year == year)
    umap = {u.id: u.name for u in db.query(User).all()}
    return [ser(t, user_name=umap.get(t.user_id, "全公司")) for t in qs.order_by(
        SalesTarget.year.desc(), SalesTarget.month).all()]


@router.post("/targets")
def add_target(data: dict = Body(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    return ser(create_obj(db, SalesTarget, data, user, "业绩目标"))


@router.put("/targets/{tid}")
def upd_target(tid: int, data: dict = Body(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = db.query(SalesTarget).filter(SalesTarget.id == tid).first()
    if not t:
        raise HTTPException(status_code=404, detail="目标不存在")
    return ser(update_obj(db, t, data, user, "业绩目标"))


@router.delete("/targets/{tid}")
def del_target(tid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    t = db.query(SalesTarget).filter(SalesTarget.id == tid).first()
    if not t:
        raise HTTPException(status_code=404, detail="目标不存在")
    return delete_obj(db, t, user, "业绩目标")


# ================================================================ 产品分析
@router.get("/analysis/product")
def analysis_product(period: str = "year", db: Session = Depends(get_db),
                     user=Depends(get_current_user)):
    s, e, _, _ = period_range(period)
    q = db.query(Product.id, Product.name, Product.category,
                 func.coalesce(func.sum(OrderItem.qty), 0),
                 func.coalesce(func.sum(OrderItem.amount), 0), Product.cost, Product.supply_price) \
        .join(OrderItem, OrderItem.product_id == Product.id) \
        .join(Order, Order.id == OrderItem.order_id).filter(Order.status != "已取消")
    q = in_range(q, Order.created_at, s, e).group_by(Product.id).all()
    items = []
    for pid, name, cat, qty, amount, cost, supply in q:
        profit = money((amount or 0) - (cost or 0) * (qty or 0))
        items.append({"id": pid, "name": name, "category": cat or "未分类", "qty": qty,
                      "amount": money(amount), "profit": profit,
                      "rate": round(profit / (amount or 1) * 100, 1)})
    items.sort(key=lambda x: -x["amount"])
    cats = {}
    for it in items:
        c = cats.setdefault(it["category"], {"amount": 0, "profit": 0})
        c["amount"] = money(c["amount"] + it["amount"])
        c["profit"] = money(c["profit"] + it["profit"])
    return {"items": items, "total_amount": money(sum(i["amount"] for i in items)),
            "total_profit": money(sum(i["profit"] for i in items)),
            "categories": [{"name": k, "amount": v["amount"], "profit": v["profit"]}
                           for k, v in sorted(cats.items(), key=lambda x: -x[1]["amount"])]}


@router.get("/analysis/options")
def analysis_options(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """看板下拉：年份列表等"""
    years = sorted({t.year for t in db.query(SalesTarget).all()} |
                   {o.created_at.year for o in db.query(Order).all() if o.created_at} or
                   {datetime.now().year}, reverse=True)
    return {"years": years}
