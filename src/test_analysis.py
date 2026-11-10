"""研究邏輯的合成資料檢查；不連接資料庫。"""
import unittest

import pandas as pd

from english_taught_analysis import assign_prior_levels, stage_two, within_model


class TemporalAnalysisTests(unittest.TestCase):
    def test_prior_level_does_not_use_same_or_future_term(self):
        cohort = pd.DataFrame({
            "student_key": [1, 1, 1, 1],
            "term_code": ["1101", "1102", "1111", "1112"],
        })
        attempts = pd.DataFrame({
            "student_key": [1, 1],
            "term_code": ["1101", "1111"],
            "english_level": ["beginner", "advanced"],
            "selected": [True, True],
        })
        observed = assign_prior_levels(cohort, attempts).prior_level.tolist()
        self.assertEqual(observed, ["unknown", "beginner", "beginner", "advanced"])

    def test_flow_requires_two_consecutive_observed_terms(self):
        roster = pd.DataFrame({
            "student_key": [1, 1, 2, 2],
            "term_code": ["1101", "1111", "1101", "1102"],
            "prior_level": ["unknown"] * 4,
            "english_yes": [False, True, False, True],
        })
        pairs, result = stage_two(roster)
        self.assertEqual(len(pairs), 1)
        started = next(row for row in result if row["本學期前可見英文級別"] == "未知"
                       and row["相鄰學期流向"] == "未觀察到→有修讀")
        self.assertEqual(started["人次"], 1)
        self.assertEqual(started["同一起點人次"], 1)

    def test_within_course_term_model_recovers_known_difference(self):
        rows = []
        for course, baseline in [("A", 62), ("B", 83)]:
            for term in ["1101", "1102"]:
                for n in range(20):
                    english = n % 2 == 0
                    prior = 55 + (n // 2) * 2
                    rows.append({
                        "course_code": course,
                        "comparison_group": course + ":" + term,
                        "teaching_language": "英語" if english else "國語",
                        "grade_num": baseline + 2 * english + 0.1 * prior,
                        "prior_average": prior,
                        "prior_level": "unknown",
                        "department_code": "1001",
                    })
        fit = within_model(pd.DataFrame(rows), adjusted=True)
        self.assertIsNotNone(fit)
        self.assertAlmostEqual(fit["英文班減國語班_調整後分數差"], 2, places=3)


if __name__ == "__main__":
    unittest.main()
