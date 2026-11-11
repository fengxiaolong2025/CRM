"""CRM 全部数据模型（火锅蘸料企业 B2B）V2"""
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Date, Text,
    ForeignKey, JSON, Enum as SAEnum,
)
from sqlalchemy.orm import relationship
from app.database import Base

# 角色枚举
ROLES = (
    "super_admin",      # 超级管理员
    "sales_director",   # 销售总监
    "regional_manager", # 区域销售主管
    "salesrep",         # 业务员
    "finance",          # 财务
    "after_sales",      # 售后客服
    "qc",               # 产品/品控
)

# 商机阶段（顺序即漏斗顺序）
OPP_STAGES = ("初步接触", "需求确认", "样品测试", "报价谈判", "合同确认", "成交")
LEAD_STATUS = ("待跟进", "跟进中", "有效", "无效")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    name = Column(String(50), nullable=False)
    role = Column(SAEnum(*ROLES), default="salesrep", nullable=False)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=True)
    parent_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 直属主管
    phone = Column(String(20))
    wechat = Column(String(50))
    email = Column(String(80))
    job_no = Column(String(30))          # 工号
    status = Column(Integer, default=1)  # 1启用 0禁用
    last_login_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)

    children = relationship("User", backref="parent", remote_side=[id])


class Region(Base):
    __tablename__ = "regions"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    parent_id = Column(Integer, ForeignKey("regions.id"), nullable=True)
    level = Column(Integer, default=1)  # 1省 2市 3区


class ChannelType(Base):
    __tablename__ = "channel_types"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)


class CustomerLevel(Base):
    __tablename__ = "customer_levels"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(10), nullable=False)  # A/B/C
    name = Column(String(50), nullable=False)
    policy_desc = Column(Text)


class ProductCategory(Base):
    """产品分类（支持二级）"""
    __tablename__ = "product_categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    parent_id = Column(Integer, ForeignKey("product_categories.id"), nullable=True)
    sort = Column(Integer, default=0)
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True)
    name = Column(String(100), nullable=False)
    category = Column(String(50))              # 冗余的品类名称（兼容旧数据）
    category_id = Column(Integer, ForeignKey("product_categories.id"), nullable=True)
    spec = Column(String(50))
    unit = Column(String(20))
    barcode = Column(String(50))
    factory_price = Column(Float, default=0)
    supply_price = Column(Float, default=0)     # 建议供货价
    retail_price = Column(Float, default=0)     # 建议零售价
    cost = Column(Float, default=0)
    safety_stock = Column(Float, default=0)
    shelf_life = Column(Integer)                # 保质期(天)
    status = Column(Integer, default=1)         # 1在售 0停售
    image = Column(String(255))
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class Competitor(Base):
    __tablename__ = "competitors"
    id = Column(Integer, primary_key=True, index=True)
    brand = Column(String(100), nullable=False)
    product_name = Column(String(100))
    spec = Column(String(50))
    market_price = Column(Float)
    channel = Column(String(50))     # 主销渠道
    strength = Column(Text)          # 竞品优势
    weakness = Column(Text)          # 竞品短板
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class DictItem(Base):
    """数据字典：线索来源/客户标签/客诉类型/丢单原因等可配置项"""
    __tablename__ = "dict_items"
    id = Column(Integer, primary_key=True, index=True)
    dtype = Column(String(50), nullable=False, index=True)  # lead_source / customer_tag / complaint_type / lost_reason
    name = Column(String(100), nullable=False)
    sort = Column(Integer, default=0)
    active = Column(Integer, default=1)


