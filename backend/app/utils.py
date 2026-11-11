"""通用工具：序列化、时间区间、行级权限、操作日志"""
from datetime import datetime, date, timedelta
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from app.models import User, AuditLog


# ---------------------------------------------------------------- 序列化
def ser(obj, **extra):
    """把 SQLAlchemy 对象转成可 JSON 的 dict（日期转字符串）"""
    if obj is None:
        return None
    d = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name, None)
        if isinstance(v, datetime):
            v = v.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(v, date):
            v = v.isoformat()
        d[col.name] = v
    d.update(extra)
    return d


def ser_list(rows, **extra):
    return [ser(r, **extra) for r in rows]


def money(v) -> float:
    try:
        return round(float(v or 0), 2)
    except Exception:
        return 0.0


# ---------------------------------------------------------------- 时间区间
PERIODS = {
    "today": "今天", "yesterday": "昨天", "week": "本周", "last_week": "上周",
    "month": "本月", "last_month": "上月", "quarter": "本季度", "last_quarter": "上季度",
    "year": "本年", "last_year": "去年", "all": "全部",
}


def period_range(period: str) -> Tuple[Optional[datetime], Optional[datetime], Optional[datetime], Optional[datetime]]:
    """返回 (本期起, 本期止, 上期起, 上期止)；period=all 时全部为 None"""
    now = datetime.now()
    today = datetime(now.year, now.month, now.day)

    def day(d): return datetime(d.year, d.month, d.day)
    def add_months(d, n):
        y = d.year + (d.month - 1 + n) // 12
        m = (d.month - 1 + n) % 12 + 1
        return datetime(y, m, 1)

    if period in ("", "all", None):
        return None, None, None, None
    if period == "today":
        s, e = today, today + timedelta(days=1)
        return s, e, s - timedelta(days=1), s
    if period == "yesterday":
        s = today - timedelta(days=1)
        return s, today, s - timedelta(days=1), s
    if period == "week":
        s = today - timedelta(days=today.weekday())
        return s, s + timedelta(days=7), s - timedelta(days=7), s
    if period == "last_week":
        s = today - timedelta(days=today.weekday() + 7)
        return s, s + timedelta(days=7), s - timedelta(days=7), s
    if period == "month":
        s = datetime(now.year, now.month, 1)
        return s, add_months(s, 1), add_months(s, -1), s
    if period == "last_month":
        s = add_months(datetime(now.year, now.month, 1), -1)
        return s, add_months(s, 1), add_months(s, -1), s
    if period == "quarter":
        qm = (now.month - 1) // 3 * 3 + 1
        s = datetime(now.year, qm, 1)
        return s, add_months(s, 3), add_months(s, -3), s
    if period == "last_quarter":
        qm = (now.month - 1) // 3 * 3 + 1
        s = add_months(datetime(now.year, qm, 1), -3)
        return s, add_months(s, 3), add_months(s, -3), s
    if period == "year":
        s = datetime(now.year, 1, 1)
        return s, datetime(now.year + 1, 1, 1), datetime(now.year - 1, 1, 1), s
    if period == "last_year":
        s = datetime(now.year - 1, 1, 1)
        return s, datetime(now.year, 1, 1), datetime(now.year - 2, 1, 1), s
    return None, None, None, None


def in_range(qs, col, start, end):
    if start is not None:
        qs = qs.filter(col >= start)
    if end is not None:
        qs = qs.filter(col < end)
    return qs


# ---------------------------------------------------------------- 权限
ROLE_LABELS = {
    "super_admin": "超级管理员",
    "sales_director": "销售总监",
    "regional_manager": "区域销售主管",
    "salesrep": "业务员",
    "finance": "财务",
    "after_sales": "售后客服",
    "qc": "产品/品控",
}

# 可见全公司数据的角色
GLOBAL_ROLES = ("super_admin", "sales_director", "finance", "after_sales", "qc")


def subordinate_ids(db: Session, user: User):
    """本人 + 直接/间接下属"""
    ids, stack = [user.id], [user.id]
    while stack:
        cur = stack.pop()
        for u in db.query(User).filter(User.parent_id == cur).all():
            if u.id not in ids:
                ids.append(u.id)
                stack.append(u.id)
    return ids


def scope_ids(db: Session, user: User, want: str = "auto"):
    """返回可见 owner_id 列表；None = 不限
    want: auto(角色默认) / mine(仅本人) / dept(本部门) / all(全公司)
    """
    if want == "mine":
        return [user.id]
    if want == "all" and user.role in GLOBAL_ROLES:
        return None
    if user.role in GLOBAL_ROLES and want != "dept":
        return None
    if user.role == "regional_manager":
        return subordinate_ids(db, user) if want in ("auto", "dept") else [user.id]
    return [user.id]


def apply_scope(qs, model, db, user, want="auto", col="owner_id"):
    ids = scope_ids(db, user, want)
    if ids is not None:
        qs = qs.filter(getattr(model, col).in_(ids))
    return qs


# ---------------------------------------------------------------- 操作日志
def log(db: Session, user: Optional[User], action: str, module: str,
        record_id: int = None, detail: str = "", ip: str = "", table: str = ""):
    try:
        db.add(AuditLog(
            user_id=user.id if user else None,
            user_name=user.name if user else "系统",
            action=action, module=module, table_name=table or module,
            record_id=record_id, detail=detail[:2000] if detail else "", ip=ip,
        ))
        db.commit()
    except Exception:
        db.rollback()


# ---------------------------------------------------------------- 编号
def gen_no(prefix: str) -> str:
    return f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}{int(datetime.now().microsecond/1000):02d}"


def pct(a, b):
    """增长率：b 为上期值"""
    a, b = float(a or 0), float(b or 0)
    if b == 0:
        return 100.0 if a > 0 else 0.0
    return round((a - b) / b * 100, 1)
