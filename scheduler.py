# scheduler.py
from __future__ import annotations
from typing import List, Dict, Any, Tuple

# 員工名單
EMPLOYEES = ["豐杰", "在慶", "學林", "奕忠", "子紘", "紀龍", "孟桓", "立群", "天立"]
ROLES = ["A", "B", "C", "D", "E"]

SPECIAL_C = "在慶"
SPECIAL_E = "奕忠"

# ----------------------------------------------------
# 角色池生成：硬邏輯 ABCCD + B → D → C 的追加規則
# ----------------------------------------------------
def _build_role_pool_for_day(employees: List[str]) -> Tuple[List[str], List[str]]:
    """產生當天的 A/B/C/D 需求（不含E）"""

    base_staff = [e for e in employees if e != SPECIAL_E]  # 奕忠不進一般角色池
    n = len(base_staff)
    roles = []

    if n <= 0:
        return roles, base_staff

    # 基礎五人配置：ABCCD
    if n >= 5:
        roles = ["A", "B", "C", "C", "D"]
        extra = n - 5

        # 先補 B（最多2），再補 D（最多2），其餘補 C
        for _ in range(extra):
            if roles.count("B") < 2:
                roles.append("B")
            elif roles.count("D") < 2:
                roles.append("D")
            else:
                roles.append("C")

    else:
        # 少於五人的緊急保底
        if n == 1:
            roles = ["C"]
        elif n == 2:
            roles = ["A", "C"]
        elif n == 3:
            roles = ["A", "B", "C"]
        elif n == 4:
            roles = ["A", "B", "C", "D"]

    return roles, base_staff


# ----------------------------------------------------
# 分數計算（沒有倫理模型）
# ----------------------------------------------------
def _score_full_assignment(
    day_meta: Dict[str, Any],
    assignment: Dict[str, str],
    prev_assignment: Dict[str, str],
    role_counts: Dict[str, Dict[str, int]],
    bigA_counts: Dict[str, int],
    bigD_counts: Dict[str, int],
    monC_counts: Dict[str, int],
) -> float:

    score = 0.0
    big_day = bool(day_meta.get("big_day", False))
    weekday = int(day_meta.get("weekday", 0))  # Monday = 0

    # 權重（可調整）
    w_role_balance = 0.5
    w_bigA = 3.5
    w_bigD = 3.0
    w_monC = 5.0
    fatigue_B_bonus = 2.5
    fatigue_A_bonus = 1.5

    for name, role in assignment.items():

        # 排班次數越多 → 越扣分（平均）
        prev_count = role_counts[name].get(role, 0)
        score -= w_role_balance * prev_count

        # 大日 A、D 的平均
        if big_day and role == "A":
            score -= w_bigA * bigA_counts[name]
        if big_day and role == "D":
            score -= w_bigD * bigD_counts[name]

        # 週一 C 平均（排除在慶、奕忠）
        if weekday == 0 and role == "C" and name not in (SPECIAL_C, SPECIAL_E):
            score -= w_monC * monC_counts[name]

        # 疲勞模型（昨日 C → 今日 A/B）
        prev_role = prev_assignment.get(name)
        if prev_role == "C":
            if role == "B":
                score += fatigue_B_bonus
            elif role == "A":
                score += fatigue_A_bonus

    return score


