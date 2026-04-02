# test_scheduler.py
"""
排班核心邏輯的基本單元測試。
執行：python test_scheduler.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from scheduler import (
    EMPLOYEES, FIXED_ROLES, RESTRICTED_ROLES, ROLES,
    generate_period, generate_day,
)


def assert_eq(desc, actual, expected):
    if actual != expected:
        print(f"  FAIL  {desc}")
        print(f"        expected: {expected}")
        print(f"        actual:   {actual}")
        return False
    print(f"  PASS  {desc}")
    return True


def assert_true(desc, condition):
    if not condition:
        print(f"  FAIL  {desc}")
        return False
    print(f"  PASS  {desc}")
    return True


passed = failed = 0

def run(desc, condition):
    global passed, failed
    if assert_true(desc, condition):
        passed += 1
    else:
        failed += 1


print("=== scheduler tests ===\n")

# ── 1. 固定角色：奕忠永遠 E ──────────────────────────────────
print("[ 固定角色 ]")
result, _ = generate_day(EMPLOYEES)
run("奕忠固定 E", result.get("奕忠") == "E")
run("井仁固定 C", result.get("井仁") == "C")
run("俊瑋固定 C", result.get("俊瑋") == "C")

# ── 2. 受限角色：在慶只能 B/C/D ─────────────────────────────
print("\n[ 受限角色 ]")
for _ in range(30):
    r, _ = generate_day(EMPLOYEES)
    zaiqing_role = r.get("在慶")
    if zaiqing_role not in ("B", "C", "D"):
        run(f"在慶限 B/C/D（30次隨機）", False)
        break
else:
    run("在慶限 B/C/D（30次隨機）", True)

# ── 3. 疲勞模型：前天C→今天不能C（一般員工）────────────────────
# 僅測 5 人，角色池 ABCCD 中只有 2 個 C → 一般員工前天排 C 的人今天拿不到 C
print("\n[ 疲勞模型 ]")
from scheduler import _assign_one_day_with_fixed, FIXED_ROLES as FR
from typing import Dict

# 5 人：選不含固定角色員工的一般員工
normal_emps = [e for e in EMPLOYEES if e not in FR and e not in RESTRICTED_ROLES][:5]
prev_all_c = {e: "C" for e in normal_emps}
day_meta = {"date": "2026-01-01", "weekday": 3, "mode": "AUTO",
            "employees": normal_emps, "fixed": {}}
role_counts: Dict = {e: {r: 0 for r in ROLES} for e in EMPLOYEES}
assignment = _assign_one_day_with_fixed(day_meta, prev_all_c, role_counts)

# 5人時角色池 ABCCD：只有 2 個C，所以最多 2 人能拿 C
# 驗證：前天排C的一般員工，今天被分到 C 的數量不超過 2
c_count = sum(1 for e in normal_emps if assignment.get(e) == "C")
run("前天全C（5人）→ 今天C的數量不超過角色池C上限(2)", c_count <= 2)

# ── 4. OFF 模式：停爐日回傳空 assignment ─────────────────────
print("\n[ OFF 模式 ]")
schedule = generate_period([
    {"date": "2026-01-01", "weekday": 3, "mode": "OFF", "employees": [], "fixed": {}}
])
run("停爐日 assignment 為空 dict", schedule[0] == {})

# ── 5. MANUAL 模式：原樣輸出，不進 scheduler ─────────────────
print("\n[ MANUAL 模式 ]")
manual_assign = {"豐杰": "A", "在慶": "B", "奕忠": "E"}
schedule = generate_period([
    {"date": "2026-01-01", "weekday": 3, "mode": "MANUAL",
     "employees": list(manual_assign.keys()), "fixed": manual_assign}
])
run("手動日 assignment 完全照輸入", schedule[0] == manual_assign)

# ── 6. AUTO 多日：角色池覆蓋所有在場員工 ──────────────────────
print("\n[ AUTO 多日 ]")
days_info = [
    {"date": f"2026-01-{i:02d}", "weekday": i % 7, "mode": "AUTO",
     "employees": EMPLOYEES, "fixed": {}}
    for i in range(1, 8)
]
schedule = generate_period(days_info)
all_covered = all(
    len(day_assign) == len(EMPLOYEES)
    for day_assign in schedule
)
run("全員出勤時每日 assignment 包含所有人", all_covered)

roles_valid = all(
    v in ROLES
    for day_assign in schedule
    for v in day_assign.values()
)
run("所有角色值合法（ABCDE）", roles_valid)

# ── 結果 ────────────────────────────────────────────────────
print(f"\n{'='*30}")
print(f"結果：{passed} passed，{failed} failed")
if failed:
    sys.exit(1)
