"""报表与数据仪表盘（老板驾驶舱）"""
from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from app.database import get_db
from app.models import (
    Customer, Order, Payment, SampleApplication, Complaint, User, Region,
    ChannelType, Lead, Visit, Opportunity
)
from app.deps import get_current_user, is_manager_or_above

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user=Depends(get_current_user)):
    now = datetime.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 业绩（本组/全公司）
    order_qs = db.query(Order)
    pay_qs = db.query(Payment)
    if not is_manager_or_above(user.role) and user.role != "finance":
        my_ids = [o.id for o in order_qs.filter(Order.owner_id == user.id).all()]
        order_qs = db.query(Order).filter(Order.id.in_(my_ids))

    order_total = float(db.query(func.coalesce(func.sum(Order.total_amount), 0)).select_from(Order).scalar() or 0)
    paid_total = float(db.query(func.coalesce(func.sum(Payment.amount), 0)).scalar() or 0)
    month_order = float(db.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(Order.created_at >= month_start).scalar() or 0)

    # 客户分析
    total_cust = db.query(Customer).filter(Customer.status == 1).count()
    new_cust = db.query(Customer).filter(Customer.created_at >= month_start, Customer.status == 1).count()
    # 沉睡：90天无拜访
    sleep_cut = now - timedelta(days=90)
    active = db.query(Visit.customer_id).filter(Visit.created_at >= sleep_cut).distinct().count()
    sleeping = max(total_cust - active, 0)

    # 客诉分类统计
    complaint_types = db.query(Complaint.ctype, func.count(Complaint.id)).group_by(Complaint.ctype).all()
    # 渠道销量占比
    channel_sales = db.query(ChannelType.name, func.coalesce(func.sum(Order.total_amount), 0)) \
        .join(Customer, Customer.channel_type_id == ChannelType.id) \
        .join(Order, Order.customer_id == Customer.id) \
        .group_by(ChannelType.name).all()

    # 销售漏斗
    stages = ["初步接触", "样品测试", "报价谈判", "合同确认", "成交"]
    funnel = []
    for s in stages:
        cnt = db.query(Opportunity).filter(Opportunity.stage == s, Opportunity.is_lost == False).count()  # noqa
        amt = float(db.query(func.coalesce(func.sum(Opportunity.amount), 0)).filter(
            Opportunity.stage == s, Opportunity.is_lost == False).scalar() or 0)  # noqa
        funnel.append({"stage": s, "count": cnt, "amount": amt})

    return {
        "order_total": round(order_total, 2),
        "paid_total": round(paid_total, 2),
        "receivable": round(order_total - paid_total, 2),
        "month_order": round(month_order, 2),
        "total_customers": total_cust,
        "new_customers": new_cust,
        "active_customers": active,
        "sleeping_customers": sleeping,
        "sample_count": db.query(SampleApplication).count(),
        "complaint_count": db.query(Complaint).count(),
        "complaint_types": [{"type": t, "count": c} for t, c in complaint_types],
        "channel_sales": [{"channel": c, "amount": float(a)} for c, a in channel_sales],
        "funnel": funnel,
        "month_orders": _monthly_orders(db),
    }


def _monthly_orders(db):
    rows = db.query(func.strftime("%Y-%m", Order.created_at),
                    func.coalesce(func.sum(Order.total_amount), 0)) \
        .group_by(func.strftime("%Y-%m", Order.created_at)).all()
    return [{"month": m, "amount": float(a)} for m, a in rows]


@router.get("/export/customers")
def export_customers(db: Session = Depends(get_db), user=Depends(get_current_user)):
    from openpyxl import Workbook
    from io import BytesIO
    wb = Workbook(); ws = wb.active; ws.title = "客户"
    headers = ["ID", "客户名称", "统一信用代码", "客户类型", "状态", "负责人", "账期", "授信额度", "月消耗量"]
    ws.append(headers)
    for c in db.query(Customer).filter(Customer.status == 1).all():
        owner = db.query(User).filter(User.id == c.owner_id).first()
        ws.append([c.id, c.name, c.credit_code, c.customer_type, c.status,
                   owner.name if owner else "", c.payment_term, c.credit_limit, c.monthly_consumption])
    buf = BytesIO(); wb.save(buf); buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": "attachment; filename=customers.xlsx"})


@router.get("/export/orders")
def export_orders(db: Session = Depends(get_db), user=Depends(get_current_user)):
    from openpyxl import Workbook
    from io import BytesIO
    wb = Workbook(); ws = wb.active; ws.title = "订单"
    ws.append(["订单号", "客户", "状态", "账期", "金额", "创建时间"])
    for o in db.query(Order).all():
        cust = db.query(Customer).filter(Customer.id == o.customer_id).first()
        ws.append([o.order_no, cust.name if cust else "", o.status, o.account_term,
                   float(o.total_amount), str(o.created_at)[:10]])
    buf = BytesIO(); wb.save(buf); buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": "attachment; filename=orders.xlsx"})