# ----------------------------------------------------
# 單日排班（DFS）
# ----------------------------------------------------
def _assign_one_day(
    day_meta: Dict[str, Any],
    prev_assignment: Dict[str, str],
    role_counts: Dict[str, Dict[str, int]],
    bigA_counts: Dict[str, int],
    bigD_counts: Dict[str, int],
    monC_counts: Dict[str, int],
) -> Dict[str, str]:

    employees = day_meta["employees"]
    if not employees:
        return {}

    roles_pool, base_staff = _build_role_pool_for_day(employees)

    # 在慶 → 永遠 C
    must_C = set()
    if SPECIAL_C in base_staff:
        must_C.add(SPECIAL_C)

    best_score = None
    best_assignment_partial = {}

    base_staff_order = list(base_staff)  # 固定順序

    # DFS
    def dfs(idx: int, current_assignment: Dict[str, str], remaining_roles: List[str]):
        nonlocal best_score, best_assignment_partial

        if idx >= len(base_staff_order):
            temp_assignment = dict(current_assignment)

            # 奕忠固定 E
            if SPECIAL_E in employees:
                temp_assignment[SPECIAL_E] = "E"

            s = _score_full_assignment(
                day_meta, temp_assignment, prev_assignment,
                role_counts, bigA_counts, bigD_counts, monC_counts
            )

            if best_score is None or s > best_score:
                best_score = s
                best_assignment_partial = dict(current_assignment)
            return

        name = base_staff_order[idx]

        tried = set()
        for i, r in enumerate(remaining_roles):
            if r in tried:
                continue
            tried.add(r)

            # 在慶：只能 C
            if name in must_C and r != "C":
                continue

            # 一般人：不能 C→C，但在慶除外
            prev_role = prev_assignment.get(name)
            if name not in must_C and prev_role == "C" and r == "C":
                continue

            new_assignment = dict(current_assignment)
            new_assignment[name] = r

            new_remaining = remaining_roles[:i] + remaining_roles[i+1:]
            dfs(idx + 1, new_assignment, new_remaining)

    dfs(0, {}, roles_pool)

    # 找不到（極罕見）→ fallback
    if best_score is None:
        assignment = {}
        tmp = roles_pool[:]
        for name in base_staff:
            role = tmp.pop(0) if tmp else "C"
            assignment[name] = role
    else:
        assignment = dict(best_assignment_partial)

    # 奕忠固定 E
    if SPECIAL_E in employees:
        assignment[SPECIAL_E] = "E"

    # 在慶固定 C（DFS 已經保證，這裡只是保守 double-check）
    if SPECIAL_C in employees:
        assignment[SPECIAL_C] = "C"

    return assignment


# ----------------------------------------------------
# 多日排班主體
# ----------------------------------------------------
def generate_period(days_info: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    role_counts = {e: {r: 0 for r in ROLES} for e in EMPLOYEES}
    bigA_counts = {e: 0 for e in EMPLOYEES}
    bigD_counts = {e: 0 for e in EMPLOYEES}
    monC_counts = {e: 0 for e in EMPLOYEES}

    schedule = []
    prev_assignment = {}

    for day_meta in days_info:
        assignment = _assign_one_day(
            day_meta, prev_assignment,
            role_counts, bigA_counts, bigD_counts, monC_counts
        )
        schedule.append(assignment)

        big_day = bool(day_meta.get("big_day", False))
        weekday = int(day_meta.get("weekday", 0))

        for name, role in assignment.items():
            role_counts[name][role] += 1
            if big_day and role == "A":
                bigA_counts[name] += 1
            if big_day and role == "D":
                bigD_counts[name] += 1
            if weekday == 0 and role == "C" and name not in (SPECIAL_C, SPECIAL_E):
                monC_counts[name] += 1

        prev_assignment = assignment

    return schedule


# ----------------------------------------------------
# 單日 demo
# ----------------------------------------------------
def generate_day(employees: List[str], prev_day=None):
    if prev_day is None:
        prev_day = {}

    day_meta = {
        "date": "1970-01-01",
        "weekday": 0,
        "big_day": False,
        "employees": employees,
    }

    role_counts = {e: {r: 0 for r in ROLES} for e in EMPLOYEES}
    bigA_counts = {e: 0 for e in EMPLOYEES}
    bigD_counts = {e: 0 for e in EMPLOYEES}
    monC_counts = {e: 0 for e in EMPLOYEES}

    assignment = _assign_one_day(
        day_meta, prev_day,
        role_counts, bigA_counts, bigD_counts, monC_counts
    )

    score = _score_full_assignment(
        day_meta, assignment, prev_day,
        role_counts, bigA_counts, bigD_counts, monC_counts
    )

    return assignment, score
