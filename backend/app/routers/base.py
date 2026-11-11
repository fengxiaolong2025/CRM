"""基础数据：产品、产品分类、竞品、区域、渠道、客户等级、数据字典"""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    Product, ProductCategory, Competitor, Region, ChannelType, CustomerLevel, DictItem,
    OrderItem, Order,
)
from app.schemas import (
    ProductCreate, RegionCreate, ChannelTypeCreate, CustomerLevelCreate, CompetitorCreate
)
from app.deps import get_current_user, require_roles
from app.utils import ser, ser_list, money
from app.crud import create_obj, update_obj, delete_obj

router = APIRouter(prefix="/api", tags=["base"])

ADMIN = ("super_admin", "sales_director", "qc")


def _cat_path(by_id: dict, cid) -> (str, int):
    """返回某分类的完整路径（名称用 ' / ' 连接）与层级深度"""
    names, level, guard = [], 0, 0
    cur = by_id.get(cid)
    while cur and guard < 10:
        names.insert(0, cur.name)
        cur = by_id.get(cur.parent_id)
        level += 1
        guard += 1
    return " / ".join(names), level


# ---------------------------------------------------------------- 产品
@router.get("/products")
def list_products(q: str = "", category_id: int = 0, status: int = -1,
                  db: Session = Depends(get_db), _=Depends(get_current_user)):
    qs = db.query(Product)
    if q:
        qs = qs.filter(Product.name.contains(q) | Product.code.contains(q))
    if category_id:
        qs = qs.filter(Product.category_id == category_id)
    if status in (0, 1):
        qs = qs.filter(Product.status == status)
    all_cats = db.query(ProductCategory).all()
    by_id = {c.id: c for c in all_cats}
    cats = {c.id: _cat_path(by_id, c.id)[0] for c in all_cats}
    # 销量统计（排除取消订单）
    stat = {}
    for pid, qty, amt in db.query(OrderItem.product_id, OrderItem.qty, OrderItem.amount) \
            .join(Order, Order.id == OrderItem.order_id) \
            .filter(Order.status != "已取消").all():
        s = stat.setdefault(pid, [0, 0.0])
        s[0] += qty or 0
        s[1] += amt or 0
    rows = []
    for p in qs.order_by(Product.id).all():
        qty, amount = stat.get(p.id, [0, 0.0])
        gross = money((p.supply_price or 0) - (p.cost or 0))
        rows.append(ser(p, category_name=cats.get(p.category_id) or p.category or "",
                        sold_qty=qty, sold_amount=money(amount), gross_profit=gross,
                        gross_rate=round(gross / (p.supply_price or 1) * 100, 1)))
    return rows


@router.post("/products")
def create_product(d: ProductCreate, db: Session = Depends(get_db), user=Depends(require_roles(*ADMIN))):
    if db.query(Product).filter(Product.code == d.code).first():
        raise HTTPException(status_code=400, detail="产品编码已存在")
    return ser(create_obj(db, Product, d.model_dump(), user, "产品信息"))


@router.put("/products/{pid}")
def update_product(pid: int, d: ProductCreate, db: Session = Depends(get_db), user=Depends(require_roles(*ADMIN))):
    p = db.query(Product).filter(Product.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="产品不存在")
    return ser(update_obj(db, p, d.model_dump(), user, "产品信息"))


@router.delete("/products/{pid}")
def delete_product(pid: int, db: Session = Depends(get_db), user=Depends(require_roles(*ADMIN))):
    p = db.query(Product).filter(Product.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="产品不存在")
    p.status = 0
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 产品分类
@router.get("/product-categories")
def list_categories(db: Session = Depends(get_db), _=Depends(get_current_user)):
    all_cats = db.query(ProductCategory).all()
    by_id = {c.id: c for c in all_cats}
    child_ids = {c.parent_id for c in all_cats if c.parent_id}
    rows = []
    for c in sorted(all_cats, key=lambda x: (x.sort or 0, x.id)):
        path, level = _cat_path(by_id, c.id)
        cnt = db.query(Product).filter(Product.category_id == c.id).count()
        rows.append(ser(c, level=level, path=path, product_count=cnt,
                        has_children=c.id in child_ids))
    return rows


@router.post("/product-categories")
def create_category(data: dict = Body(...), db: Session = Depends(get_db), user=Depends(require_roles(*ADMIN))):
    return ser(create_obj(db, ProductCategory, data, user, "产品分类"))


@router.post("/product-categories/row")
def create_category_row(data: dict = Body(...), db: Session = Depends(get_db),
                        user=Depends(require_roles(*ADMIN))):
    """按 Excel 三级格式新增一行分类：类目一 / 类目二 / 类目三（逐级 find-or-create）"""
    l1 = (data.get("level1") or "").strip()
    l2 = (data.get("level2") or "").strip()
    l3 = (data.get("level3") or "").strip()
    if not l1:
        raise HTTPException(status_code=400, detail="类目一不能为空")
    sort = data.get("sort") or 0
    note = (data.get("note") or "").strip()

    def foc(name, parent_id, is_leaf):
        exist = db.query(ProductCategory).filter(
            ProductCategory.name == name, ProductCategory.parent_id == parent_id).first()
        if exist:
            return exist
        return create_obj(db, ProductCategory,
                         {"name": name, "parent_id": parent_id, "sort": sort,
                          "note": note if is_leaf else ""}, user, "产品分类")

    n1 = foc(l1, None, not l2)
    leaf = n1
    if l2:
        n2 = foc(l2, n1.id, not l3)
        leaf = n2
        if l3:
            n3 = foc(l3, n2.id, True)
            leaf = n3
    by_id = {c.id: c for c in db.query(ProductCategory).all()}
    path, level = _cat_path(by_id, leaf.id)
    return ser(leaf, level=level, path=path)


