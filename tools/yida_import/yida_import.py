#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宜搭(YiDa) -> 公司CRM系统 数据导入工具
=====================================
配置驱动：在 config.json 中填写 appKey/appSecret、表单 formUuid 与字段映射。
支持三类数据导入：组织人员(org)、客户与联系人(customer)、产品(product)。

用法（均需用后端 venv 的 python 运行）：
  # 列出应用内所有宜搭表单（先拿到 formUuid）
  python yida_import.py --config config.json --discover-forms
  # 打印某个表单第一条实例的字段键（用来填 field_map）
  python yida_import.py --config config.json --discover-fields <formUuid>
  # 仅预览，不写入数据库
  python yida_import.py --config config.json --dry-run
  # 正式导入（默认先自动备份 crm.db）
  python yida_import.py --config config.json
  # 只导入其中一类
  python yida_import.py --config config.json --modules org,customer

说明：
  - 宜搭表单实例里每个组件的字段键（field id，如 textField_xxx）无法预知，
    务必先用 --discover-fields 打印出来，再填到 config 的 field_map 里。
  - 重复运行安全：用户名/客户名+信用代码/产品编码 命中已存在记录时只更新不新增。
  - 导入的用户默认密码见 config.default_password，登录后可在系统内修改。
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, date

# ------------------------- 定位后端（crm.db 所在 app 目录） -------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_APP_DIRS = [
    os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", "backend", "app")),  # 本地：app 内含 crm.db
    os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", "backend")),         # 本地：crm.db 在 backend 根
    "/root/crm/backend/app",                                                     # 服务器
    "/root/crm/backend",                                                         # 服务器：crm.db 在 backend 根
]


def find_app_dir(explicit=None):
    if explicit:
        return os.path.abspath(explicit)
    for d in DEFAULT_APP_DIRS:
        if os.path.exists(os.path.join(d, "crm.db")):
            return os.path.abspath(d)
    return os.getcwd()


# ------------------------- 宜搭 HTTP 封装（仅用标准库） -------------------------
def http_post_json(url, payload, headers=None, timeout=30):
    data = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = ureq_request(url, data=data, headers=h, timeout=timeout)
    with ureq_urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def http_get_json(url, params=None, headers=None, timeout=30):
    if params:
        from urllib.parse import urlencode
        url = url + ("&" if "?" in url else "?") + urlencode(params)
    req = ureq_request(url, data=None, headers=(headers or {}), timeout=timeout)
    with ureq_urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


# 延迟 import，避免无网络时也能 import 模块做语法检查
def ureq_request(*a, **k):
    from urllib import request as _r
    hdr = k.pop("headers", {})
    req = _r.Request(a[0], data=k.get("data"), headers=hdr, method="POST" if k.get("data") is not None else "GET")
    return req


def ureq_urlopen(req, timeout=30):
    from urllib import request as _r
    return _r.urlopen(req, timeout=timeout)


# ------------------------- 宜搭字段值归一化 -------------------------
def gv(val):
    """宜搭部分组件会把值包成 {'value': ...} 或放到数组里，这里尽量还原成标量。"""
    if isinstance(val, dict):
        if "value" in val:
            return gv(val["value"])
        # 部门/员工组件常形如 {"text":"...","value":"..."}
        if "text" in val and "value" in val:
            return val.get("text")
        return ""
    if isinstance(val, list):
        if not val:
            return ""
        if len(val) == 1:
            return gv(val[0])
        return " / ".join(str(gv(x)) for x in val)
    return val


def to_float(v):
    try:
        return float(gv(v))
    except (TypeError, ValueError):
        return 0.0


def to_int(v):
    try:
        return int(float(gv(v)))
    except (TypeError, ValueError):
        return None


