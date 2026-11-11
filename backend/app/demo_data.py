"""演示数据（可选）：用于查看工作台/看板效果
用法：
    python -m app.demo_data          # 无客户时生成
    python -m app.demo_data --clear  # 清空全部业务数据（保留用户/产品/字典）
"""
import random
import sys
from datetime import datetime, date, timedelta
from app.database import SessionLocal, engine, Base
from app.models import (
    Customer, Contact, CustomerTag, Lead, Opportunity, Order, OrderItem, Payment,
    Invoice, Complaint, Contract, SampleApplication, SampleItem, FollowUp,
    RebatePolicy, RebateRecord, CrossSale, User, Product, CustomerLevel,
    ChannelType, Region, SalesTarget, OPP_STAGES,
)

random.seed(20261018)

CUSTOMERS = [
    ("蜀九香火锅（成都总店）", "restaurant", 1, "连锁火锅总部", 5, 240),
    ("小龙坎老火锅·春熙路店", "restaurant", 1, "单店餐饮", 2, 120),
    ("大龙燚火锅（四川区域）", "restaurant", 1, "连锁火锅总部", 6, 300),
    ("蜀大侠火锅·天府三街", "restaurant", 1, "单店餐饮", 1, 80),
    ("川西坝子火锅（成都）", "restaurant", 1, "单店餐饮", 1, 90),
    ("谭鸭血·成都万象城店", "restaurant", 1, "单店餐饮", 1, 70),
    ("牛华八婆麻辣烫（连锁）", "restaurant", 1, "连锁火锅总部", 3, 110),
    ("巴蜀大将火锅·绵阳店", "restaurant", 1, "单店餐饮", 1, 60),
    ("重庆德庄火锅（渝中）", "restaurant", 2, "连锁火锅总部", 4, 210),
    ("刘一手火锅·江北旗舰", "restaurant", 2, "单店餐饮", 1, 85),
    ("朝天门火锅（重庆）", "restaurant", 2, "单店餐饮", 1, 75),
    ("蜀王火锅食材供应链", "dealer", 1, "一级经销商", 0, 1200),
    ("蓉城调味品商贸", "dealer", 1, "一级经销商", 0, 900),
    ("川味源食品（广州）", "dealer", 3, "二级分销", 0, 520),
    ("南方火锅食材（深圳）", "dealer", 3, "一级经销商", 0, 780),
    ("佛山顺德味业", "dealer", 3, "二级分销", 0, 430),
    ("长沙湘味调料商行", "dealer", 4, "二级分销", 0, 360),
    ("株洲餐饮配送中心", "dealer", 4, "二级分销", 0, 280),
    ("西安秦味商贸", "dealer", 5, "一级经销商", 0, 640),
    ("咸阳餐饮供应链", "dealer", 5, "二级分销", 0, 300),
    ("郑州中原调味", "dealer", 6, "一级经销商", 0, 700),
    ("洛阳火锅食材城", "dealer", 6, "二级分销", 0, 260),
    ("永辉超市（四川区）", "supermarket", 1, "商超", 0, 380),
    ("红旗连锁（成都）", "supermarket", 1, "商超", 0, 320),
    ("华润万家（深圳）", "supermarket", 3, "商超", 0, 290),
    ("蜀香园餐饮集团总部", "group", 1, "企业团购", 12, 460),
    ("成都高新区管委会食堂", "group", 1, "企业团购", 0, 150),
    ("海底捞（西南片区）", "restaurant", 1, "连锁火锅总部", 8, 520),
]

LEADS = [
    ("鲜货火锅·建设路店", "抖音/短视频", "待跟进", 68),
    ("牛签签串串香（新店）", "转介绍", "跟进中", 75),
    ("滋味空间火锅（德阳）", "展会", "待跟进", 52),
    ("成都食韵餐饮有限公司", "官网咨询", "跟进中", 81),
    ("三只蛙火锅（绵阳）", "市场拓客", "待跟进", 45),
    ("渝味晓宇火锅（江北）", "老客户复购", "跟进中", 88),
    ("辣妹子火锅城", "招商加盟", "无效", 20),
    ("好又来火锅（佛山）", "展会", "待跟进", 60),
    ("乡里乡亲火锅（株洲）", "市场拓客", "有效", 92),
    ("川江号子火锅（西安）", "抖音/短视频", "跟进中", 70),
    ("成都味源商贸（新客）", "招商加盟", "待跟进", 58),
    ("渝北区老码头火锅", "转介绍", "跟进中", 64),
    ("九龙坡火锅食材批发行", "市场拓客", "待跟进", 48),
    ("香天下火锅（郑州）", "展会", "跟进中", 73),
    ("洛阳老城涮锅坊", "官网咨询", "待跟进", 55),
]