@router.put("/product-categories/{cid}")
def update_category(cid: int, data: dict = Body(...), db: Session = Depends(get_db), user=Depends(require_roles(*ADMIN))):
    c = db.query(ProductCategory).filter(ProductCategory.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="分类不存在")
    return ser(update_obj(db, c, data, user, "产品分类"))


@router.delete("/product-categories/{cid}")
def delete_category(cid: int, db: Session = Depends(get_db), user=Depends(require_roles(*ADMIN))):
    c = db.query(ProductCategory).filter(ProductCategory.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="分类不存在")
    if db.query(ProductCategory).filter(ProductCategory.parent_id == cid).count():
        raise HTTPException(status_code=400, detail="该分类下存在子分类，请先删除子分类")
    if db.query(Product).filter(Product.category_id == cid).count():
        raise HTTPException(status_code=400, detail="分类下仍有产品，无法删除")
    return delete_obj(db, c, user, "产品分类")


# ---------------------------------------------------------------- 竞品
@router.get("/competitors")
def list_competitors(q: str = "", db: Session = Depends(get_db), _=Depends(get_current_user)):
    qs = db.query(Competitor)
    if q:
        qs = qs.filter(Competitor.brand.contains(q) | Competitor.product_name.contains(q))
    return ser_list(qs.order_by(Competitor.id).all())


@router.post("/competitors")
def create_competitor(d: CompetitorCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return ser(create_obj(db, Competitor, d.model_dump(), user, "竞品库"))


@router.put("/competitors/{cid}")
def update_competitor(cid: int, data: dict = Body(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = db.query(Competitor).filter(Competitor.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="竞品不存在")
    return ser(update_obj(db, c, data, user, "竞品库"))


@router.delete("/competitors/{cid}")
def delete_competitor(cid: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = db.query(Competitor).filter(Competitor.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="竞品不存在")
    return delete_obj(db, c, user, "竞品库")


# ---------------------------------------------------------------- 区域 / 渠道 / 等级
@router.get("/regions")
def list_regions(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return ser_list(db.query(Region).order_by(Region.id).all())


@router.post("/regions")
def create_region(d: RegionCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return ser(create_obj(db, Region, d.model_dump(), user, "区域"))


@router.delete("/regions/{rid}")
def delete_region(rid: int, db: Session = Depends(get_db), user=Depends(require_roles("super_admin"))):
    r = db.query(Region).filter(Region.id == rid).first()
    if not r:
        raise HTTPException(status_code=404, detail="区域不存在")
    return delete_obj(db, r, user, "区域")


@router.get("/channel-types")
def list_channels(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return ser_list(db.query(ChannelType).order_by(ChannelType.id).all())


@router.post("/channel-types")
def create_channel(d: ChannelTypeCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return ser(create_obj(db, ChannelType, d.model_dump(), user, "渠道类型"))


@router.delete("/channel-types/{cid}")
def delete_channel(cid: int, db: Session = Depends(get_db), user=Depends(require_roles("super_admin"))):
    c = db.query(ChannelType).filter(ChannelType.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="渠道不存在")
    return delete_obj(db, c, user, "渠道类型")


@router.get("/customer-levels")
def list_levels(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return ser_list(db.query(CustomerLevel).order_by(CustomerLevel.id).all())


@router.post("/customer-levels")
def create_level(d: CustomerLevelCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return ser(create_obj(db, CustomerLevel, d.model_dump(), user, "客户等级"))


# ---------------------------------------------------------------- 数据字典
DICT_TYPES = {
    "lead_source": "线索来源",
    "customer_tag": "客户标签",
    "complaint_type": "客诉类型",
    "lost_reason": "丢单原因",
    "pay_method": "回款方式",
    "visit_type": "跟进方式",
}


@router.get("/dicts")
def list_dicts(dtype: str = "", db: Session = Depends(get_db), _=Depends(get_current_user)):
    qs = db.query(DictItem)
    if dtype:
        qs = qs.filter(DictItem.dtype == dtype)
    return ser_list(qs.filter(DictItem.active == 1).order_by(DictItem.dtype, DictItem.sort).all())


@router.get("/dicts/all")
def all_dicts(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """前端下拉统一取值：{dtype: [name...]}"""
    out = {k: [] for k in DICT_TYPES}
    for d in db.query(DictItem).filter(DictItem.active == 1).order_by(DictItem.sort).all():
        out.setdefault(d.dtype, []).append(d.name)
    return out


@router.get("/dicts/manage")
def manage_dicts(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = []
    for d in db.query(DictItem).order_by(DictItem.dtype, DictItem.sort, DictItem.id).all():
        rows.append(ser(d, type_label=DICT_TYPES.get(d.dtype, d.dtype)))
    return rows


@router.post("/dicts")
def create_dict(data: dict = Body(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    return ser(create_obj(db, DictItem, data, user, "数据字典"))


@router.put("/dicts/{did}")
def update_dict(did: int, data: dict = Body(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    d = db.query(DictItem).filter(DictItem.id == did).first()
    if not d:
        raise HTTPException(status_code=404, detail="字典项不存在")
    return ser(update_obj(db, d, data, user, "数据字典"))


@router.delete("/dicts/{did}")
def delete_dict(did: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    d = db.query(DictItem).filter(DictItem.id == did).first()
    if not d:
        raise HTTPException(status_code=404, detail="字典项不存在")
    return delete_obj(db, d, user, "数据字典")
