#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从宜搭导出指定月份的「职能岗 / 营销岗月度任务令」，输出为 Excel。
- 两个 sheet 分别对应两张表单；外加「字段说明」sheet。
- 按 dateField_mhuo2qrf（毫秒时间戳）过滤目标月份。
- 字段标签接口不可用，任务项列用 fieldId 标识，身份字段尽量中文命名。
"""
import argparse
import json
import os
import sys
import datetime
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from yida_import import YiDaClient, gv, http_post_json  # 复用宜搭客户端与取值归一化

FORMS = [
    ("职能岗月度任务令", "FORM-90FDB1E041F44B229063438BAF4A2FEDY590",
     {"employeeField_muf396b4": "考核人"}),
    ("营销岗月度任务令", "FORM-7198D79F077B4D45BD221F7165F4E813EC13",
     {"employeeField_muknzjcn": "考核人"}),
]

# 通用身份字段 -> 中文列名（与具体表单无关）
COMMON_LABELS = {
    "dateField_mhuo2qrf": "月份",
    "departmentSelectField_mhrjjy88": "部门",
    "employeeField_mhrjjy87": "被考核人",
    "textField_mhrjjy89": "岗位",
    "numberField_mioelv8j": "考核总分(满分)",
    "numberField_mio0r9js": "考核总分(满分)",
}

TRACE_COLS = [
    ("formInstanceId", "实例ID"),
    ("createTimeGMT", "提交时间"),
    ("modifiedTimeGMT", "最后修改时间"),
    ("originator", "提交人"),
    ("title", "标题"),
]

DATE_BASE = "dateField_mhuo2qrf"  # 月份字段（毫秒时间戳）


def fmt_month(ms):
    if isinstance(ms, (int, float)):
        try:
            dt = datetime.datetime.fromtimestamp(ms / 1000)
            return "%d年%d月" % (dt.year, dt.month)
        except Exception:
            return str(ms)
    return ""


def fmt_gmt(s):
    if not s:
        return ""
    s = str(s)
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return s


def fmt_originator(v):
    if not v:
        return ""
    try:
        if isinstance(v, str):
            v = json.loads(v)
        return v.get("name", {}).get("nameInChinese") or v.get("name", {}).get("nameInEnglish") or ""
    except Exception:
        return str(v)


def fetch_full_rows(client, form_uuid, page_size=100):
    """分页拉取某表单全部实例（保留实例级字段：formInstanceId/createTime...）。"""
    token = client.get_token()
    out = []
    page = 1
    while True:
        body = {
            "appType": client.yida_app_type,
            "systemToken": client.yida_system_token,
            "userId": client.manager_user_id,
            "language": "zh_CN",
            "formUuid": form_uuid,
            "pageNumber": page,
            "pageSize": page_size,
            "modifiedFrom": client.cfg.get("modified_from", "2000-01-01 00:00:00"),
            "modifiedTo": client.cfg.get("modified_to", "2099-12-31 23:59:59"),
            "searchFieldJson": "{}",
        }
        r = http_post_json(client.instance_url, body, headers={client.auth_header: token})
        result = r.get("result") or r
        data = result.get("data") or []
        out.extend(data)
        if len(data) < page_size or not data:
            break
        page += 1
        if page > 200:
            break
    return out


def parse_month(ms):
    if isinstance(ms, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(ms / 1000)
        except Exception:
            return None
    return None


def base_field_ids(rows):
    """收集所有实例中出现的基础字段 id（去掉 _value / _id 后缀）。"""
    s = set()
    for r in rows:
        fd = r.get("formData") or {}
        for k in fd.keys():
            if k.endswith("_value") or k.endswith("_id"):
                s.add(k[:-len("_value" if k.endswith("_value") else "_id")])
            else:
                s.add(k)
    return s


def pick_value(fd, base):
    """优先取基础字段值，否则取 _value。"""
    if base in fd:
        return gv(fd[base])
    if (base + "_value") in fd:
        return gv(fd[base + "_value"])
    return ""


def label_of(base, form_specific):
    if base in COMMON_LABELS:
        return COMMON_LABELS[base]
    if base in form_specific:
        return form_specific[base]
    return base  # 任务项列：以 fieldId 标识


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"))
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--month", type=int, default=10)
    ap.add_argument("--out", default=None, help="输出 xlsx 路径")
    args = ap.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    client = YiDaClient(cfg)

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("缺少 openpyxl，请先安装：pip install openpyxl")
        return

    wb = Workbook()
    wb.remove(wb.active)

    # 字段说明 sheet 内容收集
    field_notes = OrderedDict()
    summary = []

    for label, fu, form_specific in FORMS:
        rows = fetch_full_rows(client, fu)
        month_rows = []
        for r in rows:
            fd = r.get("formData") or {}
            dt = parse_month(gv(fd.get("dateField_mhuo2qrf")))
            if dt and dt.year == args.year and dt.month == args.month:
                month_rows.append(r)
        summary.append((label, len(rows), len(month_rows)))

        # 列顺序：实例级追踪列 -> 通用身份字段 -> 其余基础字段（按出现顺序稳定排序）
        bases = base_field_ids(month_rows)
        id_fields = ["dateField_mhuo2qrf", "departmentSelectField_mhrjjy88",
                     "employeeField_mhrjjy87", "textField_mhrjjy89",
                     "employeeField_muf396b4", "employeeField_muknzjcn",
                     "numberField_mioelv8j", "numberField_mio0r9js"]
        ordered = [f for f in id_fields if f in bases]
        rest = sorted(b for b in bases if b not in ordered and b not in
                      ("dateField_mhuo2qrf", "departmentSelectField_mhrjjy88",
                       "employeeField_mhrjjy87", "textField_mhrjjy89",
                       "employeeField_muf396b4", "employeeField_muknzjcn",
                       "numberField_mioelv8j", "numberField_mio0r9js"))
        cols = [c[0] for c in TRACE_COLS] + ordered + rest
        headers = [c[1] for c in TRACE_COLS] + [label_of(b, form_specific) for b in ordered + rest]

        ws = wb.create_sheet(title=label[:31])
        ws.append(headers)
        for ci, _ in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=ci)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="4472C4")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for r in month_rows:
            fd = r.get("formData") or {}
            rowvals = []
            for tc, _ in TRACE_COLS:
                v = r.get(tc)
                if tc in ("createTimeGMT", "modifiedTimeGMT"):
                    rowvals.append(fmt_gmt(v))
                elif tc == "originator":
                    rowvals.append(fmt_originator(v))
                else:
                    rowvals.append("" if v is None else str(v))
            for b in ordered + rest:
                if b == DATE_BASE:
                    rowvals.append(fmt_month(gv(fd.get(b))))
                else:
                    rowvals.append(pick_value(fd, b))
            ws.append(rowvals)

        # 自适应列宽 + 长文本换行
        for ci, h in enumerate(headers, start=1):
            width = max(10, min(40, len(str(h)) + 2))
            for ri in range(2, ws.max_row + 1):
                v = ws.cell(row=ri, column=ci).value
                if v is not None:
                    width = max(width, min(50, len(str(v)) + 2))
            ws.column_dimensions[get_column_letter(ci)].width = width
            if ci > len(TRACE_COLS):  # 任务项文本列允许换行
                for ri in range(2, ws.max_row + 1):
                    ws.cell(row=ri, column=ci).alignment = Alignment(wrap_text=True, vertical="top")
        ws.freeze_panes = "A2"

        for b in ordered + rest:
            field_notes.setdefault(b, label_of(b, form_specific))

    # 字段说明 sheet
    ws_info = wb.create_sheet(title="字段说明")
    ws_info.append(["导出说明", ""])
    ws_info.append(["数据来源", "宜搭：职能岗月度任务令 / 营销岗月度任务令"])
    ws_info.append(["筛选条件", "%d年%d月（按 dateField_mhuo2qrf 月份）" % (args.year, args.month)])
    ws_info.append(["", ""])
    ws_info.append(["身份字段（已命名）", "说明"])
    for b, lb in field_notes.items():
        if lb != b:
            ws_info.append([lb, "fieldId: %s" % b])
    ws_info.append(["", ""])
    ws_info.append(["任务项列（fieldId）", "说明"])
    ws_info.append(["numberField_*", "各任务项得分/权重，对照宜搭表单设计中的组件标题理解"])
    ws_info.append(["textareaField_* / textField_*", "任务完成情况、考核评语等文本"])
    ws_info.append(["", ""])
    ws_info.append(["统计", ""])
    for label, total, m in summary:
        ws_info.append(["%s" % label, "实例总数 %d，%d年%d月 %d 条" % (total, args.year, args.month, m)])

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "..", "output",
                                   "月度任务令_%d%02d.xlsx" % (args.year, args.month))
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    wb.save(out)
    print("已导出：%s" % out)
    for label, total, m in summary:
        print("  %s: 实例总数 %d，%d年%d月 %d 条" % (label, total, args.year, args.month, m))


if __name__ == "__main__":
    main()
