"""新廠四週排班核心。

排班規則：
- 一般日／大日：2 名 A、2 名 C，其餘出勤者為 B。
- 自訂日：依使用者輸入的 A／B／C 人數排班，其餘可上班者標為未排。
- 停爐日：不排班。
- 休假、停爐、未排都會中斷連續 B。
"""
from __future__ import annotations

import json
import os
import random
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


_config_path = os.path.join(os.path.dirname(__file__), "employees.json")
with open(_config_path, encoding="utf-8") as _f:
    _config = json.load(_f)

EMPLOYEES: List[str] = list(_config["employees"])
EMPLOYEE_ROWS: List[List[str]] = [list(row) for row in _config.get("employee_rows", [EMPLOYEES])]
ROLES: Tuple[str, ...] = ("A", "B", "C")
DAY_TYPES: Tuple[str, ...] = ("NORMAL", "BIG", "OFF", "CUSTOM")
RESTRICTED_ROLES: Dict[str, List[str]] = {
    name: list(roles) for name, roles in _config.get("restricted_roles", {}).items()
}
ROLE_PREFERENCES: Dict[str, Dict[str, float]] = {
    name: {role: float(weight) for role, weight in preferences.items()}
    for name, preferences in _config.get("role_preferences", {}).items()
}

MIN_VACATION_DAYS = 8
PERIOD_DAYS = 28


class ScheduleError(ValueError):
    """輸入資料無法產生符合硬性規則的班表。"""


def allowed_roles(name: str) -> Tuple[str, ...]:
    configured = RESTRICTED_ROLES.get(name)
    if configured is None:
        return ROLES
    return tuple(role for role in configured if role in ROLES)


def _requirements_for_day(day: Mapping[str, Any], available_count: int) -> Dict[str, int]:
    day_type = str(day.get("day_type", "NORMAL")).upper()

    if day_type == "OFF":
        return {role: 0 for role in ROLES}

    if day_type == "CUSTOM":
        raw = day.get("requirements") or {}
        requirements: Dict[str, int] = {}
        for role in ROLES:
            value = raw.get(role, 0)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ScheduleError(f"自訂日的 {role} 人數必須是 0 以上整數")
            requirements[role] = value
        if sum(requirements.values()) > available_count:
            raise ScheduleError(
                f"自訂需求共 {sum(requirements.values())} 人，但當天只有 {available_count} 人可排班"
            )
        return requirements

    # 一般／大日固定為 AA、CC，其餘 B；極端低人數時自然縮減，避免輸入使系統崩潰。
    a_count = min(2, available_count)
    c_count = min(2, max(0, available_count - a_count))
    b_count = max(0, available_count - a_count - c_count)
    return {"A": a_count, "B": b_count, "C": c_count}


def _option_score(
    *,
    name: str,
    role: str,
    day_type: str,
    prev_assignment: Mapping[str, str],
    role_counts: Mapping[str, Mapping[str, int]],
    role_opportunities: Mapping[str, Mapping[str, int]],
    assigned_counts: Mapping[str, int],
    availability_counts: Mapping[str, int],
    custom_day: bool,
    tie_noise: float,
) -> float:
    """分數越高越適合把 role 分給 name。"""
    opportunity = max(1, role_opportunities[name][role])
    role_rate_after = (role_counts[name][role] + 1) / opportunity
    score = -4.0 * role_rate_after

    # 自訂日可能只需要少數留守人員，額外平衡誰被選中。
    if custom_day:
        availability = max(1, availability_counts[name])
        workload_rate_after = (assigned_counts[name] + 1) / availability
        score -= 2.5 * workload_rate_after

    score += ROLE_PREFERENCES.get(name, {}).get(role, 0.0)

    # 昨日 B：今天優先 A、其次 C；若排不開仍可連續 B。
    if prev_assignment.get(name) == "B":
        big_multiplier = 1.8 if day_type == "BIG" else 1.0
        if role == "A":
            score += 5.0 * big_multiplier
        elif role == "C":
            score += 3.0 * big_multiplier
        elif role == "B":
            score -= 6.0 * big_multiplier

    # seed 只擾動相近候選，不足以推翻硬限制和主要權重。
    score += tie_noise
    return score


