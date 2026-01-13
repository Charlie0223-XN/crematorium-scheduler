# scheduler.py
from __future__ import annotations
from typing import List, Dict, Any, Tuple

# 員工名單
EMPLOYEES = ["豐杰", "孟桓", "立群", "學林", "天立", "在慶", "奕忠", "紀龍", "子紘"]
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
    roles: List[str] = []

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
# 分數計算：平均 + 疲勞模型（移除週一C平衡）
# ----------------------------------------------------
def _score_full_assignment(
    assignment: Dict[str, str],
    prev_assignment: Dict[str, str],
    role_counts: Dict[str, Dict[str, int]],
) -> float:
    score = 0.0

    # 權重（可調整）
    w_role_balance = 0.5
    fatigue_B_bonus = 2.5
    fatigue_A_bonus = 1.5

    for name, role in assignment.items():
        # 排班次數越多 → 越扣分（平均）
        prev_count = role_counts[name].get(role, 0)
        score -= w_role_balance * prev_count

        # 疲勞模型（昨日 C → 今日 A/B）
        prev_role = prev_assignment.get(name)
        if prev_role == "C":
            if role == "B":
                score += fatigue_B_bonus
            elif role == "A":
                score += fatigue_A_bonus

    return score


def _remove_one(roles: List[str], role: str) -> List[str]:
    """從 roles 中移除一個指定 role（若存在）"""
    if role in roles:
        idx = roles.index(role)
        return roles[:idx] + roles[idx + 1 :]
    return roles


# ----------------------------------------------------
# 單日排班（支援 fixed / partial 指定）
# fixed：{name: "A/B/C/D/E"} ；不在 fixed 的人由系統補排
# ----------------------------------------------------
def _assign_one_day_with_fixed(
    day_meta: Dict[str, Any],
    prev_assignment: Dict[str, str],
    role_counts: Dict[str, Dict[str, int]],
) -> Dict[str, str]:
    employees = day_meta.get("employees", []) or []
    if not employees:
        return {}

    fixed: Dict[str, str] = day_meta.get("fixed", {}) or {}

    # 奕忠 / 在慶：若有上班，強制 E / C（覆寫 fixed）
    if SPECIAL_E in employees:
        fixed[SPECIAL_E] = "E"
    if SPECIAL_C in employees:
        fixed[SPECIAL_C] = "C"

    roles_pool, base_staff = _build_role_pool_for_day(employees)

    # base_staff：不含奕忠
    # 先把 fixed（A/B/C/D）從角色池扣掉（若扣不到，代表你指定了額外角色，仍尊重，剩下的人會用剩餘池補）
    remaining_roles = roles_pool[:]
    for name, r in fixed.items():
        if name == SPECIAL_E:
            continue
        if r in ("A", "B", "C", "D"):
            remaining_roles = _remove_one(remaining_roles, r)

    # 需要 DFS 補排的人（base_staff 中，且不在 fixed）
    to_fill = [n for n in base_staff if n not in fixed]

    # 在慶永遠 C（上面已覆寫 fixed），這裡只是保險
    must_C = set()
    if SPECIAL_C in base_staff:
        must_C.add(SPECIAL_C)

    best_score = None
    best_assignment_partial: Dict[str, str] = {}

    # DFS
    def dfs(idx: int, current_assignment: Dict[str, str], roles_left: List[str]):
        nonlocal best_score, best_assignment_partial

        if idx >= len(to_fill):
            # 合成完整 assignment（fixed + current）
            full = {}
            # 先放 fixed
            for k, v in fixed.items():
                full[k] = v
            # 再放 DFS 補排
            for k, v in current_assignment.items():
                full[k] = v

            s = _score_full_assignment(full, prev_assignment, role_counts)
            if best_score is None or s > best_score:
                best_score = s
                best_assignment_partial = dict(current_assignment)
            return

        name = to_fill[idx]

        tried = set()
        for i, r in enumerate(roles_left):
            if r in tried:
                continue
            tried.add(r)

            # 在慶：只能 C（理論上不會進 to_fill，但保險）
            if name in must_C and r != "C":
                continue

            # 一般人：不能 C→C，但在慶除外
            prev_role = prev_assignment.get(name)
            if name not in must_C and prev_role == "C" and r == "C":
                continue

            new_assignment = dict(current_assignment)
            new_assignment[name] = r
            new_roles_left = roles_left[:i] + roles_left[i + 1 :]
            dfs(idx + 1, new_assignment, new_roles_left)

    # 如果沒有需要補排的人，直接回 fixed + 特殊規則
    if not to_fill:
        assignment = dict(fixed)
        # 再保守確保
        if SPECIAL_E in employees:
            assignment[SPECIAL_E] = "E"
        if SPECIAL_C in employees:
            assignment[SPECIAL_C] = "C"
        return assignment

    dfs(0, {}, remaining_roles)

    # DFS 找不到（極罕見）→ fallback：照 roles_left 順序塞，塞完不夠就補 C
    assignment: Dict[str, str] = {}
    assignment.update(fixed)

    if best_score is None:
        tmp = remaining_roles[:]
        for name in to_fill:
            role = tmp.pop(0) if tmp else "C"
            assignment[name] = role
    else:
        assignment.update(best_assignment_partial)

        # 如果剩餘角色池比人少，會有沒被塞到（理論上不會），這裡保底
        for name in to_fill:
            if name not in assignment:
                assignment[name] = "C"

    # 奕忠固定 E
    if SPECIAL_E in employees:
        assignment[SPECIAL_E] = "E"
    # 在慶固定 C
    if SPECIAL_C in employees:
        assignment[SPECIAL_C] = "C"

    return assignment


# ----------------------------------------------------
# 多日排班主體（一次性產出「最終班表」）
# day_meta 預期：
# {
#   "date": "YYYY-MM-DD",
#   "weekday": 0..6 (Mon=0),
#   "manual": bool,
#   "no_burn": bool,
#   "employees": [...working employees...],
#   "fixed": {name: "A/B/C/D/E"}   # 只有 manual day 可能帶
# }
# ----------------------------------------------------
def generate_period(days_info: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    role_counts = {e: {r: 0 for r in ROLES} for e in EMPLOYEES}

    schedule: List[Dict[str, str]] = []
    prev_assignment: Dict[str, str] = {}

    for day_meta in days_info:
        no_burn = bool(day_meta.get("no_burn", False))

        if no_burn:
            # 停爐：當天沒有排班；疲勞中斷（隔天不套用昨日C）
            schedule.append({})
            prev_assignment = {}
            continue

        assignment = _assign_one_day_with_fixed(day_meta, prev_assignment, role_counts)
        schedule.append(assignment)

        # 累積統計（公平性）
        for name, role in assignment.items():
            if name in role_counts and role in role_counts[name]:
                role_counts[name][role] += 1

        prev_assignment = assignment

    return schedule


# ----------------------------------------------------
# 單日 demo（保留）
# ----------------------------------------------------
def generate_day(employees: List[str], prev_day=None):
    if prev_day is None:
        prev_day = {}

    day_meta = {
        "date": "1970-01-01",
        "weekday": 0,
        "manual": False,
        "no_burn": False,
        "employees": employees,
        "fixed": {},
    }

    role_counts = {e: {r: 0 for r in ROLES} for e in EMPLOYEES}

    assignment = _assign_one_day_with_fixed(day_meta, prev_day, role_counts)
    score = _score_full_assignment(assignment, prev_day, role_counts)

    return assignment, score