def to_date(v):
    s = str(gv(v) or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def to_str(v):
    x = gv(v)
    return "" if x is None else str(x).strip()


# ------------------------- 宜搭 API 客户端 -------------------------
class YiDaClient:
    def __init__(self, cfg):
        self.cfg = cfg
        # 钉钉开放平台凭据（OAuth2 换 accessToken）
        # 新版：clientId / clientSecret（2024 后钉钉应用），优先使用
        self.dt_client_id = cfg.get("dingtalk_client_id", "")
        self.dt_client_secret = cfg.get("dingtalk_client_secret", "")
        self.dt_app_id = cfg.get("dingtalk_app_id", "")
        # 旧版：appKey / appSecret（兼容老应用）
        self.dt_app_key = cfg.get("dingtalk_app_key", "")
        self.dt_app_secret = cfg.get("dingtalk_app_secret", "")
        # 宜搭应用凭据（业务参数：appType / systemToken）
        self.yida_app_type = cfg.get("yida_app_type", cfg.get("app_key", ""))
        self.yida_system_token = cfg.get("yida_system_token", cfg.get("app_secret", ""))
        self.manager_user_id = cfg.get("manager_user_id", "")
        api = cfg.get("api", {})
        self.token_url = api.get("token_url", "https://api.dingtalk.com/v1.0/oauth2/accessToken")
        self.instance_url = api.get("instance_url", "https://api.dingtalk.com/v1.0/yida/forms/instances/query")
        self.forms_url = api.get("forms_url", "https://api.dingtalk.com/v1.0/yida/forms")
        self.auth_header = api.get("auth_header", "x-acs-dingtalk-access-token")
        self._token = None

    def get_token(self):
        if self._token:
            return self._token
        if self.dt_client_id and self.dt_client_secret:
            # 钉钉新版凭据（clientId / clientSecret），接口字段名仍为 appKey/appSecret
            r = http_post_json(self.token_url,
                               {"appKey": self.dt_client_id,
                                "appSecret": self.dt_client_secret,
                                "grantType": "client_credentials"})
        elif self.dt_app_key and self.dt_app_secret:
            # 钉钉旧版 OAuth2（appKey / appSecret）
            r = http_post_json(self.token_url,
                               {"appKey": self.dt_app_key,
                                "appSecret": self.dt_app_secret,
                                "grantType": "client_credentials"})
        else:
            raise RuntimeError("缺少钉钉 OAuth2 凭据（请在 config 填 dingtalk_client_id/dingtalk_client_secret 或 dingtalk_app_key/dingtalk_app_secret）")
        self._token = r.get("accessToken") or r.get("access_token")
        if not self._token:
            raise RuntimeError("获取 access_token 失败，返回：%s" % json.dumps(r, ensure_ascii=False))
        return self._token

    def _headers(self):
        return {self.auth_header: self.get_token()}

    def list_forms(self):
        """列出应用内所有宜搭表单。"""
        params = {
            "appType": self.yida_app_type,
            "systemToken": self.yida_system_token,
            "userId": self.manager_user_id,
            "language": "zh_CN",
        }
        r = http_get_json(self.forms_url, params=params, headers=self._headers())
        return r

    def fetch_instances(self, form_uuid, page_size=100):
        """分页拉取某表单全部实例，返回 list[dict(formData)]。"""
        token = self.get_token()
        out = []
        page = 1
        modified_from = self.cfg.get("modified_from", "2000-01-01 00:00:00")
        modified_to = self.cfg.get("modified_to", "2099-12-31 23:59:59")
        while True:
            body = {
                "appType": self.yida_app_type,
                "systemToken": self.yida_system_token,
                "userId": self.manager_user_id,
                "language": "zh_CN",
                "formUuid": form_uuid,
                "pageNumber": page,
                "pageSize": page_size,
                "modifiedFrom": modified_from,
                "modifiedTo": modified_to,
                "searchFieldJson": "{}",
            }
            r = http_post_json(self.instance_url, body, headers={self.auth_header: token})
            result = r.get("result") or r
            data = result.get("data") or []
            for row in data:
                fd = row.get("formData") if isinstance(row, dict) else row
                if isinstance(fd, dict):
                    out.append(fd)
            total = result.get("totalCount") or 0
            if len(data) < page_size or not data:
                break
            page += 1
            if page > 200:  # 安全上限 2 万条/表单
                break
        return out

    def discover_fields(self, form_uuid):
        """只取首页第一条实例的字段键（不翻页，避免 page_size=1 死循环）。"""
        token = self.get_token()
        body = {
            "appType": self.yida_app_type,
            "systemToken": self.yida_system_token,
            "userId": self.manager_user_id,
            "language": "zh_CN",
            "formUuid": form_uuid,
            "pageNumber": 1,
            "pageSize": 1,
            "modifiedFrom": self.cfg.get("modified_from", "2000-01-01 00:00:00"),
            "modifiedTo": self.cfg.get("modified_to", "2099-12-31 23:59:59"),
            "searchFieldJson": "{}",
        }
        r = http_post_json(self.instance_url, body, headers={self.auth_header: token})
        result = r.get("result") or r
        data = result.get("data") or []
        total = result.get("totalCount") or 0
        if not data:
            return {"__totalCount__": total}
        fd = data[0].get("formData") if isinstance(data[0], dict) else data[0]
        return fd if isinstance(fd, dict) else {}


# ------------------------- 钉钉通讯录客户端 -------------------------
class DingTalkContactClient:
    """钉钉通讯录（v1.0 contact API）。需应用已订阅通讯录读权限，否则返回 404。"""
    def __init__(self, cfg, token):
        self.token = token
        self.base = "https://api.dingtalk.com/v1.0"
        self.hdr = {"x-acs-dingtalk-access-token": token, "Content-Type": "application/json"}

    def list_departments(self):
        depts, page = [], ""
        while True:
            url = self.base + "/contact/departments?size=100" + (("&pageToken=" + page) if page else "")
            r = http_get_json(url, headers=self.hdr)
            res = r.get("result") or r
            data = res.get("data") or []
            depts.extend(data)
            page = res.get("nextToken")
            if not page or not data:
                break
        return depts

    def list_users(self, dept_id):
        if not dept_id:
            return []
        users, page = [], ""
        while True:
            url = self.base + "/contact/users?departmentId=%s&size=100" % dept_id + (("&pageToken=" + page) if page else "")
            r = http_get_json(url, headers=self.hdr)
            res = r.get("result") or r
            data = res.get("data") or []
            users.extend(data)
            page = res.get("nextToken")
            if not page or not data:
                break
        return users


# ------------------------- DB 辅助 -------------------------
def get_or_create(db, model, defaults=None, **kwargs):
    inst = db.query(model).filter_by(**kwargs).first()
    if inst:
        if defaults:
            for k, v in defaults.items():
                setattr(inst, k, v)
        return inst, False
    params = dict(kwargs)
    if defaults:
        params.update(defaults)
    inst = model(**params)
    db.add(inst)
    db.flush()
    return inst, True


def resolve_ref(db, model, name, **extra):
    """按 name 取/建一条引用表记录（regions/channel_types/customer_levels 等）。"""
    name = to_str(name)
    if not name:
        return None
    inst = db.query(model).filter_by(name=name).first()
    if inst:
        return inst
    params = {"name": name}
    params.update(extra)
    inst = model(**params)
    db.add(inst)
    db.flush()
    return inst


def resolve_customer_level(db, name, code_map=None):
    """客户等级：CustomerLevel.code 非空，必须带编码。"""
    name = to_str(name)
    if not name:
        return None
    inst = db.query(CustomerLevel).filter_by(name=name).first()
    if inst:
        return inst
    code = (code_map or {}).get(name) or name[:10]
    inst = CustomerLevel(name=name, code=code)
    db.add(inst)
    db.flush()
    return inst


def build_desc(row, fields):
    """把多个字段值拼成描述文本。"""
    parts = []
    for f in (fields or []):
        v = to_str(row.get(f))
        if v:
            parts.append(v)
    return " / ".join(parts)


def preprocess_customer_rows(rows, m):
    """宜搭同一公司常有多个表单实例（部分字段为空、信用码新旧格式并存）。
    按客户名称合并：取最完整实例为主，用其它实例补填空字段；全空行直接丢弃。"""
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        name = to_str(r.get(m.get("name", "name")))
        if name:
            groups[name].append(r)
    out = []
    for name, grp in groups.items():
        def completeness(r):
            s = 0
            for k in m.values():
                if to_str(r.get(k)):
                    s += 1
            cr = to_str(r.get(m.get("credit_code", "")))
            if len(cr) == 18:
                s += 100
            elif cr:
                s += 50
            return s
        grp.sort(key=completeness, reverse=True)
        merged = dict(grp[0])
        for r in grp[1:]:
            for k, v in r.items():
                if not to_str(merged.get(k)) and to_str(v):
                    merged[k] = v
        cr = to_str(merged.get(m.get("credit_code", "")))
        region = to_str(merged.get(m.get("region", "")))
        addr = to_str(merged.get(m.get("address", "")))
        cn = to_str(merged.get(m.get("contact_name", "")))
        cp = to_str(merged.get(m.get("contact_phone", "")))
        if not (cr or region or addr or cn or cp):
            continue  # 全空实例，丢弃
        out.append(merged)
    return out


# ------------------------- 三类导入器 -------------------------
def detect_role(dept_name, rules, default="salesrep"):
    for r in rules or []:
        if r.get("contains") and r["contains"] in (dept_name or ""):
            return r["role"]
    return default


def compute_depth(dept_id, depts, dept_id_map):
    depth = 1
    pid = None
    for d in depts:
        if d.get("deptId") == dept_id:
            pid = d.get("parentDeptId")
            break
    seen = set()
    while pid and pid not in seen:
        seen.add(pid)
        depth += 1
        nxt = None
        for d in depts:
            if d.get("deptId") == pid:
                nxt = d.get("parentDeptId")
                break
        pid = nxt
    return depth


def import_org(client, db, cfg, dry_run, stats):
    """从钉钉通讯录导入组织人员：部门->regions，员工->users。
    需要钉钉应用已订阅「通讯录」API（部门/成员读权限），否则会报 404。"""
    from app.security import hash_password
    dt = DingTalkContactClient(cfg, client.get_token())
    print("[org] 拉取钉钉通讯录部门...")
    depts = dt.list_departments()
    print("[org] 部门数=%d，开始建立 regions" % len(depts))
    dept_id_map = {}
    for d in depts:
        name = to_str(d.get("name"))
        if not name:
            continue
        region, _ = get_or_create(db, Region, defaults={"level": 1}, name=name)
        dept_id_map[d.get("deptId")] = region.id
    for d in depts:
        rid = dept_id_map.get(d.get("deptId"))
        if rid is None:
            continue
        pid = dept_id_map.get(d.get("parentDeptId"))
        region = db.query(Region).filter_by(id=rid).first()
        if region:
            region.parent_id = pid
            region.level = compute_depth(d.get("deptId"), depts, dept_id_map)

    role_rules = cfg.get("role_rules", [])
    default_pwd = cfg.get("default_password", "123456")
    all_users = []
    for d in depts:
        all_users.extend(dt.list_users(d.get("deptId")))
    print("[org] 员工数=%d，开始建立 users" % len(all_users))
    stats["org_total"] = len(all_users)
    user_id_map = {}
    for u in all_users:
        name = to_str(u.get("name"))
        if not name:
            continue
        userid = to_str(u.get("userId"))
        mobile = to_str(u.get("mobile"))
        email = to_str(u.get("email"))
        username = mobile or userid or name
        if not username:
            continue
        raw_dept = u.get("deptId")
        dept_list = raw_dept if isinstance(raw_dept, (list, tuple)) else ([raw_dept] if raw_dept else [])
        region_id = dept_id_map.get(dept_list[0]) if dept_list else None
        role = detect_role(name, role_rules, cfg.get("default_role", "salesrep"))
        user, created = get_or_create(
            db, User,
            defaults={
                "name": name,
                "role": role,
                "region_id": region_id,
                "phone": mobile,
                "email": email,
                "wechat": to_str(u.get("unionId")),
                "job_no": userid,
                "status": 1,
            },
            username=username,
        )
        if created:
            user.password_hash = hash_password(default_pwd)
            stats["org_created"] += 1
        else:
            stats["org_updated"] += 1
        user_id_map[userid] = user.id
    for u in all_users:
        userid = to_str(u.get("userId"))
        mgr = to_str(u.get("managerUserId") or u.get("managerUserid"))
        uid = user_id_map.get(userid)
        if uid is None or not mgr:
            continue
        puid = user_id_map.get(mgr)
        if puid:
            user = db.query(User).filter_by(id=uid).first()
            if user:
                user.parent_id = puid
    if not dry_run:
        db.commit()
    else:
        db.rollback()


def import_customer(client, db, cfg, dry_run, stats):
    m = cfg.get("field_map", {}).get("customer", {})
    fu = cfg["forms"].get("customer")
    if not fu:
        print("[customer] 未在 config.forms.customer 配置 formUuid，跳过。")
        return
    rows = client.fetch_instances(fu)
    rows = preprocess_customer_rows(rows, m)
    stats["customer_total"] = len(rows)
    for row in rows:
        name = to_str(row.get(m.get("name", "name")))
        if not name:
            continue
        credit = to_str(row.get(m.get("credit_code", "")))
        region = resolve_ref(db, Region, to_str(row.get(m.get("region", ""))), level=1) if m.get("region") else None
        channel = resolve_ref(db, ChannelType, to_str(row.get(m.get("channel", "")))) if m.get("channel") else None
        level = resolve_customer_level(db, to_str(row.get(m.get("level", ""))), cfg.get("level_code_map", {})) if m.get("level") else None
        owner_name = to_str(row.get(m.get("owner", "")))
        owner = db.query(User).filter_by(name=owner_name).first() if owner_name else None
        cust, created = get_or_create(
            db, Customer,
            defaults={
                "credit_code": credit,
                "address": to_str(row.get(m.get("address", ""))),
                "region_id": region.id if region else None,
                "channel_type_id": channel.id if channel else None,
                "level_id": level.id if level else None,
                "owner_id": owner.id if owner else None,
                "customer_type": "dealer",
                "phone": to_str(row.get(m.get("phone", ""))),
                "wechat": to_str(row.get(m.get("wechat", ""))),
                "source": to_str(row.get(m.get("source", ""))),
                "store_count": to_int(row.get(m.get("store_count", ""))),
                "table_count": to_int(row.get(m.get("table_count", ""))),
                "monthly_consumption": to_float(row.get(m.get("monthly_consumption", ""))),
                "current_competitor": to_str(row.get(m.get("current_competitor", ""))),
                "delivery_method": to_str(row.get(m.get("delivery_method", ""))),
                "payment_term": to_str(row.get(m.get("payment_term", ""))),
                "credit_limit": to_float(row.get(m.get("credit_limit", ""))),
                "remark": to_str(row.get(m.get("remark", ""))),
                "status": 1,
            },
            name=name,
        )
        if created:
            stats["customer_created"] += 1
        else:
            stats["customer_updated"] += 1
        # 主联系人
        cname = to_str(row.get(m.get("contact_name", "")))
        cphone = to_str(row.get(m.get("contact_phone", "")))
        if (cname or cphone) and cust.id:
            get_or_create(
                db, Contact,
                defaults={
                    "phone": cphone,
                    "title": to_str(row.get(m.get("contact_title", ""))),
                    "is_primary": True,
                },
                customer_id=cust.id, name=(cname or "联系人"),
            )
            stats["contact_created"] += 1
        if not dry_run:
            db.commit()
        else:
            db.rollback()


def find_or_create_category(db, l1, l2, l3, stats):
    """三级产品分类 find-or-create，返回最末级 category id 与名称。"""
    if not l3 and not l2 and not l1:
        return None, ""
    cur_parent = None
    last = None
    last_name = ""
    for lvl, nm in enumerate([l1, l2, l3], start=1):
        if not nm:
            break
        inst, created = get_or_create(db, ProductCategory, defaults={"parent_id": cur_parent, "sort": lvl}, name=nm, parent_id=cur_parent)
        if created:
            stats["category_created"] += 1
        cur_parent = inst.id
        last = inst
        last_name = nm
    return (last.id if last else None), last_name


def import_product(client, db, cfg, dry_run, stats):
    m = cfg.get("field_map", {}).get("product", {})
    fu = cfg["forms"].get("product")
    if not fu:
        print("[product] 未在 config.forms.product 配置 formUuid，跳过。")
        return
    rows = client.fetch_instances(fu)
    stats["product_total"] = len(rows)
    for row in rows:
        code = to_str(row.get(m.get("code", "code")))
        name = to_str(row.get(m.get("name", "name")))
        if not (code or name):
            continue
        l1 = to_str(row.get(m.get("cat_l1", "")))
        l2 = to_str(row.get(m.get("cat_l2", "")))
        l3 = to_str(row.get(m.get("cat_l3", "")))
        cat_id, cat_name = find_or_create_category(db, l1, l2, l3, stats)
        prod, created = get_or_create(
            db, Product,
            defaults={
                "name": name,
                "category_id": cat_id,
                "category": cat_name or to_str(row.get(m.get("category", ""))),
                "spec": to_str(row.get(m.get("spec", ""))),
                "unit": to_str(row.get(m.get("unit", ""))),
                "barcode": to_str(row.get(m.get("barcode", ""))),
                "factory_price": to_float(row.get(m.get("factory_price", ""))),
                "supply_price": to_float(row.get(m.get("supply_price", ""))),
                "retail_price": to_float(row.get(m.get("retail_price", ""))),
                "cost": to_float(row.get(m.get("cost", ""))),
                "shelf_life": to_int(row.get(m.get("shelf_life", ""))),
                "status": 1,
                "description": build_desc(row, m.get("description_fields", [])) or to_str(row.get(m.get("description", ""))),
            },
            code=(code or name),
        )
        if created:
            stats["product_created"] += 1
        else:
            stats["product_updated"] += 1
        if not dry_run:
            db.commit()
        else:
            db.rollback()


# ------------------------- 主流程 -------------------------
def backup_db(app_dir):
    src = os.path.join(app_dir, "crm.db")
    if not os.path.exists(src):
        return None
    dst = os.path.join(app_dir, "crm.db.bak.%s" % datetime.now().strftime("%Y%m%d%H%M%S"))
    with open(src, "rb") as f:
        data = f.read()
    with open(dst, "wb") as f:
        f.write(data)
    return dst


def main():
    ap = argparse.ArgumentParser(description="宜搭 -> 公司CRM 数据导入工具")
    ap.add_argument("--config", default=os.path.join(SCRIPT_DIR, "config.json"), help="配置文件路径")
    ap.add_argument("--app-dir", default=None, help="crm.db 所在 app 目录（默认自动探测）")
    ap.add_argument("--modules", default="org,customer,product", help="要导入的模块，逗号分隔")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写入")
    ap.add_argument("--discover-forms", action="store_true", help="列出应用内所有宜搭表单")
    ap.add_argument("--discover-fields", metavar="FORM_UUID", help="打印某表单第一条实例的字段键")
    ap.add_argument("--no-backup", action="store_true", help="跳过自动备份（不建议）")
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    app_dir = find_app_dir(args.app_dir)
    # 关键：切到 crm.db 所在目录，使相对数据库 URL sqlite:///./crm.db 正确解析
    os.chdir(app_dir)
    backend_dir = os.path.dirname(app_dir)
    # 同时把 app_dir 与父目录加入 sys.path，兼容「crm.db 在 backend/」与「在 backend/app/」两种布局
    for p in (app_dir, backend_dir):
        if p and p not in sys.path:
            sys.path.insert(0, p)

    client = YiDaClient(cfg)

    if args.discover_forms:
        print("== 应用内宜搭表单列表 ==")
        print(json.dumps(client.list_forms(), ensure_ascii=False, indent=2))
        return
    if args.discover_fields:
        print("== 表单 %s 第一条实例字段键 ==" % args.discover_fields)
        fd = client.discover_fields(args.discover_fields)
        for k in sorted(fd.keys()):
            print("  %s = %s" % (k, json.dumps(gv(fd[k]), ensure_ascii=False)[:80]))
        return

    # 以下为真实写入阶段，才需要后端模型与数据库
    if not args.dry_run and not args.no_backup:
        bk = backup_db(app_dir)
        print("已备份数据库：%s" % bk)

    # 延迟导入后端模块（需要 venv 依赖）
    global User, Region, ChannelType, CustomerLevel, Customer, Contact, Product, ProductCategory
    from app.models import (User, Region, ChannelType, CustomerLevel,
                            Customer, Contact, Product, ProductCategory)
    from app.database import SessionLocal

    db = SessionLocal()
    stats = {"org_total": 0, "org_created": 0, "org_updated": 0,
             "customer_total": 0, "customer_created": 0, "customer_updated": 0, "contact_created": 0,
             "product_total": 0, "product_created": 0, "product_updated": 0, "category_created": 0}
    mods = [x.strip() for x in args.modules.split(",") if x.strip()]
    for mod in mods:
        try:
            if mod == "org":
                import_org(client, db, cfg, args.dry_run, stats)
            elif mod == "customer":
                import_customer(client, db, cfg, args.dry_run, stats)
            elif mod == "product":
                import_product(client, db, cfg, args.dry_run, stats)
            else:
                print("!! 未知模块 %s，跳过" % mod)
        except Exception as e:
            db.rollback()
            print("!! 模块 [%s] 导入失败：%s" % (mod, e))
    if not args.dry_run:
        db.commit()
    db.close()

    print("\n==== 导入结果（%s）====" % ("干跑预览" if args.dry_run else "已写入"))
    for k, v in stats.items():
        print("  %-20s %s" % (k, v))


if __name__ == "__main__":
    main()
