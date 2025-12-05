# scheduler.py
from __future__ import annotations
from typing import List, Dict, Any, Tuple
from collections import defaultdict

# 員工名單（你前面確認過）
EMPLOYEES = ["豐杰", "在慶", "學林", "奕忠", "子紘", "紀龍", "孟桓", "立群", "天立"]

ROLES = ["A", "B", "C", "D", "E"]

SPECIAL_C = "在慶"
SPECIAL_E = "奕忠"


def _build_role_pool_for_day(employees: List[str]) -> Tuple[List[str], List[str]]:
    """
    根據「人數」產生當天的 A/B/C/D 需求（不含 E），
    並且把「不做 E 的那群人」作為需要排班的對象回傳。

    規則：
    - 先把 '奕忠' 拿掉，對剩下的人照 ABCCD + 追加 的邏輯配角色數量
    - 基礎 5 人：A1, B1, C2, D1
    - 額外人力：先補 B（最多 2）、再補 D（最多 2）、最後一直補 C
    - '奕忠' 之後會直接被指定為 E，不進 A/B/C/D 角色池
    """
    # 先把奕忠拿掉，剩下的人才需要分 A/B/C/D
    base_staff = [e for e in employees if e != SPECIAL_E]
    n = len(base_staff)

    roles = []

    if n <= 0:
        return roles, base_staff

    # 如果人數 >= 5，用 ABCCD 當基礎
    if n >= 5:
        roles = ["A", "B", "C", "C", "D"]
        extra = n - 5
        for _ in range(extra):
            # 先補 B，最多 2 個
            if roles.count("B") < 2:
                roles.append("B")
            # 再補 D，最多 2 個
            elif roles.count("D") < 2:
                roles.append("D")
            # 其餘都補 C
            else:
                roles.append("C")
    else:
        # n < 5 的應急情況：盡量維持 1A / 1B / 至少1C
        # 超少人的狀態現實中幾乎不會出現，但先保護一下
        if n == 1:
            roles = ["C"]
        elif n == 2:
            roles = ["A", "C"]
        elif n == 3:
            roles = ["A", "B", "C"]
        elif n == 4:
            roles = ["A", "B", "C", "D"]

    return roles, base_staff


def _score_full_assignment(
    day_meta: Dict[str, Any],
    assignment: Dict[str, str],
    prev_assignment: Dict[str, str],
    role_counts: Dict[str, Dict[str, int]],
    bigA_counts: Dict[str, int],
    bigD_counts: Dict[str, int],
    monC_counts: Dict[str, int],
) -> float:
    """
    計算當天完整排班的分數（數字越高越好）。

    day_meta: {
      "date": "YYYY-MM-DD",
      "weekday": 0..6,  # Monday=0
      "big_day": bool,
      "employees": [...]
    }
    """
    score = 0.0
    big_day = bool(day_meta.get("big_day", False))
    weekday = int(day_meta.get("weekday", 0))  # 0 = Monday

    # 權重（可以之後微調）
    w_role_balance = 0.5    # 平日 A/B/C/D/E 平衡
    w_bigA = 3.5            # 大日 A 平均
    w_bigD = 3.0            # 大日 D 平均
    w_monC = 5.0            # 週一 C 平均
    fatigue_B_bonus = 2.5   # 昨天 C → 今天 B 的鼓勵
    fatigue_A_bonus = 1.5   # 昨天 C → 今天 A 的鼓勵

    for name, role in assignment.items():
        if role not in ROLES:
            continue

        # 角色-次數平衡：已經做很多次，就稍微扣分
        prev_count = role_counts[name].get(role, 0)
        score -= w_role_balance * prev_count

        # 大日 A / D 平均
        if big_day and role == "A":
            score -= w_bigA * bigA_counts[name]
        if big_day and role == "D":
            score -= w_bigD * bigD_counts[name]

        # 週一 C 平均（不含在慶＆奕忠）
        if weekday == 0 and role == "C" and name not in (SPECIAL_C, SPECIAL_E):
            score -= w_monC * monC_counts[name]

        # 疲勞模型：昨天如果是 C，今天 B / A 有加分
        prev_role = prev_assignment.get(name)
        if prev_role == "C":
            if role == "B":
                score += fatigue_B_bonus
            elif role == "A":
                score += fatigue_A_bonus

    return score


