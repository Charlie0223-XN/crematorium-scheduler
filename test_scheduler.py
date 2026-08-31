"""排班核心 v2 單元測試。執行：python -m unittest -v test_scheduler.py"""
from __future__ import annotations

import unittest
from collections import Counter
from datetime import date, timedelta

from scheduler import (
    EMPLOYEES,
    EMPLOYEE_ROWS,
    RESTRICTED_ROLES,
    ROLES,
    ScheduleError,
    calculate_stats,
    generate_period,
)


START = date(2026, 9, 1)


def make_days(overrides=None):
    overrides = overrides or {}
    days = []
    for index in range(28):
        item = {
            "date": (START + timedelta(days=index)).isoformat(),
            "day_type": "NORMAL",
            "label": "",
            "requirements": {},
        }
        item.update(overrides.get(index, {}))
        days.append(item)
    return days


def staggered_vacations(off_indexes=()):
    off_indexes = set(off_indexes)
    vacations = {}
    for employee_index, name in enumerate(EMPLOYEES):
        indexes = []
        candidate_index = employee_index
        while len(indexes) < 8:
            index = candidate_index % 28
            if index not in off_indexes and index not in indexes:
                indexes.append(index)
            candidate_index += 13
        vacations[name] = [
            (START + timedelta(days=index)).isoformat() for index in sorted(indexes)
        ]
    return vacations


class SchedulerV2Tests(unittest.TestCase):
    def test_employee_configuration_and_order(self):
        self.assertEqual(len(EMPLOYEES), 13)
        self.assertEqual(
            EMPLOYEE_ROWS[0],
            ["豐杰", "孟桓", "立群", "學林", "天立", "井仁", "崇誠"],
        )
        self.assertEqual(
            EMPLOYEE_ROWS[1],
            ["在慶", "奕忠", "紀龍", "子紘", "俊瑋", "呈哲"],
        )
        self.assertEqual(ROLES, ("A", "B", "C"))
        self.assertEqual(RESTRICTED_ROLES["天立"], ["B", "C"])
        self.assertEqual(RESTRICTED_ROLES["在慶"], ["B", "C"])

    def test_normal_day_is_two_a_two_c_and_rest_b(self):
        day = make_days()[:1]
        vacations = {name: [] for name in EMPLOYEES}
        result = generate_period(day, vacations, seed=100)
        counts = Counter(result["schedule"][0]["assignment"].values())
        self.assertEqual(counts, {"A": 2, "B": 9, "C": 2})

    def test_28_days_respect_vacations_and_daily_requirements(self):
        days = make_days({5: {"day_type": "BIG"}, 12: {"day_type": "BIG"}})
        vacations = staggered_vacations()
        result = generate_period(days, vacations, seed=20260831)

        self.assertEqual(len(result["schedule"]), 28)
        for day in result["schedule"]:
            assignment = day["assignment"]
            self.assertFalse(set(assignment) & set(day["vacations"]))
            counts = Counter(assignment.values())
            self.assertEqual(counts["A"], 2)
            self.assertEqual(counts["C"], 2)
            self.assertEqual(counts["B"], len(assignment) - 4)

    def test_restricted_employees_never_receive_a(self):
        result = generate_period(
            make_days(),
            {name: [] for name in EMPLOYEES},
            seed=77,
        )
        for day in result["schedule"]:
            self.assertNotEqual(day["assignment"].get("天立"), "A")
            self.assertNotEqual(day["assignment"].get("在慶"), "A")

    def test_restricted_employees_prefer_b_over_c(self):
        result = generate_period(
            make_days(),
            {name: [] for name in EMPLOYEES},
            seed=99,
        )
        stats = {item["name"]: item for item in result["stats"]["employees"]}
        for name in ("天立", "在慶"):
            self.assertGreater(stats[name]["role_counts"]["B"], stats[name]["role_counts"]["C"])

    def test_custom_day_uses_exact_counts_and_leaves_others_unassigned(self):
        days = make_days({
            0: {
                "day_type": "CUSTOM",
                "label": "停爐留守",
                "requirements": {"A": 0, "B": 2, "C": 0},
            }
        })[:1]
        result = generate_period(days, {name: [] for name in EMPLOYEES}, seed=5)
        custom_day = result["schedule"][0]
        self.assertEqual(Counter(custom_day["assignment"].values()), {"B": 2})
        self.assertEqual(len(custom_day["unassigned"]), 11)

    def test_impossible_custom_role_requirement_is_rejected(self):
        days = [{
            "date": START.isoformat(),
            "day_type": "CUSTOM",
            "label": "限制測試",
            "requirements": {"A": 1, "B": 0, "C": 0},
        }]
        vacations = {
            name: ([] if name in ("天立", "在慶") else [START.isoformat()])
            for name in EMPLOYEES
        }
        with self.assertRaises(ScheduleError):
            generate_period(days, vacations, seed=1)

    def test_off_day_has_no_assignment_and_no_vacations(self):
        days = make_days({0: {"day_type": "OFF"}})[:1]
        vacations = {name: [START.isoformat()] for name in EMPLOYEES}
        result = generate_period(days, vacations, seed=1)
        self.assertEqual(result["schedule"][0]["assignment"], {})
        self.assertEqual(result["schedule"][0]["vacations"], [])

    def test_same_seed_repeats_and_new_seed_can_reroll(self):
        days = make_days()
        vacations = staggered_vacations()
        first = generate_period(days, vacations, seed=123)["schedule"]
        repeated = generate_period(days, vacations, seed=123)["schedule"]
        rerolled = generate_period(days, vacations, seed=456)["schedule"]
        self.assertEqual(first, repeated)
        self.assertNotEqual(
            [day["assignment"] for day in first],
            [day["assignment"] for day in rerolled],
        )

    def test_vacation_breaks_consecutive_b(self):
        target = "子紘"
        schedule = [
            {"date": "2026-09-01", "day_type": "NORMAL", "assignment": {target: "B"}},
            {"date": "2026-09-02", "day_type": "NORMAL", "assignment": {}},
            {"date": "2026-09-03", "day_type": "NORMAL", "assignment": {target: "B"}},
            {"date": "2026-09-04", "day_type": "NORMAL", "assignment": {target: "B"}},
        ]
        vacations = {name: [] for name in EMPLOYEES}
        vacations[target] = ["2026-09-02"]
        stats = calculate_stats(schedule, vacations)
        target_stats = next(item for item in stats["employees"] if item["name"] == target)
        self.assertEqual(target_stats["consecutive_b_occurrences"], 1)
        self.assertEqual(target_stats["longest_b_streak"], 2)
        self.assertEqual(target_stats["ending_b_streak"], 2)

    def test_off_and_unassigned_also_break_consecutive_b(self):
        target = "子紘"
        schedule = [
            {"date": "2026-09-01", "day_type": "NORMAL", "assignment": {target: "B"}},
            {"date": "2026-09-02", "day_type": "OFF", "assignment": {}},
            {"date": "2026-09-03", "day_type": "NORMAL", "assignment": {target: "B"}},
            {"date": "2026-09-04", "day_type": "CUSTOM", "assignment": {}},
            {"date": "2026-09-05", "day_type": "NORMAL", "assignment": {target: "B"}},
        ]
        stats = calculate_stats(schedule, {name: [] for name in EMPLOYEES})
        target_stats = next(item for item in stats["employees"] if item["name"] == target)
        self.assertEqual(target_stats["consecutive_b_occurrences"], 0)
        self.assertEqual(target_stats["longest_b_streak"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