def _assign_day(
    *,
    day: Mapping[str, Any],
    available: Sequence[str],
    requirements: Mapping[str, int],
    prev_assignment: Mapping[str, str],
    role_counts: Mapping[str, Mapping[str, int]],
    role_opportunities: Mapping[str, Mapping[str, int]],
    assigned_counts: Mapping[str, int],
    availability_counts: Mapping[str, int],
    rng: random.Random,
) -> Dict[str, str]:
    """以動態規劃找出當日最高分配置，同時滿足各角色精確人數。"""
    target = tuple(int(requirements[role]) for role in ROLES)
    required_total = sum(target)
    if required_total == 0:
        return {}
    if required_total > len(available):
        raise ScheduleError("當日需求人數超過可排班人數")

    custom_day = str(day.get("day_type", "NORMAL")).upper() == "CUSTOM"
    may_leave_unassigned = required_total < len(available)
    noise = {
        (name, role): rng.uniform(-0.18, 0.18)
        for name in available
        for role in (*ROLES, "UNASSIGNED")
    }

    # state: (A 已排, B 已排, C 已排) -> (score, assignment)
    states: Dict[Tuple[int, int, int], Tuple[float, Dict[str, str]]] = {
        (0, 0, 0): (0.0, {})
    }

    for name in available:
        next_states: Dict[Tuple[int, int, int], Tuple[float, Dict[str, str]]] = {}
        choices: List[Optional[str]] = list(allowed_roles(name))
        if may_leave_unassigned:
            choices.append(None)

        for counts, (base_score, assignment) in states.items():
            for role in choices:
                if role is None:
                    new_counts = counts
                    option_score = noise[(name, "UNASSIGNED")]
                    new_assignment = assignment
                else:
                    role_index = ROLES.index(role)
                    if counts[role_index] >= target[role_index]:
                        continue
                    mutable_counts = list(counts)
                    mutable_counts[role_index] += 1
                    new_counts = tuple(mutable_counts)
                    option_score = _option_score(
                        name=name,
                        role=role,
                        day_type=str(day.get("day_type", "NORMAL")).upper(),
                        prev_assignment=prev_assignment,
                        role_counts=role_counts,
                        role_opportunities=role_opportunities,
                        assigned_counts=assigned_counts,
                        availability_counts=availability_counts,
                        custom_day=custom_day,
                        tie_noise=noise[(name, role)],
                    )
                    new_assignment = dict(assignment)
                    new_assignment[name] = role

                new_score = base_score + option_score
                current_best = next_states.get(new_counts)
                if current_best is None or new_score > current_best[0]:
                    next_states[new_counts] = (new_score, new_assignment)

        states = next_states

    best = states.get(target)
    if best is None:
        date_label = day.get("date", "該日")
        needs = "、".join(f"{role}{requirements[role]}" for role in ROLES)
        raise ScheduleError(f"{date_label} 無法滿足角色需求（{needs}），請檢查休假或自訂人數")
    return best[1]


def calculate_stats(
    schedule: Sequence[Mapping[str, Any]],
    vacations: Mapping[str, Iterable[str]],
) -> Dict[str, Any]:
    vacation_sets: Dict[str, Set[str]] = {
        name: set(vacations.get(name, [])) for name in EMPLOYEES
    }
    employee_stats: Dict[str, Dict[str, Any]] = {}
    streaks = {name: 0 for name in EMPLOYEES}

    for name in EMPLOYEES:
        employee_stats[name] = {
            "name": name,
            "vacation_days": 0,
            "available_days": 0,
            "assigned_days": 0,
            "unassigned_days": 0,
            "role_counts": {role: 0 for role in ROLES},
            "consecutive_b_occurrences": 0,
            "longest_b_streak": 0,
            "ending_b_streak": 0,
            "allowed_roles": list(allowed_roles(name)),
        }

    working_days = big_days = custom_days = off_days = 0
    for day in schedule:
        date_str = str(day["date"])
        day_type = str(day.get("day_type", "NORMAL"))
        assignment = day.get("assignment", {}) or {}

        if day_type == "OFF":
            off_days += 1
            for name in EMPLOYEES:
                streaks[name] = 0
            continue

        working_days += 1
        big_days += int(day_type == "BIG")
        custom_days += int(day_type == "CUSTOM")

        for name in EMPLOYEES:
            stat = employee_stats[name]
            if date_str in vacation_sets[name]:
                stat["vacation_days"] += 1
                streaks[name] = 0
                continue

            stat["available_days"] += 1
            role = assignment.get(name)
            if role not in ROLES:
                stat["unassigned_days"] += 1
                streaks[name] = 0
                continue

            stat["assigned_days"] += 1
            stat["role_counts"][role] += 1
            if role == "B":
                if streaks[name] >= 1:
                    stat["consecutive_b_occurrences"] += 1
                streaks[name] += 1
                stat["longest_b_streak"] = max(stat["longest_b_streak"], streaks[name])
            else:
                streaks[name] = 0

    for name in EMPLOYEES:
        stat = employee_stats[name]
        assigned = stat["assigned_days"]
        stat["ending_b_streak"] = streaks[name]
        stat["role_percentages"] = {
            role: round(stat["role_counts"][role] / assigned, 4) if assigned else 0.0
            for role in ROLES
        }

    role_balance: Dict[str, Dict[str, float]] = {}
    for role in ROLES:
        rates: List[float] = []
        for name in EMPLOYEES:
            stat = employee_stats[name]
            if role not in stat["allowed_roles"] or stat["available_days"] == 0:
                continue
            rates.append(stat["role_counts"][role] / stat["available_days"])

        minimum = min(rates, default=0.0)
        maximum = max(rates, default=0.0)
        spread = maximum - minimum
        role_balance[role] = {
            "min_rate": round(minimum, 4),
            "max_rate": round(maximum, 4),
            "spread": round(spread, 4),
            "score": round(max(0.0, 100.0 * (1.0 - spread)), 1),
        }

    overall_score = round(
        sum(item["score"] for item in role_balance.values()) / len(ROLES), 1
    )
    return {
        "period_days": len(schedule),
        "working_days": working_days,
        "off_days": off_days,
        "big_days": big_days,
        "custom_days": custom_days,
        "employees": [employee_stats[name] for name in EMPLOYEES],
        "balance": {
            "overall_score": overall_score,
            "roles": role_balance,
        },
    }


