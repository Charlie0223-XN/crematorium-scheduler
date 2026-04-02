# scheduler.py
from __future__ import annotations
import json
import os
from typing import List, Dict, Any, Tuple

# ── 載入員工設定 ──────────────────────────────────────────────
_config_path = os.path.join(os.path.dirname(__file__), "employees.json")
with open(_config_path, encoding="utf-8") as _f:
    _config = json.load(_f)

EMPLOYEES: List[str] = _config["employees"]
ROLES = ["A", "B", "C", "D", "E"]
FIXED_ROLES: Dict[str, str] = _config.get("fixed_roles", {})
# e.g. {"奕忠": "E", "井仁": "C", "俊瑋": "C"}
RESTRICTED_ROLES: Dict[str, List[str]] = _config.get("restricted_roles", {})
# e.g. {"在慶": ["B", "C", "D"]}


# ── 角色池生成 ────────────────────────────────────────────────
def _build_role_pool_for_day(employees: List[str]) -> Tuple[List[str], List[str]]:
    """產生當天 A/B/C/D 需求（固定E的員工不進池）"""
    base_staff = [e for e in employees if FIXED_ROLES.get(e) != "E"]
    n = len(base_staff)
    roles: List[str] = []

    if n <= 0:
        return roles, base_staff

    if n >= 5:
        roles = ["A", "B", "C", "C", "D"]
        extra = n - 5
        for _ in range(extra):
            if roles.count("B") < 2:
                roles.append("B")
            elif roles.count("D") < 2:
                roles.append("D")
            else:
                roles.append("C")
    else:
        mapping = {1: ["C"], 2: ["A", "C"], 3: ["A", "B", "C"], 4: ["A", "B", "C", "D"]}
        roles = mapping[n]

    return roles, base_staff


# ── 分數計算 ──────────────────────────────────────────────────
def _score_full_assignment(
    assignment: Dict[str, str],
    prev_assignment: Dict[str, str],
    role_counts: Dict[str, Dict[str, int]],
) -> float:
    score = 0.0
    w_role_balance = 0.5
    fatigue_B_bonus = 2.5
    fatigue_A_bonus = 1.5

    for name, role in assignment.items():
        score -= w_role_balance * role_counts[name].get(role, 0)

        prev_role = prev_assignment.get(name)
        if prev_role == "C":
            if role == "B":
                score += fatigue_B_bonus
            elif role == "A":
                score += fatigue_A_bonus

    return score


def _remove_one(roles: List[str], role: str) -> List[str]:
    if role in roles:
        idx = roles.index(role)
        return roles[:idx] + roles[idx + 1:]
    return roles


# ── 單日排班（AUTO 專用）────────────────────────────────────────
def _assign_one_day_with_fixed(
    day_meta: Dict[str, Any],
    prev_assignment: Dict[str, str],
    role_counts: Dict[str, Dict[str, int]],
) -> Dict[str, str]:
    employees = day_meta.get("employees", []) or []
    if not employees:
        return {}

    fixed: Dict[str, str] = dict(day_meta.get("fixed", {}) or {})

    # 套用全局固定角色（FIXED_ROLES 最優先）
    for emp in employees:
        if emp in FIXED_ROLES:
            fixed[emp] = FIXED_ROLES[emp]

    roles_pool, base_staff = _build_role_pool_for_day(employees)

    # 從角色池扣掉已固定的 A/B/C/D 槽位
    remaining_roles = roles_pool[:]
    for name, r in fixed.items():
        if FIXED_ROLES.get(name) == "E":
            continue
        if r in ("A", "B", "C", "D"):
            remaining_roles = _remove_one(remaining_roles, r)

    to_fill = [n for n in base_staff if n not in fixed]

    best_score = None
    best_assignment_partial: Dict[str, str] = {}

    def dfs(idx: int, current_assignment: Dict[str, str], roles_left: List[str]):
        nonlocal best_score, best_assignment_partial

        if idx >= len(to_fill):
            full = {**fixed, **current_assignment}
            s = _score_full_assignment(full, prev_assignment, role_counts)
            if best_score is None or s > best_score:
                best_score = s
                best_assignment_partial = dict(current_assignment)
            return

        name = to_fill[idx]
        allowed = RESTRICTED_ROLES.get(name, ["A", "B", "C", "D"])
        prev_role = prev_assignment.get(name)

        tried = set()
        for i, r in enumerate(roles_left):
            if r in tried:
                continue
            tried.add(r)

            if r not in allowed:
                continue

            # 前天C→今天不能C，除非此人 allowed 中沒有 A（角色受限，無法迴避）
            if prev_role == "C" and r == "C" and "A" in allowed:
                continue

            new_assignment = dict(current_assignment)
            new_assignment[name] = r
            dfs(idx + 1, new_assignment, roles_left[:i] + roles_left[i + 1:])

    if not to_fill:
        return dict(fixed)

    dfs(0, {}, remaining_roles)

    assignment: Dict[str, str] = dict(fixed)

    if best_score is None:
        # fallback：直接塞（極罕見）
        tmp = remaining_roles[:]
        for name in to_fill:
            assignment[name] = tmp.pop(0) if tmp else "C"
    else:
        assignment.update(best_assignment_partial)
        for name in to_fill:
            if name not in assignment:
                assignment[name] = "C"

    # 保底確認固定角色
    for emp in employees:
        if emp in FIXED_ROLES:
            assignment[emp] = FIXED_ROLES[emp]

    return assignment


# ── 多日排班主體 ───────────────────────────────────────────────
# day_meta 格式：
# {
#   "date": "YYYY-MM-DD",
#   "weekday": 0..6,
#   "mode": "AUTO" | "MANUAL" | "OFF",
#   "employees": [...],
#   "fixed": {name: role}   # MANUAL 時為完整 assignment；AUTO 時為空
# }
def generate_period(days_info: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    role_counts = {e: {r: 0 for r in ROLES} for e in EMPLOYEES}
    schedule: List[Dict[str, str]] = []
    prev_assignment: Dict[str, str] = {}

    for day_meta in days_info:
        mode = day_meta.get("mode", "AUTO")

        if mode == "OFF":
            schedule.append({})
            prev_assignment = {}  # 停爐後疲勞重置
            continue

        # AUTO 和 MANUAL 都走 scheduler，差別只在 fixed 是否有預填
        assignment = _assign_one_day_with_fixed(day_meta, prev_assignment, role_counts)
        schedule.append(assignment)
        for name, role in assignment.items():
            if name in role_counts and role in role_counts[name]:
                role_counts[name][role] += 1
        prev_assignment = assignment

    return schedule


# ── 單日 demo（保留測試用）────────────────────────────────────
def generate_day(employees: List[str], prev_day=None):
    if prev_day is None:
        prev_day = {}

    day_meta = {
        "date": "1970-01-01",
        "weekday": 0,
        "mode": "AUTO",
        "employees": employees,
        "fixed": {},
    }
    role_counts = {e: {r: 0 for r in ROLES} for e in EMPLOYEES}
    assignment = _assign_one_day_with_fixed(day_meta, prev_day, role_counts)
    score = _score_full_assignment(assignment, prev_day, role_counts)
    return assignment, score