COMPLAINT_TYPES = ["口味问题", "变质", "胀袋", "漏袋", "配送破损", "临期", "数量短缺", "包装不符"]
SOLUTIONS = [
    "第一时间补发同批次产品，并回收问题样品送检",
    "已安排业务上门沟通，按 1:1.5 补偿并赠送新品试用",
    "确认为运输挤压导致，已更换包装并加强防护",
    "客户储存方式不当，已提供储存指引并赠送样品",
]


def gen(clear=False):
    db = SessionLocal()
    try:
        if clear:
            for m in (FollowUp, SampleItem, SampleApplication, RebateRecord, RebatePolicy,
                      CrossSale, Complaint, Invoice, Payment, OrderItem, Order, Opportunity,
                      Contact, CustomerTag, Contract, Lead, Customer):
                db.query(m).delete()
            db.commit()
            print("已清空业务数据（用户/产品/字典保留）")
            return

        if db.query(Customer).first():
            print("已存在客户数据，跳过演示数据生成（如需重建：python -m app.demo_data --clear）")
            return

        users = db.query(User).all()
        if not users:
            print("请先运行 seed 初始化基础数据")
            return
        reps = [u for u in users if u.role == "salesrep"] or users
        director = next((u for u in users if u.role == "sales_director"), users[0])
        finance = next((u for u in users if u.role == "finance"), users[0])
        service = next((u for u in users if u.role == "after_sales"), users[0])
        products = db.query(Product).all()
        levels = db.query(CustomerLevel).all()
        channels = {c.name: c.id for c in db.query(ChannelType).all()}
        regions = {r.name: r.id for r in db.query(Region).filter(Region.level == 2).all()}
        region_names = list(regions.keys())

        now = datetime.now()
        today = date.today()

        # ---------------- 客户
        customers = []
        for i, (name, ctype, region_idx, ch, stores, consume) in enumerate(CUSTOMERS):
            owner = reps[i % len(reps)]
            created = now - timedelta(days=random.randint(5, 400))
            c = Customer(
                name=name, customer_type=ctype, region_id=regions.get(region_names[i % len(region_names)]),
                channel_type_id=channels.get(ch), level_id=levels[min(i % 4, len(levels) - 1)].id,
                owner_id=owner.id, credit_code=f"91510100{random.randint(10000000, 99999999)}X",
                address=f"{region_names[i % len(region_names)]}示例路 {random.randint(1, 200)} 号",
                phone=f"1{random.choice(['3','5','8','9'])}{random.randint(100000000, 999999999)}",
                source=random.choice(["展会", "转介绍", "市场拓客", "官网咨询", "招商加盟"]),
                store_count=stores, table_count=stores * random.randint(15, 45) if stores else None,
                monthly_consumption=consume, current_competitor=random.choice(["老干妈", "六必居", "川南", "无"]),
                delivery_method=random.choice(["自有车辆", "第三方物流", "客户自提"]),
                delivery_cycle=random.choice(["每周1次", "每两周1次", "每月1次"]),
                payment_term=random.choice(["现结", "月结30天", "月结30天", "月结60天"]),
                credit_limit=random.choice([20000, 50000, 80000, 120000, 200000]),
                created_at=created,
                last_follow_at=now - timedelta(days=random.randint(1, 40)),
                next_follow_at=now + timedelta(days=random.randint(-5, 12)),
                remark="由演示数据生成",
            )
            db.add(c); db.flush()
            customers.append(c)
            db.add(Contact(customer_id=c.id, name=random.choice(["张", "李", "王", "刘", "陈", "杨"]) + random.choice(["总", "经理", "老板", "主管"]),
                           title=random.choice(["采购经理", "老板", "后厨负责人", "店长"]),
                           phone=f"1{random.choice(['3','5','8'])}{random.randint(100000000, 999999999)}",
                           is_primary=True))
            for t in random.sample(["价格敏感", "品质优先", "连锁总部", "账期客户", "潜力大", "竞品在用"],
                                   random.randint(1, 2)):
                db.add(CustomerTag(customer_id=c.id, tag=t))
        db.commit()

        # ---------------- 合同
        for c in customers[:16]:
            start = today - timedelta(days=random.randint(30, 300))
            end = start + timedelta(days=365)
            db.add(Contract(contract_no=f"HT{start.strftime('%Y%m')}{c.id:03d}", customer_id=c.id,
                            owner_id=c.owner_id, title=f"{c.name} 年度供货合同",
                            amount=random.choice([200000, 350000, 500000, 800000]),
                            status="执行中", sign_date=start, start_date=start, end_date=end,
                            reminder_date=end - timedelta(days=30)))
        db.commit()

        # ---------------- 线索
        for i, (name, source, status, score) in enumerate(LEADS):
            created = now - timedelta(days=random.randint(0, 60))
            db.add(Lead(customer_name=name, source=source, status=status, score=score,
                        contact=random.choice(["王经理", "李老板", "刘店长", "陈总"]),
                        phone=f"1{random.choice(['3','5','8'])}{random.randint(100000000, 999999999)}",
                        address=random.choice(region_names) + "示例街道",
                        intend_product=random.choice([p.name for p in products]),
                        owner_id=reps[i % len(reps)].id,
                        is_pool=(i % 4 == 0),
                        last_follow_at=created,
                        next_follow_at=created + timedelta(days=random.randint(1, 10)),
                        created_at=created,
                        note="演示线索"))
        # 公海线索无归属
        db.query(Lead).filter(Lead.is_pool == True).update({"owner_id": None})  # noqa
        db.commit()

        # ---------------- 商机
        stage_weight = {"初步接触": 0.18, "需求确认": 0.22, "样品测试": 0.24,
                        "报价谈判": 0.18, "合同确认": 0.10, "成交": 0.08}
        opps = []
        for i, c in enumerate(customers):
            for k in range(random.randint(1, 2)):
                stage = random.choices(list(stage_weight), weights=list(stage_weight.values()))[0]
                created = now - timedelta(days=random.randint(5, 180))
                o = Opportunity(
                    customer_id=c.id, owner_id=c.owner_id,
                    name=f"{c.name[:6]}·{random.choice(['蘸料供货', '新品试用', '年度框架', '定制配方'])}",
                    amount=random.choice([30000, 50000, 80000, 120000, 200000, 350000]),
                    intend_product=random.choice([p.name for p in products]),
                    source=random.choice(["展会", "转介绍", "老客户复购"]),
                    stage=stage, win_prob={"初步接触": 10, "需求确认": 30, "样品测试": 45,
                                          "报价谈判": 60, "合同确认": 80, "成交": 100}[stage],
                    expected_close=(created + timedelta(days=random.randint(15, 90))).date(),
                    created_at=created, last_follow_at=created + timedelta(days=random.randint(1, 10)),
                    next_action=random.choice(["寄样品", "出报价", "约拜访", "等客户内部决策"]),
                )
                db.add(o); db.flush()
                opps.append(o)
        db.commit()

        # ---------------- 订单 + 回款 + 发票（覆盖近 12 个月）
        order_seq = 0
        for m in range(11, -1, -1):
            month_start = (now.replace(day=1) - timedelta(days=31 * m)).replace(day=1)
            # 每月 12~22 单
            for _ in range(random.randint(12, 22)):
                c = random.choice(customers)
                od = month_start + timedelta(days=random.randint(0, 27), hours=random.randint(9, 18))
                if od > now:
                    od = now - timedelta(hours=random.randint(1, 48))
                order_seq += 1
                o = Order(order_no=f"SO{od.strftime('%y%m%d')}{order_seq:03d}", customer_id=c.id,
                          owner_id=c.owner_id, status=random.choices(
                              ["已完成", "已发货", "待发货", "待确认", "已取消"],
                              weights=[0.55, 0.2, 0.14, 0.08, 0.03])[0],
                          account_term=c.payment_term, created_at=od,
                          receiver=c.name[:6] + "收货人", receiver_phone=c.phone,
                          address=c.address,
                          ship_date=(od + timedelta(days=2)).date())
                db.add(o); db.flush()
                total = 0
                for p in random.sample(products, random.randint(2, 5)):
                    qty = random.choice([200, 300, 500, 800, 1000, 1500, 2000])
                    price = round((p.supply_price or 10) * random.choice([1, 1, 0.95, 1.05]), 2)
                    amt = round(qty * price, 2)
                    total += amt
                    db.add(OrderItem(order_id=o.id, product_id=p.id, qty=qty,
                                     unit_price=price, amount=amt))
                o.total_amount = round(total, 2)
                # 回款：已完成/已发货大部分已回款
                if o.status in ("已完成", "已发货") and random.random() < 0.82:
                    ratio = random.choice([1, 1, 1, 0.6, 0.4])
                    pd_ = od.date() + timedelta(days=random.randint(3, 40))
                    if pd_ > today:
                        pd_ = today
                    db.add(Payment(pay_no=f"HK{od.strftime('%y%m%d')}{order_seq:03d}",
                                   order_id=o.id, customer_id=c.id, owner_id=c.owner_id,
                                   amount=round(total * ratio, 2), pay_date=pd_,
                                   pay_method=random.choice(["银行转账", "微信", "承兑汇票", "支付宝"]),
                                   status="已确认", created_at=od + timedelta(days=5)))
                    if ratio == 1:
                        db.add(Invoice(invoice_no=f"FP{od.strftime('%y%m%d')}{order_seq:03d}",
                                       customer_id=c.id, order_id=o.id, amount=round(total, 2),
                                       status="已开票", invoice_date=pd_,
                                       title=c.name, tax_no=c.credit_code, created_at=od))
            db.commit()

        # ---------------- 跟进记录
        results = ["客户有意向，约下周试味", "已寄样品，等待反馈", "价格偏高，需申请特价",
                   "确认年度框架，进入合同流程", "客户暂时观望，保持联系"]
        for _ in range(220):
            c = random.choice(customers)
            ftype = random.choice(["电话", "微信", "上门", "邮件"])
            created = now - timedelta(days=random.randint(0, 200), hours=random.randint(0, 10))
            db.add(FollowUp(customer_id=c.id, owner_id=c.owner_id, ftype=ftype,
                            content=random.choice([
                                "沟通本月用量与配送安排", "介绍新口味复合蘸料", "跟进样品反馈",
                                "催收上月货款", "了解竞品使用情况", "确认节前备货计划",
                                "邀请参加火锅食材展", "处理配送破损问题",
                            ]),
                            result=random.choice(results),
                            next_at=created + timedelta(days=random.randint(3, 15)),
                            created_at=created))
        db.commit()

        # ---------------- 样品
        for _ in range(26):
            c = random.choice(customers)
            created = now - timedelta(days=random.randint(1, 150))
            sa = SampleApplication(apply_no=f"YP{created.strftime('%y%m%d')}{random.randint(100, 999)}",
                                   customer_id=c.id, owner_id=c.owner_id,
                                   purpose=random.choice(["门店试味", "新品测试", "连锁总部评审"]),
                                   freight_payer=random.choice(["我方", "客户"]),
                                   status=random.choice(["待审批", "已通过", "已寄出", "已签收", "已驳回"]),
                                   created_at=created)
            db.add(sa); db.flush()
            cost = 0
            for p in random.sample(products, random.randint(1, 3)):
                qty = random.randint(1, 3)
                cost += (p.cost or 0) * qty
                db.add(SampleItem(application_id=sa.id, product_id=p.id, qty=qty))
            sa.total_cost = round(cost, 2)
        db.commit()

        # ---------------- 客诉
        for _ in range(24):
            c = random.choice(customers)
            created = now - timedelta(days=random.randint(1, 120))
            status = random.choice(["新建", "处理中", "待回访", "已结案", "已结案"])
            cp = Complaint(complaint_no=f"KS{created.strftime('%y%m%d')}{random.randint(100, 999)}",
                           customer_id=c.id, owner_id=c.owner_id, assignee_id=service.id,
                           ctype=random.choice(COMPLAINT_TYPES),
                           urgency=random.choice(["高", "中", "中", "低"]),
                           batch=f"B{random.randint(202501, 202612)}",
                           description=random.choice([
                               "客户反馈麻酱偏咸，口味不稳定", "到货发现有 2 袋胀袋",
                               "配送过程中瓶体破损", "临期产品未提前告知",
                               "订单数量与实物不符，少了 5 件", "包装标签印刷不清晰",
                           ]),
                           status=status,
                           solution=random.choice(SOLUTIONS) if status != "新建" else None,
                           result="客户接受处理方案" if status == "已结案" else None,
                           deadline=(created + timedelta(days=3)).date(),
                           closed_at=created + timedelta(days=random.randint(1, 5)) if status == "已结案" else None,
                           created_at=created)
            db.add(cp)
        db.commit()

        # ---------------- 返利
        policy = RebatePolicy(name="2026 年度经销商返利", period="年度", threshold_ton=50,
                              rebate_rate=3.0, active=1)
        db.add(policy); db.flush()
        for c in random.sample(customers, 8):
            db.add(RebateRecord(customer_id=c.id, policy_id=policy.id, period="2026年度",
                                amount=random.choice([5000, 8000, 12000, 20000]),
                                status=random.choice(["待核算", "待审批", "已批准", "已兑现"]),
                                redeem_type=random.choice(["货款抵扣", "现金"])))
        db.commit()

        # ---------------- 窜货
        for _ in range(5):
            c = random.choice([x for x in customers if x.customer_type == "dealer"])
            db.add(CrossSale(product_batch=f"B{random.randint(202501, 202612)}",
                             dealer_id=c.id, found_location=random.choice(region_names) + "批发市场",
                             status=random.choice(["待处理", "处理中", "已处理"]),
                             handle_result="已按窜货管理办法扣减返利并警告",
                             reporter_id=reps[0].id))
        db.commit()

        print(f"演示数据生成完成：客户 {len(customers)}、商机 {len(opps)}、订单 {order_seq}")
    finally:
        db.close()


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    gen(clear="--clear" in sys.argv)