class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50))
    customer_name = Column(String(100), nullable=False, index=True)
    contact = Column(String(50))
    phone = Column(String(20))
    wechat = Column(String(50))
    address = Column(String(200))
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=True)
    intend_channel = Column(String(50))
    intend_product = Column(String(100))
    score = Column(Integer, default=0)          # 线索评分
    status = Column(String(20), default="待跟进")  # 待跟进/跟进中/有效/无效
    is_pool = Column(Boolean, default=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    last_follow_at = Column(DateTime)
    next_follow_at = Column(DateTime)
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    credit_code = Column(String(50))
    address = Column(String(200))
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=True)
    channel_type_id = Column(Integer, ForeignKey("channel_types.id"), nullable=True)
    level_id = Column(Integer, ForeignKey("customer_levels.id"), nullable=True)
    customer_type = Column(String(20), default="dealer")  # dealer/restaurant/supermarket/group
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    phone = Column(String(30))
    wechat = Column(String(50))
    source = Column(String(50))
    status = Column(Integer, default=1)          # 1正常 0逻辑删除
    is_pool = Column(Boolean, default=False)     # 客户公海
    pool_at = Column(DateTime)
    # 特色字段（酱料行业）
    store_count = Column(Integer)                # 门店/网点数量
    table_count = Column(Integer)                # 门店桌台数量
    monthly_consumption = Column(Float)          # 月预估蘸料消耗量(kg)
    current_competitor = Column(String(100))
    delivery_method = Column(String(50))
    delivery_cycle = Column(String(50))
    payment_term = Column(String(20))
    credit_limit = Column(Float)
    last_follow_at = Column(DateTime)
    next_follow_at = Column(DateTime)
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class Contact(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    name = Column(String(50), nullable=False)
    phone = Column(String(20))
    wechat = Column(String(50))
    title = Column(String(50))     # 采购/老板/后厨负责人
    is_primary = Column(Boolean, default=False)
    birthday = Column(Date)
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class CustomerTag(Base):
    __tablename__ = "customer_tags"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    tag = Column(String(50), nullable=False)


class Contract(Base):
    __tablename__ = "contracts"
    id = Column(Integer, primary_key=True, index=True)
    contract_no = Column(String(50))
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    title = Column(String(100), nullable=False)
    amount = Column(Float, default=0)
    status = Column(String(20), default="执行中")  # 待签署/执行中/已到期/已终止
    sign_date = Column(Date)
    file_path = Column(String(255))
    start_date = Column(Date)
    end_date = Column(Date)
    reminder_date = Column(Date)
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class FollowUp(Base):
    """跟进记录（统一：可挂在客户/线索/商机上）"""
    __tablename__ = "followups"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ftype = Column(String(20), default="电话")   # 电话/微信/上门/邮件/其他
    content = Column(Text)
    result = Column(String(100))
    next_at = Column(DateTime)
    attachments = Column(JSON)
    created_at = Column(DateTime, default=datetime.now)


class Visit(Base):
    """拜访记录（保留，与跟进记录互补）"""
    __tablename__ = "visits"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    visit_type = Column(String(20))
    content = Column(Text)
    pain_point = Column(Text)
    need = Column(Text)
    next_visit_at = Column(DateTime)
    market_info = Column(Text)
    attachments = Column(JSON)
    created_at = Column(DateTime, default=datetime.now)


class SampleApplication(Base):
    __tablename__ = "sample_applications"
    id = Column(Integer, primary_key=True, index=True)
    apply_no = Column(String(50))
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    purpose = Column(String(50))
    freight_payer = Column(String(20))
    status = Column(String(20), default="待审批")   # 待审批/已通过/已驳回/已寄出/已签收
    total_cost = Column(Float, default=0)
    approver_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime)
    express_no = Column(String(50))
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class SampleItem(Base):
    __tablename__ = "sample_items"
    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("sample_applications.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    qty = Column(Integer, default=1)


class SampleRecord(Base):
    __tablename__ = "sample_records"
    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("sample_applications.id"), nullable=False)
    express_no = Column(String(50))
    received = Column(Boolean, default=False)
    feedback = Column(String(20))
    feedback_reason = Column(String(50))


class Opportunity(Base):
    __tablename__ = "opportunities"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    amount = Column(Float, default=0)
    intend_product = Column(String(200))
    source = Column(String(50))
    expected_close = Column(Date)
    win_prob = Column(Integer, default=0)
    stage = Column(String(20), default="初步接触")
    is_lost = Column(Boolean, default=False)
    lost_reason = Column(String(100))
    next_action = Column(String(200))
    last_follow_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)


