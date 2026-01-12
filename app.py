# app.py
from flask import Flask, request, jsonify, render_template, send_file
from scheduler import generate_day, generate_period, EMPLOYEES
from datetime import datetime

import io
from openpyxl import Workbook

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html", employees=EMPLOYEES)


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


# -----------------------------
# 第一階段：多日自動排班（只排非 manual / 非停爐）
# 前端送：
# {
#   "days":[
#     {"date":"2026-01-01","manual":false,"no_burn":false,"vacations":["子紘","紀龍"]},
#     {"date":"2026-01-02","manual":true,"no_burn":false,"vacations":[]},
#     {"date":"2026-01-03","manual":false,"no_burn":true,"vacations":[]}
#   ]
# }
# -----------------------------
@app.route("/api/schedule_range", methods=["POST"])
def api_schedule_range():
    data = request.get_json()
    days = data.get("days", [])

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

        weekday = dt.weekday()  # Monday=0 ... Sunday=6
        manual = bool(day.get("manual", False))
        no_burn = bool(day.get("no_burn", False))

        vacations = day.get("vacations", []) or []
        vacations = [v for v in vacations if v in EMPLOYEES]

        # auto day：員工 = 全員 - 休假
        # manual/no_burn：第一階段不排，employees 可不帶或留空
        if (not manual) and (not no_burn):
            emps = [e for e in EMPLOYEES if e not in vacations]
        else:
            emps = []

        days_info.append({
            "date": date_str,
            "weekday": weekday,
            "manual": manual,
            "no_burn": no_burn,
            "vacations": vacations,
            "employees": emps,
        })

    schedule = generate_period(days_info)

    result = []
    for idx, assign in enumerate(schedule):
        meta = days_info[idx]
        result.append({
            "day_index": idx + 1,
            "date": meta["date"],
            "manual": bool(meta["manual"]),
            "no_burn": bool(meta["no_burn"]),
            "vacations": meta.get("vacations", []),
            "assignment": assign,
        })

    return jsonify({"schedule": result})


# -----------------------------
# 第二階段：合併手動排班
# 前端送：
# {
#   "auto_schedule":[ ...第一階段回傳的 schedule... ],
#   "manual_assignments":[
#     {"date":"2026-01-02","assignment":{"豐杰":"A","在慶":"C","子紘":"","奕忠":"E",...}}
#   ]
# }
# 規則：手動 assignment 裡，空字串/None/"休假" 代表不排（=休假）
# -----------------------------
@app.route("/api/merge_manual", methods=["POST"])
def api_merge_manual():
    data = request.get_json()
    auto_schedule = data.get("auto_schedule", []) or []
    manual_assignments = data.get("manual_assignments", []) or []

    manual_map = {}
    for item in manual_assignments:
        d = item.get("date")
        a = item.get("assignment", {}) or {}
        if not d:
            continue
        # 清理：只保留有效員工 + 有效角色
        cleaned = {}
        for name, role in a.items():
            if name not in EMPLOYEES:
                continue
            if role is None:
                continue
            role = str(role).strip()
            if role == "" or role == "休假":
                continue
            # 允許 A/B/C/D/E
            if role in ("A", "B", "C", "D", "E"):
                cleaned[name] = role
        manual_map[d] = cleaned

    merged = []
    for day in auto_schedule:
        date_str = day.get("date", "")
        manual = bool(day.get("manual", False))
        no_burn = bool(day.get("no_burn", False))

        assignment = day.get("assignment", {}) or {}

        if no_burn:
            assignment = {}
        elif manual:
            assignment = manual_map.get(date_str, {})

        merged.append({
            "day_index": day.get("day_index"),
            "date": date_str,
            "manual": manual,
            "no_burn": no_burn,
            "vacations": day.get("vacations", []),
            "assignment": assignment,
        })

    return jsonify({"schedule": merged})


# -----------------------------
# 匯出 Excel API（吃「最終 schedule」）
# -----------------------------
@app.route("/api/export_excel", methods=["POST"])
def export_excel():
    data = request.get_json()
    schedule = data.get("schedule", [])
    start_date = data.get("start_date", "")
    end_date = data.get("end_date", "")

    wb = Workbook()
    ws = wb.active
    ws.title = "Schedule"

    row = 1
    for day in schedule:
        day_index = day.get("day_index")
        date_str = day.get("date", "")
        assignment = day.get("assignment", {}) or {}
        manual = bool(day.get("manual", False))
        no_burn = bool(day.get("no_burn", False))

        tag = ""
        if no_burn:
            tag = "（停爐）"
        elif manual:
            tag = "（手動）"

        if date_str:
            ws.cell(row=row, column=1, value=f"Day {day_index}  ({date_str}){tag}")
        else:
            ws.cell(row=row, column=1, value=f"Day {day_index}{tag}")
        row += 1

        if not assignment:
            ws.cell(row=row, column=1, value="（無排班）")
            row += 2
            continue

        for name in sorted(assignment.keys()):
            role = assignment[name]
            ws.cell(row=row, column=1, value=f"{name}：{role}")
            row += 1

        row += 1  # 空一行

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