def generate_period(
    days_info: Sequence[Mapping[str, Any]],
    vacations: Mapping[str, Iterable[str]],
    seed: int = 0,
) -> Dict[str, Any]:
    vacation_sets: Dict[str, Set[str]] = {
        name: set(vacations.get(name, [])) for name in EMPLOYEES
    }
    rng = random.Random(int(seed))

    role_counts = {name: {role: 0 for role in ROLES} for name in EMPLOYEES}
    role_opportunities = {name: {role: 0 for role in ROLES} for name in EMPLOYEES}
    assigned_counts = {name: 0 for name in EMPLOYEES}
    availability_counts = {name: 0 for name in EMPLOYEES}
    prev_assignment: Dict[str, str] = {}
    schedule: List[Dict[str, Any]] = []

    for index, raw_day in enumerate(days_info, 1):
        day = dict(raw_day)
        date_str = str(day["date"])
        day_type = str(day.get("day_type", "NORMAL")).upper()
        if day_type not in DAY_TYPES:
            raise ScheduleError(f"{date_str} 的日期類型不合法")

        vacation_names = [name for name in EMPLOYEES if date_str in vacation_sets[name]]
        available = [name for name in EMPLOYEES if name not in vacation_names]

        if day_type == "OFF":
            requirements = {role: 0 for role in ROLES}
            assignment: Dict[str, str] = {}
            vacation_names = []
            available = []
            unassigned: List[str] = []
            prev_assignment = {}
        else:
            requirements = _requirements_for_day(day, len(available))
            for name in available:
                availability_counts[name] += 1
                for role in allowed_roles(name):
                    if requirements.get(role, 0) > 0:
                        role_opportunities[name][role] += 1

            assignment = _assign_day(
                day=day,
                available=available,
                requirements=requirements,
                prev_assignment=prev_assignment,
                role_counts=role_counts,
                role_opportunities=role_opportunities,
                assigned_counts=assigned_counts,
                availability_counts=availability_counts,
                rng=rng,
            )
            unassigned = [name for name in available if name not in assignment]

            for name, role in assignment.items():
                role_counts[name][role] += 1
                assigned_counts[name] += 1
            # 未排、休假都不帶入前一天角色，因此會中斷連續 B。
            prev_assignment = dict(assignment)

        try:
            weekday = datetime.strptime(date_str, "%Y-%m-%d").weekday()
        except ValueError:
            weekday = day.get("weekday")

        schedule.append({
            "day_index": index,
            "date": date_str,
            "weekday": weekday,
            "day_type": day_type,
            "label": str(day.get("label", "")).strip(),
            "requirements": requirements,
            "assignment": assignment,
            "vacations": vacation_names,
            "unassigned": unassigned,
        })

    return {
        "seed": int(seed),
        "schedule": schedule,
        "stats": calculate_stats(schedule, vacation_sets),
    }
