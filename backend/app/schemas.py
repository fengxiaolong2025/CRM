"""Pydantic 请求/响应模型"""
from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserCreate(BaseModel):
    username: str
    password: str
    name: str
    role: str = "salesrep"
    region_id: Optional[int] = None
    parent_id: Optional[int] = None
    phone: Optional[str] = None
    wechat: Optional[str] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    name: str
    role: str
    region_id: Optional[int] = None
    parent_id: Optional[int] = None
    phone: Optional[str] = None
    wechat: Optional[str] = None
    status: int


class SimpleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


# 基础数据
class RegionCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None
    level: int = 1


class ChannelTypeCreate(BaseModel):
    name: str


class CustomerLevelCreate(BaseModel):
    code: str
    name: str
    policy_desc: Optional[str] = None


class ProductCreate(BaseModel):
    code: str
    name: str
    category: Optional[str] = None
    spec: Optional[str] = None
    unit: Optional[str] = None
    factory_price: float = 0
    supply_price: float = 0
    retail_price: float = 0
    cost: float = 0
    image: Optional[str] = None
    description: Optional[str] = None


class CompetitorCreate(BaseModel):
    brand: str
    product_name: Optional[str] = None
    spec: Optional[str] = None
    market_price: Optional[float] = None
    note: Optional[str] = None


# 线索
class LeadCreate(BaseModel):
    source: Optional[str] = None
    customer_name: str
    contact: Optional[str] = None
    phone: Optional[str] = None
    wechat: Optional[str] = None
    address: Optional[str] = None
    region_id: Optional[int] = None
    intend_channel: Optional[str] = None
    intend_product: Optional[str] = None
    score: Optional[int] = 0
    note: Optional[str] = None
    next_follow_at: Optional[str] = None


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: Optional[str] = None
    customer_name: str
    contact: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    intend_channel: Optional[str] = None
    intend_product: Optional[str] = None
    status: str
    is_pool: bool
    owner_id: Optional[int] = None
    note: Optional[str] = None
    created_at: Optional[datetime] = None


# 客户
class ContactCreate(BaseModel):
    customer_id: Optional[int] = None
    name: str
    phone: Optional[str] = None
    wechat: Optional[str] = None
    title: Optional[str] = None
    is_primary: Optional[bool] = False


class ContractCreate(BaseModel):
    title: str
    contract_no: Optional[str] = None
    amount: float = 0
    status: Optional[str] = "执行中"
    sign_date: Optional[str] = None
    file_path: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    reminder_date: Optional[str] = None
    remark: Optional[str] = None


class CustomerCreate(BaseModel):
    name: str
    credit_code: Optional[str] = None
    address: Optional[str] = None
    region_id: Optional[int] = None
    channel_type_id: Optional[int] = None
    level_id: Optional[int] = None
    customer_type: str = "dealer"
    owner_id: Optional[int] = None
    phone: Optional[str] = None
    wechat: Optional[str] = None
    source: Optional[str] = None
    store_count: Optional[int] = None
    table_count: Optional[int] = None
    monthly_consumption: Optional[float] = None
    current_competitor: Optional[str] = None
    delivery_method: Optional[str] = None
    delivery_cycle: Optional[str] = None
    payment_term: Optional[str] = None
    credit_limit: Optional[float] = None
    remark: Optional[str] = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    credit_code: Optional[str] = None
    address: Optional[str] = None
    region_id: Optional[int] = None
    channel_type_id: Optional[int] = None
    level_id: Optional[int] = None
    customer_type: str
    owner_id: Optional[int] = None
    status: int
    table_count: Optional[int] = None
    monthly_consumption: Optional[float] = None
    current_competitor: Optional[str] = None
    delivery_method: Optional[str] = None
    delivery_cycle: Optional[str] = None
    payment_term: Optional[str] = None
    credit_limit: Optional[float] = None
    created_at: Optional[datetime] = None


# 拜访
class VisitCreate(BaseModel):
    customer_id: int
    visit_type: Optional[str] = None
    content: Optional[str] = None
    pain_point: Optional[str] = None
    need: Optional[str] = None
    next_visit_at: Optional[str] = None
    market_info: Optional[str] = None
    attachments: Optional[list] = None


# 样品
class SampleItemIn(BaseModel):
    product_id: int
    qty: int = 1


class SampleApplicationCreate(BaseModel):
    customer_id: int
    purpose: Optional[str] = None
    freight_payer: Optional[str] = None
    items: List[SampleItemIn] = []


class SampleRecordCreate(BaseModel):
    express_no: Optional[str] = None
    received: bool = False
    feedback: Optional[str] = None
    feedback_reason: Optional[str] = None


# 商机
class OpportunityCreate(BaseModel):
    customer_id: int
    name: str
    amount: float = 0
    intend_product: Optional[str] = None
    expected_close: Optional[str] = None
    win_prob: int = 0
    stage: str = "初步接触"
    lost_reason: Optional[str] = None


# 报价
class QuotationItemIn(BaseModel):
    product_id: int
    qty: int = 1
    unit_price: float = 0


class QuotationCreate(BaseModel):
    customer_id: int
    opportunity_id: Optional[int] = None
    items: List[QuotationItemIn] = []


# 订单
class OrderItemIn(BaseModel):
    product_id: int
    qty: int = 1
    unit_price: float = 0


class OrderCreate(BaseModel):
    customer_id: int
    quotation_id: Optional[int] = None
    account_term: Optional[str] = None
    ship_date: Optional[str] = None
    receiver: Optional[str] = None
    receiver_phone: Optional[str] = None
    address: Optional[str] = None
    remark: Optional[str] = None
    items: List[OrderItemIn] = []


# 回款
class PaymentCreate(BaseModel):
    order_id: int
    customer_id: int
    amount: float = 0
    pay_date: Optional[str] = None
    pay_method: Optional[str] = None


class InvoiceCreate(BaseModel):
    customer_id: int
    order_id: Optional[int] = None
    invoice_no: Optional[str] = None
    amount: float = 0


# 客诉
class ComplaintCreate(BaseModel):
    customer_id: int
    ctype: str
    batch: Optional[str] = None
    description: Optional[str] = None
    photos: Optional[list] = None
    solution: Optional[str] = None
    result: Optional[str] = None


# 返利
class RebatePolicyCreate(BaseModel):
    name: str
    period: Optional[str] = None
    threshold_ton: float = 0
    rebate_rate: float = 0


class RebateRecordCreate(BaseModel):
    customer_id: int
    policy_id: Optional[int] = None
    amount: float = 0
    redeem_type: Optional[str] = None


# 窜货
class CrossSaleCreate(BaseModel):
    product_batch: Optional[str] = None
    dealer_id: int
    found_location: Optional[str] = None
    photos: Optional[list] = None
    handle_result: Optional[str] = None


# 消息
class MessageCreate(BaseModel):
    user_id: int
    mtype: str
    title: str
    content: Optional[str] = None
    related_id: Optional[int] = None