def _assign_one_day(
    day_meta: Dict[str, Any],
    prev_assignment: Dict[str, str],
    role_counts: Dict[str, Dict[str, int]],
    bigA_counts: Dict[str, int],
    bigD_counts: Dict[str, int],
    monC_counts: Dict[str, int],
) -> Dict[str, str]:
    """
    回傳當天的排班 assignment: { name: role }
    """
    employees = day_meta["employees"]
    if not employees:
        return {}

    # 先把「角色池」算出來（只含 A/B/C/D）
    roles_pool, base_staff = _build_role_pool_for_day(employees)

    # 強制：在慶有上班 → 必定 C
    must_C = set()
    if SPECIAL_C in base_staff:
        must_C.add(SPECIAL_C)

    # DFS 回溯找出最佳排法
    best_score = None
    best_assignment_partial: Dict[str, str] = {}

    base_staff_order = list(base_staff)  # 固定順序

    def dfs(idx: int, current_assignment: Dict[str, str], remaining_roles: List[str]):
        nonlocal best_score, best_assignment_partial

        if idx >= len(base_staff_order):
            # 所有 base_staff 都分配完了，計算分數
            temp_assignment = dict(current_assignment)

            # 再把奕忠加上 E（如果有上班）
            if SPECIAL_E in employees:
                temp_assignment[SPECIAL_E] = "E"

            s = _score_full_assignment(
                day_meta=day_meta,
                assignment=temp_assignment,
                prev_assignment=prev_assignment,
                role_counts=role_counts,
                bigA_counts=bigA_counts,
                bigD_counts=bigD_counts,
                monC_counts=monC_counts,
            )
            if best_score is None or s > best_score:
                best_score = s
                best_assignment_partial = dict(current_assignment)
            return

        name = base_staff_order[idx]

        # 依照當前 remaining_roles 嘗試派角色
        # 為了減少重複，可以先做一個「distinct roles」的 set
        tried_roles = set()
        for i, r in enumerate(remaining_roles):
            if r in tried_roles:
                continue
            tried_roles.add(r)

            # 強制條件：在慶 → 必須 C
            if name in must_C and r != "C":
                continue

            # 強制條件：同一人不能 C → C
            prev_role = prev_assignment.get(name)
            if prev_role == "C" and r == "C":
                continue

            # 試著把 r 指派給 name
            new_assignment = dict(current_assignment)
            new_assignment[name] = r
            new_remaining = remaining_roles[:i] + remaining_roles[i + 1 :]

            dfs(idx + 1, new_assignment, new_remaining)

    dfs(0, {}, roles_pool)

    # 如果完全找不到合法排法（理論上很少發生），就退回一個簡單方案
    if best_score is None:
        assignment = {}
        temp_roles = roles_pool[:]
        for name in base_staff:
            role = temp_roles.pop(0) if temp_roles else "C"
            assignment[name] = role
    else:
        assignment = dict(best_assignment_partial)

    # 奕忠 → E
    if SPECIAL_E in employees:
        assignment[SPECIAL_E] = "E"

    # 防呆：確保在慶如果有上班，一定是 C
    if SPECIAL_C in employees:
        assignment[SPECIAL_C] = "C"

    return assignment


def generate_period(days_info: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    主力：多日排班。

    days_info: list of dicts, 每天格式：
    {
      "date": "YYYY-MM-DD",
      "weekday": 0..6,   # Monday=0
      "big_day": bool,
      "employees": ["豐杰", "在慶", ...]
    }

    回傳：
      [ {name: role}, {name: role}, ... ]  # 與 days_info 順序相同
    """
    # 統計累積
    role_counts: Dict[str, Dict[str, int]] = {
        e: {r: 0 for r in ROLES} for e in EMPLOYEES
    }
    bigA_counts: Dict[str, int] = {e: 0 for e in EMPLOYEES}
    bigD_counts: Dict[str, int] = {e: 0 for e in EMPLOYEES}
    monC_counts: Dict[str, int] = {e: 0 for e in EMPLOYEES}

    schedule: List[Dict[str, str]] = []
    prev_assignment: Dict[str, str] = {}

    for day_meta in days_info:
        assignment = _assign_one_day(
            day_meta=day_meta,
            prev_assignment=prev_assignment,
            role_counts=role_counts,
            bigA_counts=bigA_counts,
            bigD_counts=bigD_counts,
            monC_counts=monC_counts,
        )
        schedule.append(assignment)

        # 更新統計
        big_day = bool(day_meta.get("big_day", False))
        weekday = int(day_meta.get("weekday", 0))

        for name, role in assignment.items():
            if role not in ROLES:
                continue
            role_counts[name][role] += 1

            if big_day and role == "A":
                bigA_counts[name] += 1
            if big_day and role == "D":
                bigD_counts[name] += 1
            if weekday == 0 and role == "C" and name not in (SPECIAL_C, SPECIAL_E):
                monC_counts[name] += 1

        prev_assignment = assignment

    return schedule


def generate_day(
    employees: List[str],
    prev_day: Dict[str, str] | None = None,
) -> Tuple[Dict[str, str], float]:
    """
    單日 demo 用的小函式。prev_day 是前一天的排班 {name: role}。
    回傳：(assignment, dummy_score)
    """
    if prev_day is None:
        prev_day = {}

    day_meta = {
        "date": "1970-01-01",
        "weekday": 0,       # 當 Monday 處理
        "big_day": False,
        "employees": employees,
    }

    # 簡化版：不累積跨日統計，只跑一天
    role_counts = {e: {r: 0 for r in ROLES} for e in EMPLOYEES}
    bigA_counts = {e: 0 for e in EMPLOYEES}
    bigD_counts = {e: 0 for e in EMPLOYEES}
    monC_counts = {e: 0 for e in EMPLOYEES}

    assignment = _assign_one_day(
        day_meta=day_meta,
        prev_assignment=prev_day,
        role_counts=role_counts,
        bigA_counts=bigA_counts,
        bigD_counts=bigD_counts,
        monC_counts=monC_counts,
    )

    # 這裡 score 就隨便算一下，主要是保持原介面
    score = _score_full_assignment(
        day_meta=day_meta,
        assignment=assignment,
        prev_assignment=prev_day,
        role_counts=role_counts,
        bigA_counts=bigA_counts,
        bigD_counts=bigD_counts,
        monC_counts=monC_counts,
    )

    return assignment, score
