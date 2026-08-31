"""火葬場新廠四週排班網站。"""
from __future__ import annotations

import io
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Mapping, Tuple

from flask import Flask, jsonify, render_template, request, send_file
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from scheduler import (
    DAY_TYPES,
    EMPLOYEES,
    EMPLOYEE_ROWS,
    MIN_VACATION_DAYS,
    PERIOD_DAYS,
    RESTRICTED_ROLES,
    ROLES,
    ROLE_PREFERENCES,
    ScheduleError,
    generate_period,
)


app = Flask(__name__)

WEEKDAY_NAMES = ("一", "二", "三", "四", "五", "六", "日")
DAY_TYPE_NAMES = {
    "NORMAL": "一般日",
    "BIG": "大日",
    "OFF": "停爐",
    "CUSTOM": "其他",
}


def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _normalize_requirements(raw: Any, date_str: str) -> Dict[str, int]:
    if not isinstance(raw, dict):
        raise ScheduleError(f"{date_str} 的自訂需求格式不正確")

    normalized: Dict[str, int] = {}
    for role in ROLES:
        value = raw.get(role, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ScheduleError(f"{date_str} 的 {role} 人數必須是 0 以上整數")
        normalized[role] = value
    return normalized


def _normalize_payload(data: Any) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]], int]:
    if not isinstance(data, dict):
        raise ScheduleError("請提供正確的 JSON 排班資料")

    raw_days = data.get("days")
    if not isinstance(raw_days, list) or len(raw_days) != PERIOD_DAYS:
        raise ScheduleError(f"每次排班必須包含完整 {PERIOD_DAYS} 天")

    normalized_days: List[Dict[str, Any]] = []
    parsed_dates = []
    seen_dates = set()
    for raw_day in raw_days:
        if not isinstance(raw_day, dict):
            raise ScheduleError("日期模板格式不正確")

        date_str = str(raw_day.get("date", "")).strip()
        try:
            parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ScheduleError(f"日期格式錯誤：{date_str or '空白'}") from exc
        if date_str in seen_dates:
            raise ScheduleError(f"日期重複：{date_str}")
        seen_dates.add(date_str)
        parsed_dates.append(parsed_date)

        day_type = str(raw_day.get("day_type", "NORMAL")).upper()
        if day_type not in DAY_TYPES:
            raise ScheduleError(f"{date_str} 的日期類型不合法")

        label = str(raw_day.get("label", "")).strip()
        if len(label) > 40:
            raise ScheduleError(f"{date_str} 的自訂名稱不可超過 40 個字")

        requirements = (
            _normalize_requirements(raw_day.get("requirements") or {}, date_str)
            if day_type == "CUSTOM"
            else {role: 0 for role in ROLES}
        )
        normalized_days.append({
            "date": date_str,
            "weekday": parsed_date.weekday(),
            "day_type": day_type,
            "label": label,
            "requirements": requirements,
        })

    for index in range(1, len(parsed_dates)):
        if parsed_dates[index] != parsed_dates[0] + timedelta(days=index):
            raise ScheduleError("日期模板必須是連續 28 天")

    raw_vacations = data.get("vacations")
    if not isinstance(raw_vacations, dict):
        raise ScheduleError("缺少人員休假資料")
    unknown_names = sorted(set(raw_vacations) - set(EMPLOYEES))
    if unknown_names:
        raise ScheduleError(f"休假資料包含未知人員：{'、'.join(unknown_names)}")

    off_dates = {
        day["date"] for day in normalized_days if day["day_type"] == "OFF"
    }
    normalized_vacations: Dict[str, List[str]] = {}
    for name in EMPLOYEES:
        raw_dates = raw_vacations.get(name)
        if not isinstance(raw_dates, list):
            raise ScheduleError(f"缺少{name}的休假資料")
        selected = {str(value) for value in raw_dates}
        invalid_dates = sorted(selected - seen_dates)
        if invalid_dates:
            raise ScheduleError(f"{name}的休假包含區間外日期：{'、'.join(invalid_dates)}")

        # 停爐不算個人休假，也不會傳入排班核心。
        selected -= off_dates
        if len(selected) < MIN_VACATION_DAYS:
            raise ScheduleError(
                f"{name}目前只有 {len(selected)} 天休假，至少需要 {MIN_VACATION_DAYS} 天"
            )
        normalized_vacations[name] = sorted(selected)

    raw_seed = data.get("seed")
    if raw_seed is None:
        seed = secrets.randbelow(2_147_483_647)
    elif isinstance(raw_seed, bool):
        raise ScheduleError("重新安排代碼格式不正確")
    else:
        try:
            seed = int(raw_seed)
        except (TypeError, ValueError) as exc:
            raise ScheduleError("重新安排代碼格式不正確") from exc

    return normalized_days, normalized_vacations, seed


def _generate_from_payload(data: Any) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]], Dict[str, Any]]:
    days, vacations, seed = _normalize_payload(data)
    result = generate_period(days, vacations, seed)
    return days, vacations, result


@app.route("/")
def index():
    return render_template(
        "index.html",
        employees=EMPLOYEES,
        employee_rows=EMPLOYEE_ROWS,
        restricted_roles=RESTRICTED_ROLES,
        role_preferences=ROLE_PREFERENCES,
        period_days=PERIOD_DAYS,
        min_vacation_days=MIN_VACATION_DAYS,
    )


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "version": 2})


@app.route("/api/generate_final", methods=["POST"])
def api_generate_final():
    try:
        _, _, result = _generate_from_payload(request.get_json(silent=True))
    except ScheduleError as exc:
        return _error(str(exc))
    return jsonify(result)


