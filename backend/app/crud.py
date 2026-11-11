"""通用增删改：类型矫正 + 审计日志"""
from datetime import datetime, date
from sqlalchemy import Date, DateTime, Integer, Float, Boolean
from sqlalchemy.orm import Session
from app.models import User
from app.utils import log, ser


def parse_dt(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    s = str(v).strip().replace("T", " ").replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19] if len(s) > 10 else s, fmt)
        except Exception:
            continue
    return None


def parse_date(v):
    d = parse_dt(v)
    return d.date() if d else None


def coerce(model, data: dict) -> dict:
    cols = {c.name: c for c in model.__table__.columns}
    out = {}
    for k, v in (data or {}).items():
        c = cols.get(k)
        if c is None or k == "id":
            continue
        if v == "":
            v = None
        if v is not None:
            t = c.type
            try:
                if isinstance(t, Boolean):
                    v = bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "yes", "on")
                elif isinstance(t, DateTime):
                    v = parse_dt(v)
                elif isinstance(t, Date):
                    v = parse_date(v)
                elif isinstance(t, Integer):
                    v = int(float(v))
                elif isinstance(t, Float):
                    v = float(v)
            except Exception:
                v = None
        out[k] = v
    return out


def create_obj(db: Session, model, data: dict, user: User = None, module: str = "", extra: dict = None):
    vals = coerce(model, data)
    if extra:
        vals.update({k: v for k, v in extra.items() if v is not None})
    obj = model(**vals)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    if user:
        log(db, user, "新增", module or model.__tablename__, obj.id,
            f"新增 {getattr(obj, 'name', '') or getattr(obj, 'customer_name', '') or obj.id}")
    return obj


def update_obj(db: Session, obj, data: dict, user: User = None, module: str = "", extra: dict = None):
    vals = coerce(type(obj), data)
    for k, v in vals.items():
        setattr(obj, k, v)
    if extra:
        for k, v in extra.items():
            if v is not None:
                setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    if user:
        log(db, user, "修改", module or obj.__tablename__, obj.id,
            f"修改字段: {', '.join(list(vals.keys())[:10])}")
    return obj


def delete_obj(db: Session, obj, user: User = None, module: str = ""):
    rid = obj.id
    name = getattr(obj, "name", "") or getattr(obj, "customer_name", "") or str(rid)
    db.delete(obj)
    db.commit()
    if user:
        log(db, user, "删除", module or type(obj).__tablename__, rid, f"删除 {name}")
    return {"ok": True}


def ok(obj=None):
    return {"ok": True, "data": ser(obj) if obj is not None and hasattr(obj, "__table__") else obj}
