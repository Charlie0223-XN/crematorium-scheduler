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


# ---------------------------------------------------------
# 一次性產生「最終班表」API（新流程）
# 前端送：
# {
#   "days":[
#     {"date":"2026-01-01","manual":false,"no_burn":false,"vacations":["子紘","紀龍"]},
#     {"date":"2026-01-02","manual":true,"no_burn":false,"vacations":[]},
#     {"date":"2026-01-03","manual":false,"no_burn":true,"vacations":[]}
#   ],
#   "manual_assignments":[
#     {"date":"2026-01-02","assignment":{"豐杰":"A","子紘":"","學林":"休假","在慶":"C","奕忠":"E",...}}
#   ]
# }
#
# manual_assignments 規則：
# - "" (空字串) 代表「交給系統自動」
# - "休假" 代表此人當天不排（視為休假）
# - "A/B/C/D/E" 代表你指定
# ---------------------------------------------------------
@app.route("/api/generate_final", methods=["POST"])
def api_generate_final():
    data = request.get_json()
    days = data.get("days", []) or []
    manual_assignments = data.get("manual_assignments", []) or []

    if not days:
        return jsonify({"error": "至少要提供一天的資料"}), 400

    # 轉 manual_assignments -> map
    manual_map = {}
    for item in manual_assignments:
        d = item.get("date")
        a = item.get("assignment", {}) or {}
        if not d:
            continue

        cleaned = {}
        for name, role in a.items():
            if name not in EMPLOYEES:
                continue
            if role is None:
                continue
            role = str(role).strip()
            if role == "":
                # 空字串：交給系統
                continue
            if role == "休假":
                cleaned[name] = "休假"
                continue
            if role in ("A", "B", "C", "D", "E"):
                cleaned[name] = role
        manual_map[d] = cleaned

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

        fixed = {}
        manual_vac = []

        if manual and (not no_burn):
            picked = manual_map.get(date_str, {}) or {}
            for name, role in picked.items():
                if role == "休假":
                    manual_vac.append(name)
                else:
                    fixed[name] = role

        # 這一天真正休假 = UI 勾休假（只在非手動日會有） + 手動下拉選休假
        all_vac = set(vacations) | set(manual_vac)

        if no_burn:
            emps = []
        else:
            emps = [e for e in EMPLOYEES if e not in all_vac]

        days_info.append(
            {
                "date": date_str,
                "weekday": weekday,
                "manual": manual,
                "no_burn": no_burn,
                "vacations": sorted(list(all_vac), key=lambda x: EMPLOYEES.index(x)),
                "employees": emps,
                "fixed": fixed,
            }
        )

    schedule = generate_period(days_info)

    result = []
    for idx, assign in enumerate(schedule):
        meta = days_info[idx]
        result.append(
            {
                "day_index": idx + 1,
                "date": meta["date"],
                "manual": bool(meta["manual"]),
                "no_burn": bool(meta["no_burn"]),
                "vacations": meta.get("vacations", []),
                "assignment": assign,
            }
        )

    return jsonify({"schedule": result})


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
            tag = "（手動含補排）"

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