def _style_header(ws, row: int, values: List[str], fill: PatternFill) -> None:
    for column, value in enumerate(values, 1):
        cell = ws.cell(row=row, column=column, value=value)
        cell.font = Font(bold=True, color="24323D")
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _build_workbook(
    days: List[Dict[str, Any]],
    vacations: Mapping[str, List[str]],
    result: Mapping[str, Any],
) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "每日班表"

    header_fill = PatternFill("solid", fgColor="DCEAE6")
    normal_fill = PatternFill("solid", fgColor="FFFFFF")
    big_fill = PatternFill("solid", fgColor="FFF0D8")
    off_fill = PatternFill("solid", fgColor="E8EBED")
    custom_fill = PatternFill("solid", fgColor="ECE6F7")
    role_fills = {
        "A": PatternFill("solid", fgColor="F9D976"),
        "B": PatternFill("solid", fgColor="CFE4F7"),
        "C": PatternFill("solid", fgColor="CEE9D5"),
        "休假": PatternFill("solid", fgColor="F5D6D6"),
        "未排": PatternFill("solid", fgColor="F1F1F1"),
        "停爐": off_fill,
    }
    row_fills = {
        "NORMAL": normal_fill,
        "BIG": big_fill,
        "OFF": off_fill,
        "CUSTOM": custom_fill,
    }

    headers = ["日期", "週", "類型", "標記", "需求"] + EMPLOYEES
    _style_header(ws, 1, headers, header_fill)
    ws.freeze_panes = "F2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(result['schedule']) + 1}"

    for row_index, day in enumerate(result["schedule"], 2):
        day_type = day["day_type"]
        requirements = day["requirements"]
        requirement_text = " / ".join(f"{role}{requirements[role]}" for role in ROLES)
        values = [
            day["date"],
            f"週{WEEKDAY_NAMES[day['weekday']]}",
            DAY_TYPE_NAMES[day_type],
            day.get("label", ""),
            requirement_text,
        ]
        for column, value in enumerate(values, 1):
            cell = ws.cell(row=row_index, column=column, value=value)
            cell.fill = row_fills[day_type]
            cell.alignment = Alignment(horizontal="center", vertical="center")

        assignment = day.get("assignment", {}) or {}
        vacation_names = set(day.get("vacations", []))
        for employee_index, name in enumerate(EMPLOYEES, 6):
            if day_type == "OFF":
                value = "停爐"
            elif name in vacation_names:
                value = "休假"
            else:
                value = assignment.get(name, "未排")
            cell = ws.cell(row=row_index, column=employee_index, value=value)
            cell.fill = role_fills[value]
            cell.alignment = Alignment(horizontal="center", vertical="center")

    widths = [13, 6, 9, 16, 18] + [8] * len(EMPLOYEES)
    for column, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(column)].width = width
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row):
        for cell in row:
            cell.alignment = Alignment(horizontal="center", vertical="center")

    stats_ws = wb.create_sheet("人員統計")
    stats_ws["A1"] = "整體均衡分數"
    stats_ws["A1"].font = Font(bold=True)
    stats_ws["B1"] = result["stats"]["balance"]["overall_score"]
    stats_ws["C1"] = "滿分 100；依每人可排天數與允許角色比較"
    stats_headers = [
        "人員", "休假", "可排", "實排", "未排", "A", "B", "C",
        "A比例", "B比例", "C比例", "連B次數", "最長連B", "期末連B",
    ]
    _style_header(stats_ws, 3, stats_headers, header_fill)
    stats_ws.freeze_panes = "A4"

    for row_index, stat in enumerate(result["stats"]["employees"], 4):
        counts = stat["role_counts"]
        percentages = stat["role_percentages"]
        values = [
            stat["name"], stat["vacation_days"], stat["available_days"],
            stat["assigned_days"], stat["unassigned_days"],
            counts["A"], counts["B"], counts["C"],
            percentages["A"], percentages["B"], percentages["C"],
            stat["consecutive_b_occurrences"], stat["longest_b_streak"],
            stat["ending_b_streak"],
        ]
        for column, value in enumerate(values, 1):
            cell = stats_ws.cell(row=row_index, column=column, value=value)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            if column in (9, 10, 11):
                cell.number_format = "0.0%"

    for column in range(1, len(stats_headers) + 1):
        stats_ws.column_dimensions[get_column_letter(column)].width = 13 if column == 1 else 10

    vacation_ws = wb.create_sheet("休假設定")
    vacation_headers = ["人員", "休假天數", "休假日期"]
    _style_header(vacation_ws, 1, vacation_headers, header_fill)
    for row_index, name in enumerate(EMPLOYEES, 2):
        dates = vacations[name]
        vacation_ws.cell(row=row_index, column=1, value=name)
        vacation_ws.cell(row=row_index, column=2, value=len(dates))
        vacation_ws.cell(row=row_index, column=3, value="、".join(dates))
    vacation_ws.column_dimensions["A"].width = 12
    vacation_ws.column_dimensions["B"].width = 12
    vacation_ws.column_dimensions["C"].width = 80
    vacation_ws.freeze_panes = "A2"

    return wb


@app.route("/api/export_excel", methods=["POST"])
def export_excel():
    try:
        days, vacations, result = _generate_from_payload(request.get_json(silent=True))
    except ScheduleError as exc:
        return _error(str(exc))

    wb = _build_workbook(days, vacations, result)
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    start_date = days[0]["date"]
    end_date = days[-1]["date"]
    return send_file(
        output,
        as_attachment=True,
        download_name=f"schedule_{start_date}_to_{end_date}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    app.run(debug=True)
