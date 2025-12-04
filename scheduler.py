# scheduler.py
import random
from collections import defaultdict
from typing import Dict, List, Tuple, Any

# ===== 員工名單 =====
# 這裡請用你原本的 EMPLOYEES 名單即可
EMPLOYEES: List[str] = [
    "在慶", "天立", "突然", "子桓", "孟偉", "孟桓",
    "學林", "立群", "紀龍", "配龍", "豐杰",
]

# ===== 每天需要的角色數量（可以之後再調） =====
# 這只是示意，你可以依實際狀況調整
ROLE_REQUIREMENTS: Dict[str, int] = {
    "A": 1,
    "B": 2,
    "C": 3,
    "D": 2,
    "E": 0,  # 可以當作多餘人手的備援
}

# 角色疲勞強度大致順序：D >= A > C > B > E (你可以之後再微調)
# 我們主要在意：連續 C、連續 A/B，以及 C 隔天去扛重的
# 權重調整的地方都寫在註解裡了


# ==========================
#   工具：建立今日要用的 role 配額
# ==========================
def _init_remaining_roles(num_employees: int) -> Dict[str, int]:
    """
    依 ROLE_REQUIREMENTS 建出「今日剩餘角色」。
    若人數比總配額多，就補 E；若少，就從 E / B 開始刪。
    """
    remaining = dict(ROLE_REQUIREMENTS)
    total = sum(remaining.values())

    # 人比較多 -> 增加 E
    while total < num_employees:
        remaining["E"] = remaining.get("E", 0) + 1
        total += 1

    # 人比較少 -> 減少 E / B / D / A / C 順序
    reduce_order = ["E", "B", "D", "A", "C"]
    while total > num_employees:
        for r in reduce_order:
            if remaining.get(r, 0) > 0:
                remaining[r] -= 1
                total -= 1
                break

    return remaining


# ==========================
#   硬限制判斷
# ==========================
def _hard_ok(emp: str, role: str, prev_assign: Dict[str, str]) -> bool:
    """
    不可違反的硬限制：
    - 前一天是 C，今天不能再 C
    （之後若你想加其他「絕對禁止」也可以放進來）
    """
    prev_role = prev_assign.get(emp)
    if prev_role == "C" and role == "C":
        return False
    return True


# ==========================
#   演算法內部用的狀態
# ==========================
def _empty_stats() -> Dict[str, defaultdict]:
    """
    stats 結構：
    - ad_count：每個人 A/D 的總次數
    - big_ad_count：每個人「大日上的 A/D」次數
    - mon_c_count：每個人「星期一 C」次數（在慶除外）
    """
    return {
        "ad_count": defaultdict(int),
        "big_ad_count": defaultdict(int),
        "mon_c_count": defaultdict(int),
    }


# ==========================
#   隨機產生一個「符合硬限制」的排班
# ==========================
def _generate_random_assignment(
    day_info: Dict[str, Any],
    prev_assign: Dict[str, str]
) -> Dict[str, str] | None:
    employees: List[str] = day_info["employees"]

    remaining = _init_remaining_roles(len(employees))
    emps = employees[:]
    random.shuffle(emps)

    assignment: Dict[str, str] = {}

    for emp in emps:
        # 可以用的角色（還有剩、而且不違反硬限制）
        candidates = [
            r for r, cnt in remaining.items()
            if cnt > 0 and _hard_ok(emp, r, prev_assign)
        ]

        if not candidates:
            return None  # 這次嘗試失敗，外面會再重跑一次

        role = random.choice(candidates)
        assignment[emp] = role
        remaining[role] -= 1

    return assignment


