"""依赖注入：当前用户、角色校验、行级权限"""
from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.security import decode_token

ROLE_LABELS = {
    "super_admin": "超级管理员",
    "sales_director": "销售总监",
    "regional_manager": "区域销售主管",
    "salesrep": "业务员",
    "finance": "财务",
    "after_sales": "售后客服",
    "qc": "产品/品控",
}


def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = authorization[7:]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="无效令牌")
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user or user.status != 1:
        raise HTTPException(status_code=401, detail="账号不可用")
    return user


def require_roles(*roles):
    def checker(user: User = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="无权限")
        return user
    return checker


def is_manager_or_above(role: str) -> bool:
    return role in ("super_admin", "sales_director", "regional_manager")


def visible_user_ids(db: Session, user: User):
    """返回当前用户可查看的下属用户 id 列表（含自己）"""
    if user.role in ("super_admin", "sales_director"):
        return None  # None 表示全部
    if user.role == "regional_manager":
        ids = [u.id for u in db.query(User).filter(User.parent_id == user.id).all()]
        ids.append(user.id)
        return ids
    return [user.id]


def customer_owner_filter(db: Session, user: User):
    """返回 (owner_ids_or_None, region_ids_or_None) 用于客户可见性过滤"""
    if user.role in ("super_admin", "sales_director", "finance", "after_sales", "qc"):
        return None, None  # 这些角色看全公司客户
    if user.role == "regional_manager":
        ids = [u.id for u in db.query(User).filter(User.parent_id == user.id).all()]
        ids.append(user.id)
        return ids, None
    return [user.id], None
