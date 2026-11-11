"""初始化种子数据：组织架构、基础数据、字典、业绩目标"""
from datetime import datetime
from sqlalchemy.orm import Session
from app.database import engine, Base
from app.models import (
    User, Region, ChannelType, CustomerLevel, Product, ProductCategory, Competitor,
    DictItem, SalesTarget,
)
from app.security import hash_password

DEMO_PASSWORD = "123456"


def seed(db: Session):
    # ------------------------------------------------ 区域
    if not db.query(Region).first():
        tree = {
            "四川省": ["成都市", "绵阳市", "德阳市"],
            "重庆市": ["渝中区", "江北区"],
            "广东省": ["广州市", "深圳市", "佛山市"],
            "湖南省": ["长沙市", "株洲市"],
            "陕西省": ["西安市", "咸阳市"],
            "河南省": ["郑州市", "洛阳市"],
        }
        for p, cities in tree.items():
            pr = Region(name=p, level=1)
            db.add(pr); db.flush()
            for c in cities:
                db.add(Region(name=c, parent_id=pr.id, level=2))
        db.commit()

    # ------------------------------------------------ 渠道
    if not db.query(ChannelType).first():
        for n in ["一级经销商", "二级分销", "连锁火锅总部", "单店餐饮", "商超", "企业团购", "电商"]:
            db.add(ChannelType(name=n))
        db.commit()

    # ------------------------------------------------ 客户等级
    if not db.query(CustomerLevel).first():
        for code, name, desc in [
            ("A", "A级 战略客户", "连锁总部/年采购 100 万以上，专属政策+账期"),
            ("B", "B级 重点客户", "区域经销商/中型连锁，季度返利"),
            ("C", "C级 普通客户", "单店餐饮/小分销，现结为主"),
            ("D", "D级 观察客户", "新开发/采购不稳定，控制授信"),
        ]:
            db.add(CustomerLevel(code=code, name=name, policy_desc=desc))
        db.commit()

    # ------------------------------------------------ 产品分类
    cats = {}
    if not db.query(ProductCategory).first():
        for i, n in enumerate(["麻酱系列", "油碟系列", "调味酱系列", "复合蘸料", "餐饮定制"]):
            c = ProductCategory(name=n, sort=i)
            db.add(c); db.flush()
            cats[n] = c.id
        db.commit()
    else:
        cats = {c.name: c.id for c in db.query(ProductCategory).all()}

    # ------------------------------------------------ 产品
    product_rows = [
        ("MJ001", "经典麻酱", "麻酱系列", "1kg/瓶", "瓶", 12, 18, 25, 8, 180),
        ("MJ002", "香浓芝麻酱", "麻酱系列", "2.5kg/桶", "桶", 28, 42, 58, 19, 180),
        ("MJ003", "花生麻酱", "麻酱系列", "1kg/瓶", "瓶", 11, 16, 23, 7.2, 180),
        ("XY002", "小磨香油碟", "油碟系列", "200ml/瓶", "瓶", 6, 9, 15, 4, 365),
        ("XY003", "蒜香香油碟", "油碟系列", "500ml/瓶", "瓶", 13, 19, 28, 8.6, 365),
        ("SN003", "蒜泥酱", "调味酱系列", "500g/袋", "袋", 5, 8, 12, 3.5, 240),
        ("HY004", "蚝油蘸料", "调味酱系列", "480g/瓶", "瓶", 4, 7, 11, 3, 365),
        ("ZJ005", "辣椒油碟", "油碟系列", "300ml/瓶", "瓶", 5, 8, 13, 3.5, 365),
        ("FH006", "火锅复合蘸料（麻辣）", "复合蘸料", "2kg/袋", "袋", 22, 32, 45, 15, 180),
        ("FH007", "火锅复合蘸料（清香）", "复合蘸料", "2kg/袋", "袋", 21, 31, 44, 14.5, 180),
        ("DZ008", "连锁定制蘸料 A", "餐饮定制", "5kg/桶", "桶", 55, 78, 108, 40, 120),
        ("DZ009", "连锁定制蘸料 B", "餐饮定制", "5kg/桶", "桶", 52, 75, 105, 38, 120),
    ]
    existing_codes = {p.code for p in db.query(Product).all()}
    for code, name, cat, spec, unit, fp, sp, rp, cost, life in product_rows:
        if code in existing_codes:
            continue
        db.add(Product(code=code, name=name, category=cat, category_id=cats.get(cat),
                       spec=spec, unit=unit, factory_price=fp, supply_price=sp,
                       retail_price=rp, cost=cost, shelf_life=life, status=1,
                       safety_stock=500))
    db.commit()

    # ------------------------------------------------ 竞品
    if not db.query(Competitor).first():
        for brand, pname, spec, price, ch, strength, weakness in [
            ("老干妈", "风味豆豉", "280g", 9.5, "商超", "品牌认知度高、渠道广", "非火锅专用、蘸料场景弱"),
            ("六必居", "芝麻酱", "350g", 12.8, "商超/电商", "老字号、纯芝麻", "价格偏高、B端服务弱"),
            ("李锦记", "蚝油", "510g", 15.9, "商超", "终端陈列强", "蘸料组合不完整"),
            ("川南", "火锅蘸料", "150g", 6.5, "流通", "低价、覆盖小店", "品质不稳定、无定制"),
        ]:
            db.add(Competitor(brand=brand, product_name=pname, spec=spec, market_price=price,
                              channel=ch, strength=strength, weakness=weakness))
        db.commit()

    # ------------------------------------------------ 字典
    if not db.query(DictItem).first():
        dicts = {
            "lead_source": ["市场拓客", "展会", "转介绍", "抖音/短视频", "招商加盟", "官网咨询", "老客户复购"],
            "customer_tag": ["价格敏感", "品质优先", "连锁总部", "账期客户", "潜力大", "待激活", "竞品在用"],
            "complaint_type": ["口味问题", "变质", "胀袋", "漏袋", "配送破损", "临期", "数量短缺", "包装不符"],
            "lost_reason": ["竞品价格低", "口味不满意", "客户换供应商", "预算不足", "决策链过长", "区域冲突"],
            "pay_method": ["银行转账", "微信", "支付宝", "现金", "承兑汇票"],
            "visit_type": ["电话", "微信", "上门", "邮件", "其他"],
        }
        for dtype, names in dicts.items():
            for i, n in enumerate(names):
                db.add(DictItem(dtype=dtype, name=n, sort=i))
        db.commit()

    # ------------------------------------------------ 用户
    if not db.query(User).first():
        admin = User(username="admin", password_hash=hash_password(DEMO_PASSWORD),
                     name="系统管理员", role="super_admin", job_no="A001")
        db.add(admin); db.flush()
        director = User(username="director", password_hash=hash_password(DEMO_PASSWORD),
                        name="销售总监", role="sales_director", region_id=1, job_no="S001")
        db.add(director); db.flush()
        manager = User(username="manager", password_hash=hash_password(DEMO_PASSWORD),
                       name="区域主管", role="regional_manager", region_id=2,
                       parent_id=director.id, job_no="S002")
        db.add(manager); db.flush()
        rep = User(username="rep", password_hash=hash_password(DEMO_PASSWORD),
                   name="业务员小王", role="salesrep", region_id=2, parent_id=manager.id, job_no="S003")
        db.add(rep)
        db.add(User(username="rep2", password_hash=hash_password(DEMO_PASSWORD),
                    name="业务员小李", role="salesrep", region_id=4, parent_id=manager.id, job_no="S004"))
        db.add(User(username="finance", password_hash=hash_password(DEMO_PASSWORD),
                    name="财务小李", role="finance", region_id=1, job_no="F001"))
        db.add(User(username="service", password_hash=hash_password(DEMO_PASSWORD),
                    name="售后小张", role="after_sales", region_id=1, job_no="K001"))
        db.add(User(username="qc", password_hash=hash_password(DEMO_PASSWORD),
                    name="品控小陈", role="qc", region_id=1, job_no="Q001"))
        db.commit()
        print("种子数据已初始化（演示账号密码均为 123456）")
    else:
        print("数据已存在，跳过种子")

    # ------------------------------------------------ 业绩目标（当年）
    year = datetime.now().year
    if not db.query(SalesTarget).filter(SalesTarget.year == year).first():
        db.add(SalesTarget(year=year, month=0, target_amount=16000000,
                           target_new_customers=120, target_orders=600, note="公司年度目标"))
        for m in range(1, 13):
            # 旺季（9-12月）权重更高
            factor = 1.25 if m >= 9 else (1.1 if m >= 6 else 0.85)
            db.add(SalesTarget(year=year, month=m,
                               target_amount=round(16000000 / 12 * factor, 2),
                               target_new_customers=int(120 / 12 * factor),
                               target_orders=int(600 / 12 * factor)))
        director = db.query(User).filter(User.role == "sales_director").first()
        manager = db.query(User).filter(User.role == "regional_manager").first()
        if director:
            db.add(SalesTarget(user_id=director.id, year=year, month=0, target_amount=16000000))
        if manager:
            db.add(SalesTarget(user_id=manager.id, year=year, month=0, target_amount=6000000))
        db.commit()

    # 兜底：给老产品补品类 ID
    cmap = {c.name: c.id for c in db.query(ProductCategory).all()}
    for p in db.query(Product).filter(Product.category_id.is_(None)).all():
        if p.category in cmap:
            p.category_id = cmap[p.category]
    db.commit()


if __name__ == "__main__":
    from app.database import SessionLocal
    Base.metadata.create_all(bind=engine)
    from app.migrate import ensure_columns
    ensure_columns()
    db = SessionLocal()
    seed(db)
    db.close()