class Quotation(Base):
    __tablename__ = "quotations"
    id = Column(Integer, primary_key=True, index=True)
    quote_no = Column(String(50))
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    version = Column(Integer, default=1)
    status = Column(String(20), default="草稿")  # 草稿/待审批/已通过/已驳回/已失效
    special_price = Column(Boolean, default=False)
    discount_approved = Column(Boolean, default=False)
    valid_until = Column(Date)
    total_amount = Column(Float, default=0)
    remark = Column(Text)
    pdf_path = Column(String(255))
    created_at = Column(DateTime, default=datetime.now)


class QuotationItem(Base):
    __tablename__ = "quotation_items"
    id = Column(Integer, primary_key=True, index=True)
    quotation_id = Column(Integer, ForeignKey("quotations.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    qty = Column(Integer, default=1)
    unit_price = Column(Float, default=0)
    amount = Column(Float, default=0)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String(50), unique=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    quotation_id = Column(Integer, ForeignKey("quotations.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(20), default="待确认")  # 待确认/待发货/已发货/部分发货/已完成/已取消
    account_term = Column(String(20))
    delivery_no = Column(String(50))
    receiver = Column(String(50))
    receiver_phone = Column(String(30))
    address = Column(String(200))
    ship_date = Column(Date)
    remark = Column(Text)
    total_amount = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.now)


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    qty = Column(Integer, default=1)
    unit_price = Column(Float, default=0)
    amount = Column(Float, default=0)


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, index=True)
    pay_no = Column(String(50))
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, default=0)
    pay_date = Column(Date)
    pay_method = Column(String(20))
    status = Column(String(20), default="已确认")  # 待确认/已确认
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    invoice_no = Column(String(50))
    invoice_type = Column(String(20), default="增值税专用发票")
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    amount = Column(Float, default=0)
    status = Column(String(20), default="已开票")  # 待开票/已开票/已作废
    invoice_date = Column(Date)
    title = Column(String(100))
    tax_no = Column(String(50))
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class Complaint(Base):
    __tablename__ = "complaints"
    id = Column(Integer, primary_key=True, index=True)
    complaint_no = Column(String(50))
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ctype = Column(String(50))
    urgency = Column(String(10), default="中")  # 高/中/低
    batch = Column(String(50))
    description = Column(Text)
    photos = Column(JSON)
    status = Column(String(20), default="新建")  # 新建/处理中/待回访/已结案
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    solution = Column(Text)
    result = Column(Text)
    deadline = Column(Date)
    closed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)


class RebatePolicy(Base):
    __tablename__ = "rebate_policies"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    period = Column(String(20))
    threshold_ton = Column(Float)
    rebate_rate = Column(Float)
    active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now)


class RebateRecord(Base):
    __tablename__ = "rebate_records"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    policy_id = Column(Integer, ForeignKey("rebate_policies.id"), nullable=True)
    period = Column(String(20))
    amount = Column(Float, default=0)
    status = Column(String(20), default="待核算")  # 待核算/待审批/已批准/已兑现
    redeem_type = Column(String(20))
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class CrossSale(Base):
    __tablename__ = "cross_sales"
    id = Column(Integer, primary_key=True, index=True)
    product_batch = Column(String(50))
    dealer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    found_location = Column(String(200))
    photos = Column(JSON)
    handle_result = Column(Text)
    status = Column(String(20), default="待处理")  # 待处理/处理中/已处理
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.now)


class SalesTarget(Base):
    """业绩目标：user_id 为空表示公司/部门目标"""
    __tablename__ = "sales_targets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, default=0)  # 0=全年
    target_amount = Column(Float, default=0)
    target_new_customers = Column(Integer, default=0)
    target_orders = Column(Integer, default=0)
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # 接收人
    mtype = Column(String(50))  # approval/contract/overdue/visit/system
    title = Column(String(100), nullable=False)
    content = Column(Text)
    related_id = Column(Integer)
    link = Column(String(100))
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user_name = Column(String(50))
    action = Column(String(50))  # 新增/修改/删除/登录/审批
    module = Column(String(50))
    table_name = Column(String(50))
    record_id = Column(Integer)
    detail = Column(Text)
    ip = Column(String(50))
    created_at = Column(DateTime, default=datetime.now, index=True)
