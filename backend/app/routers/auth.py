"""认证、个人中心与用户管理"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Form, Body
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Region
from app.schemas import UserCreate, UserOut
from app.security import verify_password, create_token, hash_password
from app.deps import get_current_user, require_roles
from app.utils import ROLE_LABELS, ser, log
from app.crud import update_obj

router = APIRouter(prefix="/api", tags=["auth"])

ROLE_DESC = {
    "super_admin": ("超级管理员", "全部数据 + 系统配置 + 用户管理"),
    "sales_director": ("销售总监", "全公司业务数据、审批、业绩目标"),
    "regional_manager": ("区域销售主管", "本部门（含下属）数据、部门内审批"),
    "salesrep": ("业务员", "仅本人负责的线索/客户/商机/订单"),
    "finance": ("财务", "全公司订单、回款、应收、发票，无客户编辑权"),
    "after_sales": ("售后客服", "全公司客诉工单、客户查询"),
    "qc": ("产品/品控", "产品档案、客诉质量分析"),
}


@router.post("/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user.status != 1:
        raise HTTPException(status_code=403, detail="账号已禁用，请联系管理员")
    user.last_login_at = datetime.now()
    db.commit()
    log(db, user, "登录", "系统", user.id, f"{user.name} 登录系统")
    return {
        "access_token": create_token(user.id, user.role),
        "token_type": "bearer",
        "user": _me(user),
    }


def _me(user: User) -> dict:
    return {
        "id": user.id, "name": user.name, "role": user.role,
        "role_label": ROLE_LABELS.get(user.role, user.role),
        "username": user.username, "phone": user.phone, "wechat": user.wechat,
        "email": user.email, "job_no": user.job_no, "region_id": user.region_id,
        "last_login_at": user.last_login_at.strftime("%Y-%m-%d %H:%M") if user.last_login_at else None,
    }


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _me(user)


@router.put("/me")
def update_me(data: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    for k in ("phone", "wechat", "email", "name"):
        if k in data:
            setattr(user, k, data[k])
    db.commit()
    return _me(user)


@router.post("/me/password")
def change_password(data: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not verify_password(data.get("old_password", ""), user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    if len(data.get("new_password", "")) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    user.password_hash = hash_password(data["new_password"])
    db.commit()
    log(db, user, "修改", "个人中心", user.id, "修改登录密码")
    return {"ok": True}


@router.get("/roles")
def roles(_: User = Depends(get_current_user)):
    return [{"value": k, "label": v[0], "desc": v[1]} for k, v in ROLE_DESC.items()]


@router.get("/users")
def list_users(keyword: str = "", role: str = "", db: Session = Depends(get_db),
               user: User = Depends(require_roles("super_admin", "sales_director", "regional_manager"))):
    qs = db.query(User)
    if user.role == "regional_manager":
        ids = [u.id for u in db.query(User).filter(User.parent_id == user.id).all()] + [user.id]
        qs = qs.filter(User.id.in_(ids))
    if keyword:
        qs = qs.filter(User.name.contains(keyword) | User.username.contains(keyword))
    if role:
        qs = qs.filter(User.role == role)
    rows = []
    for u in qs.order_by(User.id).all():
        parent = db.query(User).filter(User.id == u.parent_id).first() if u.parent_id else None
        region = db.query(Region).filter(Region.id == u.region_id).first() if u.region_id else None
        rows.append(ser(u, role_label=ROLE_LABELS.get(u.role, u.role),
                        parent_name=parent.name if parent else "",
                        region_name=region.name if region else ""))
    return rows


@router.post("/users")
def create_user(data: UserCreate, db: Session = Depends(get_db),
                user: User = Depends(require_roles("super_admin", "sales_director", "regional_manager"))):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    if data.role == "super_admin" and user.role != "super_admin":
        raise HTTPException(status_code=403, detail="仅超级管理员可创建超管账号")
    u = User(username=data.username, password_hash=hash_password(data.password), name=data.name,
             role=data.role, region_id=data.region_id, parent_id=data.parent_id,
             phone=data.phone, wechat=data.wechat)
    db.add(u); db.commit(); db.refresh(u)
    log(db, user, "新增", "用户管理", u.id, f"新增用户 {u.name}({u.username})")
    return ser(u)


@router.put("/users/{uid}")
def update_user(uid: int, data: dict = Body(...), db: Session = Depends(get_db),
                user: User = Depends(require_roles("super_admin", "sales_director", "regional_manager"))):
    u = db.query(User).filter(User.id == uid).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if "password" in data and data["password"]:
        u.password_hash = hash_password(data["password"])
    update_obj(db, u, {k: v for k, v in data.items() if k != "password"}, user, "用户管理")
    return ser(u)


@router.delete("/users/{uid}")
def disable_user(uid: int, db: Session = Depends(get_db),
                 user: User = Depends(require_roles("super_admin"))):
    if uid == user.id:
        raise HTTPException(status_code=400, detail="不能禁用自己")
    u = db.query(User).filter(User.id == uid).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    u.status = 0
    db.commit()
    log(db, user, "禁用", "用户管理", uid, f"禁用用户 {u.name}")
    return {"ok": True}
