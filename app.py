# app.py
from flask import Flask, request, jsonify, render_template, send_file
from scheduler import generate_day, generate_period, EMPLOYEES, FIXED_ROLES, RESTRICTED_ROLES
from datetime import datetime

import io
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

app = Flask(__name__)

ROLES = ["A", "B", "C", "D", "E"]
_WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]


@app.route("/")
def index():
    return render_template(
        "index.html",
        employees=EMPLOYEES,
        fixed_roles=FIXED_ROLES,
        restricted_roles=RESTRICTED_ROLES,
    )


# -----------------------------
# 單日排班 API（保留測試用）
# -----------------------------
@app.route("/api/schedule", methods=["POST"])
def api_schedule():
    data = request.get_json()
    employees = data.get("employees", [])
    prev_day = data.get("prev_day", {})

    if not employees:
        return jsonify({"error": "請至少選一個上班人員"}), 400

    assignment, score = generate_day(employees, prev_day)
    return jsonify({"assignment": assignment, "score": score})


# ---------------------------------------------------------
# 產生最終班表 API（DAY_CONTRACT v1）
#
# 請求格式：
# {
#   "days": [
#     {
#       "date": "2026-01-01",
#       "employees_mode": "WORK",   // "WORK" | "OFF"
#       "mode": "AUTO",             // "AUTO" | "MANUAL"
#       "employees": ["豐杰", ...], // AUTO 時：當天上班人員（已扣除休假）
#       "manual_assignment": null   // MANUAL 時：{name: role}，其餘人不出班
#     }
#   ]
# }
# ---------------------------------------------------------
@app.route("/api/generate_final", methods=["POST"])
def api_generate_final():
    data = request.get_json()
    days = data.get("days", []) or []

    if not days:
        return jsonify({"error": "至少要提供一天的資料"}), 400

    days_info = []
    for day in days:
        date_str = day.get("date")
        if not date_str:
            return jsonify({"error": "缺少日期資訊"}), 400

        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": f"日期格式錯誤：{date_str}"}), 400

        weekday = dt.weekday()
        employees_mode = day.get("employees_mode", "WORK")
        mode = day.get("mode", "AUTO")

        # 停爐（OFF）：最高優先
        if employees_mode == "OFF":
            days_info.append({
                "date": date_str,
                "weekday": weekday,
                "mode": "OFF",
                "employees": [],
                "fixed": {},
            })
            continue

        # 手動（MANUAL）：局部指定 + scheduler 補排
        # ""（交給系統自動）、"休假"、A-E 三種值
        if mode == "MANUAL":
            raw = day.get("manual_assignment") or {}
            manual_vacations = []
            fixed = {}

            for name, role in raw.items():
                if name not in EMPLOYEES:
                    continue
                role = str(role).strip()
                if role == "休假":
                    manual_vacations.append(name)
                elif role in ROLES:
                    fixed[name] = role
                # 空字串 = 交給系統自動，不加入 fixed

            employees = [e for e in EMPLOYEES if e not in manual_vacations]
            days_info.append({
                "date": date_str,
                "weekday": weekday,
                "mode": "MANUAL",
                "employees": employees,
                "fixed": fixed,
            })
            continue

        # 自動（AUTO）
        employees = [e for e in (day.get("employees", []) or []) if e in EMPLOYEES]
        days_info.append({
            "date": date_str,
            "weekday": weekday,
            "mode": "AUTO",
            "employees": employees,
            "fixed": {},
        })

    schedule = generate_period(days_info)

    result = []
    for idx, assign in enumerate(schedule):
        meta = days_info[idx]
        is_off = meta["mode"] == "OFF"
        vacations = (
            []
            if is_off
            else sorted(
                [e for e in EMPLOYEES if e not in assign],
                key=lambda x: EMPLOYEES.index(x),
            )
        )
        result.append({
            "day_index": idx + 1,
            "date": meta["date"],
            "employees_mode": "OFF" if is_off else "WORK",
            "mode": "AUTO" if is_off else meta["mode"],
            "vacations": vacations,
            "assignment": assign,
        })

    return jsonify({"schedule": result})


# -----------------------------
# 匯出 Excel API（表格格式）
# -----------------------------
@app.route("/api/export_excel", methods=["POST"])
def export_excel():
    data = request.get_json()
    schedule = data.get("schedule", [])
    start_date = data.get("start_date", "")
    end_date = data.get("end_date", "")

    wb = Workbook()
    ws = wb.active
    ws.title = "排班表"

    header_fill = PatternFill(fill_type="solid", fgColor="DDEBF7")
    off_fill = PatternFill(fill_type="solid", fgColor="F2F2F2")
    manual_fill = PatternFill(fill_type="solid", fgColor="FFF2CC")
    bold = Font(bold=True)
    center = Alignment(horizontal="center")

    # ── 標題列 ──────────────────────────────────────────────
    header = ["日期", "週", "狀態"] + EMPLOYEES
    for col, val in enumerate(header, 1):
        cell = ws.cell(row=1, column=col, value=val)
        cell.font = bold
        cell.fill = header_fill
        cell.alignment = center

    # ── 資料列 ──────────────────────────────────────────────
    for row_idx, day in enumerate(schedule, 2):
        date_str = day.get("date", "")
        assignment = day.get("assignment", {}) or {}
        employees_mode = day.get("employees_mode", "WORK")
        mode = day.get("mode", "AUTO")
        is_off = employees_mode == "OFF"

        weekday_str = ""
        if date_str:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                weekday_str = _WEEKDAY_NAMES[dt.weekday()]
            except ValueError:
                pass

        if is_off:
            status = "停爐"
            row_fill = off_fill
        elif mode == "MANUAL":
            status = "手動"
            row_fill = manual_fill
        else:
            status = "自動"
            row_fill = None

        ws.cell(row=row_idx, column=1, value=date_str).alignment = center
        ws.cell(row=row_idx, column=2, value=f"週{weekday_str}").alignment = center
        ws.cell(row=row_idx, column=3, value=status).alignment = center

        for col_idx, name in enumerate(EMPLOYEES, 4):
            if is_off:
                role = ""
            else:
                role = assignment.get(name, "休假")
            cell = ws.cell(row=row_idx, column=col_idx, value=role)
            cell.alignment = center

        if row_fill:
            for col in range(1, len(header) + 1):
                ws.cell(row=row_idx, column=col).fill = row_fill

    # ── 欄寬 ────────────────────────────────────────────────
    ws.column_dimensions["A"].width = 13
    ws.column_dimensions["B"].width = 5
    ws.column_dimensions["C"].width = 6
    for col_idx in range(4, len(EMPLOYEES) + 4):
        col_letter = get_column_letter(col_idx)
        name = EMPLOYEES[col_idx - 4]
        ws.column_dimensions[col_letter].width = max(6, len(name) + 2)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = "schedule.xlsx"
    if start_date and end_date:
        filename = f"schedule_{start_date}_to_{end_date}.xlsx"

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    app.run(debug=True)
