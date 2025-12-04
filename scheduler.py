import itertools
import json
# 全員名單（可以之後改成從別處讀）
EMPLOYEES = ["紀龍", "奕忠", "子紘", "在慶", "豐杰", "學林", "孟桓", "立群", "天立"]

# -----------------------------------
# 載入規則
# -----------------------------------

with open("rules.json", encoding="utf-8") as f:
    RULES = json.load(f)

FIXED = RULES["hard_rules"]["fixed_roles"]
MIN_ROLES = RULES["hard_rules"]["min_roles_per_day"]
NO_C_TWICE = RULES["hard_rules"]["no_C_twice_non_Zaiqing"]

FATIGUE = RULES["soft_rules"]["fatigue_model"]
CONFLICT = RULES["soft_rules"]["relationship_penalties"]["conflicts"]
CONFLICT_PENALTY = RULES["soft_rules"]["relationship_penalties"]["same_day_penalty"]
HIGH_INT_PENALTY = RULES["soft_rules"]["relationship_penalties"]["high_interaction_penalty"]
HIGH_ROLES = RULES["soft_rules"]["high_interaction_roles"]
SYNERGY = RULES["soft_rules"]["role_synergy"]

# -----------------------------------
# 工具函數
# -----------------------------------

def is_conflict(p1, p2):
    return [p1, p2] in CONFLICT or [p2, p1] in CONFLICT

def in_high_interaction(role):
    return role in HIGH_ROLES

def violates_hard_rules(assign):
    # 固定崗位限制
    for p, role in assign.items():
        if p in FIXED and role not in FIXED[p]:
            return True

    # 每日最小數量
    role_count = {r: 0 for r in "ABCDE"}
    for r in assign.values():
        role_count[r] += 1

    for r, m in MIN_ROLES.items():
        if role_count[r] < m:
            return True

    return False

# -----------------------------------
# 評分函數（核心）
# -----------------------------------

def score_assignment(assign, prev_day):
    score = 0

    # 疲勞模型（根據前一天）
    for person, role in assign.items():
        if person in prev_day:
            prev_role = prev_day[person]

            # C → ?
            if prev_role == "C":
                score += FATIGUE["C_next"].get(role, 0)

            # D → ?
            if prev_role == "D":
                score += FATIGUE["D_next"].get(role, 0)

            # 禁止 C 連兩天（除在慶）
            if prev_role == "C" and role == "C" and person != "在慶":
                score -= 9999

    # 人際衝突
    persons = list(assign.keys())
    for i, p1 in enumerate(persons):
        for p2 in persons[i+1:]:
            if is_conflict(p1, p2):
                score += CONFLICT_PENALTY

                # 若兩人都是 A/B/D → 再扣
                if in_high_interaction(assign[p1]) and in_high_interaction(assign[p2]):
                    score += HIGH_INT_PENALTY

    return score

# -----------------------------------
# 一日排班演算法（簡易版）
# -----------------------------------

from collections import Counter

def build_role_pool(employees_today):
    """
    根據今天上班人數，產生「角色池」：
    - 先放入硬規則下限：A1、B1、C2、D1
    - 若還有多餘人數，依序多放：B -> D -> C
    - 若有奕忠在班，補一格 E
    - 在慶固定 C，但不需要多放額外 C（因為他本來就算在 C 配額裡）
    """
    n = len(employees_today)
    pool = Counter()

    # 基本下限
    pool["A"] += MIN_ROLES.get("A", 0)
    pool["B"] += MIN_ROLES.get("B", 0)
    pool["C"] += MIN_ROLES.get("C", 0)
    pool["D"] += MIN_ROLES.get("D", 0)

    # 固定職位：奕忠 -> E
    if "奕忠" in employees_today:
        pool["E"] += 1

    # 計算目前已分配的格子數
    base_slots = sum(pool.values())
    extra = n - base_slots

    order = ["B", "D", "C"]  # 多餘人力分配順序
    idx = 0
    while extra > 0:
        role = order[idx % len(order)]
        pool[role] += 1
        extra -= 1
        idx += 1

    return pool


def generate_day(employees, prev_day):
    """
    回溯＋剪枝版：
    - 先建立今天需要的 role pool
    - 固定職位（奕忠:E、在慶:C）直接鎖定
    - 其餘人用 DFS 逐一填入角色，邊填邊檢查：
        * 硬規則（角色池用完、C 連打）
        * 立即可計算的疲勞分數
        * 人際衝突（與已填人比對）
    - 保留最高分配置
    """
    # 角色池
    role_pool = build_role_pool(employees)

    # 固定職位先分配
    fixed_assign = {}
    for p in employees:
        if p in FIXED:
            role = FIXED[p][0]
            fixed_assign[p] = role
            role_pool[role] -= 1  # 占用一格
            if role_pool[role] < 0:
                # 理論上不會發生，除非規則設錯
                raise ValueError("角色池與固定職位衝突")

    # 準備回溯
    flex_emps = [p for p in employees if p not in fixed_assign]

    best_assign = None
    best_score = -10**9

    def dfs(idx, current_assign, current_score, pool):
        nonlocal best_assign, best_score

        # 所有人都被分配完 → 計總分
        if idx == len(flex_emps):
            # 補上固定職位
            final_assign = {**current_assign, **fixed_assign}
            # 再跑一次完整 score（包含人際衝突）
            final_score = score_assignment(final_assign, prev_day)
            if final_score > best_score:
                best_score = final_score
                best_assign = final_assign
            return

        person = flex_emps[idx]

        # 試所有還有剩的角色
        for role, cnt in list(pool.items()):
            if cnt <= 0:
                continue

            # 先做局部硬規則檢查：C 連打（非在慶）
            if person in prev_day:
                prev_role = prev_day[person]
                if prev_role == "C" and role == "C" and person != "在慶":
                    continue  # 直接剪掉

            # 暫時賦值
            pool[role] -= 1
            current_assign[person] = role

            # 局部疲勞分數（先加一點，最後再統算）
            inc = 0
            if person in prev_day:
                prev_role = prev_day[person]
                if prev_role == "C":
                    inc += FATIGUE["C_next"].get(role, 0)
                if prev_role == "D":
                    inc += FATIGUE["D_next"].get(role, 0)

            # 若這一步分數已經慘到不可能翻盤，其實可以剪枝
            # 但這個版本先簡單一些，不做上界估計
            dfs(idx + 1, current_assign, current_score + inc, pool)

            # 回溯
            pool[role] += 1
            del current_assign[person]

    dfs(0, {}, 0, role_pool)

    return best_assign, best_score

def generate_period(days_employees, initial_prev_day=None):
    """
    days_employees: list[list[str]]
        例如：[
          ["豐杰", "在慶", "學林", "奕忠", "子紘", "紀龍"],  # 第 1 天
          ["豐杰", "在慶", "孟桓", "奕忠", "學林"],        # 第 2 天
          ...
        ]

    initial_prev_day: dict 或 None
        第一天下去之前，要不要先給一個「前一天排班」當疲勞模型起點。
        大多數情況可以給 {} 或不給。
    """
    schedule = []
    prev_day = initial_prev_day or {}

    for employees_today in days_employees:
        assignment, score = generate_day(employees_today, prev_day)
        schedule.append(assignment)
        prev_day = assignment  # 下一天用今天的結果當 prev_day

    return schedule