# ==========================
#   計算某個排班的分數（越小越好）
# ==========================
def _score_assignment(
    day_info: Dict[str, Any],
    assignment: Dict[str, str],
    prev_assign: Dict[str, str],
    stats: Dict[str, defaultdict],
) -> Tuple[float, Dict[str, int], Dict[str, int], Dict[str, int]]:
    big_day: bool = day_info["big_day"]
    weekday: int = day_info["weekday"]  # Monday = 0

    ad_count = stats["ad_count"].copy()
    big_ad_count = stats["big_ad_count"].copy()
    mon_c_count = stats["mon_c_count"].copy()

    penalty = 0.0

    for emp, role in assignment.items():
        prev_role = prev_assign.get(emp)

        # --- 疲勞模型：前一天 C ---
        if prev_role == "C":
            # C -> C 在硬限制已經擋掉，理論上不會出現
            if role in ("D", "E"):
                penalty += 30  # C 後去扛 D/E 會很累
            elif role in ("A", "B"):
                penalty += 10  # C -> A/B 還行，但也加一點負擔

        # --- 疲勞模型：連續 A/B ---
        if prev_role in ("A", "B") and role in ("A", "B"):
            penalty += 20  # 避免一直在前線

        # --- 累計 AD 次數（全期間）---
        if role in ("A", "D"):
            ad_count[emp] += 1
            if big_day:
                big_ad_count[emp] += 1

        # --- 星期一 C 的公平：在慶除外 ---
        if weekday == 0 and role == "C" and emp != "在慶":
            mon_c_count[emp] += 1

    # --- 公平性：A/D 全期間平均 ---
    if ad_count:
        diff_ad = max(ad_count.values()) - min(ad_count.values())
        penalty += diff_ad * 5.0  # 全體 A/D 平均（中等權重）

    # --- 公平性：大日 A/D 平均（權重更高）---
    if big_ad_count:
        diff_big = max(big_ad_count.values()) - min(big_ad_count.values())
        penalty += diff_big * 10.0  # 大日 AD 要更平均

    # --- 公平性：星期一 C 平均 ---
    non_z = {k: v for k, v in mon_c_count.items() if k != "在慶"}
    if non_z:
        diff_mon = max(non_z.values()) - min(non_z.values())
        penalty += diff_mon * 3.0

    # --- 倫理模型（目前權重最低，先給一個很小的 hook）---
    # 你之後如果想加「誰跟誰不要湊在一起」可以在這裡 + penalty
    # 例如：
    # bad_pairs = {("A某人", "B某人"), ...}
    # for (e1, r1) in assignment.items():
    #   for (e2, r2) in assignment.items():
    #       if (e1, e2) in 某表，就 + 1 之類
    # 目前先不啟用。

    return penalty, ad_count, big_ad_count, mon_c_count


# ==========================
#   排一天（供 period 專用）
# ==========================
def _schedule_one_day(
    day_info: Dict[str, Any],
    prev_assign: Dict[str, str],
    stats: Dict[str, defaultdict],
    tries: int = 800,
) -> Tuple[Dict[str, str], Dict[str, defaultdict]]:
    """
    主力：給今天的 meta + 昨天排班 + 累積 stats，
    用隨機搜尋找出分數最低的一組 assign。
    """
    best_assign: Dict[str, str] | None = None
    best_score = float("inf")
    best_counts = None

    for _ in range(tries):
        assign = _generate_random_assignment(day_info, prev_assign)
        if not assign:
            continue

        score, ad_c, big_c, mon_c = _score_assignment(
            day_info, assign, prev_assign, stats
        )

        if score < best_score:
            best_score = score
            best_assign = assign
            best_counts = (ad_c, big_c, mon_c)

    if best_assign is None:
        # 若真的全失敗，我們先粗暴用「不要考慮疲勞，只顧 role 配額」的方式湊一組
        # 理論上很少會觸發
        fallback = {}
        remaining = _init_remaining_roles(len(day_info["employees"]))
        for emp in day_info["employees"]:
            for r, cnt in remaining.items():
                if cnt > 0:
                    fallback[emp] = r
                    remaining[r] -= 1
                    break
        new_stats = {
            "ad_count": stats["ad_count"].copy(),
            "big_ad_count": stats["big_ad_count"].copy(),
            "mon_c_count": stats["mon_c_count"].copy(),
        }
        return fallback, new_stats

    new_stats = {
        "ad_count": best_counts[0],
        "big_ad_count": best_counts[1],
        "mon_c_count": best_counts[2],
    }
    return best_assign, new_stats


# ==========================
#   對外介面：多日排班（主力）
# ==========================
def generate_period(days_info: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    days_info 格式：
    [
      {
        "date": "2025-12-01",
        "weekday": 0,   # Monday = 0
        "big_day": True,
        "employees": ["在慶", "天立", ...]
      },
      ...
    ]
    """
    stats = _empty_stats()
    schedule: List[Dict[str, str]] = []
    prev_assign: Dict[str, str] = {}

    for day in days_info:
        assign, stats = _schedule_one_day(day, prev_assign, stats)
        schedule.append(assign)
        prev_assign = assign

    return schedule


# ==========================
#   對外介面：單日 demo 用（/api/schedule）
# ==========================
def generate_day(employees: List[str], prev_day: Dict[str, str]) -> Tuple[Dict[str, str], float]:
    """
    為了保留原本 /api/schedule 單日 demo 的介面。
    這裡不考慮「整段期間的平均」，只排一天，score 先固定 0。
    """
    day_info = {
        "date": "demo",
        "weekday": -1,
        "big_day": False,
        "employees": employees,
    }
    stats = _empty_stats()
    assign, _ = _schedule_one_day(day_info, prev_day or {}, stats, tries=400)
    return assign, 0.0
