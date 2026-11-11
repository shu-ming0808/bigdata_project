"""Aggregate undergraduate English-taught course pathways without exporting student IDs.

The first visible semester is not necessarily the actual entrance semester. Only
adjacent observed semesters can establish transitions. English learning courses
and waivers are excluded by the established research definition.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from english_taught_analysis import DEFAULT_MYSQL, HERE, TERMS
from run_dual_project_stats import student_term_data


def aggregate_paths(roster: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    first_event = defaultdict(lambda: Counter())
    transitions = defaultdict(lambda: Counter())
    totals = Counter()
    complete_eight_students = 0
    complete_eight_with_english = 0
    for _, part in roster.sort_values(["student_key", "order"]).groupby("student_key", sort=False):
        orders = part.order.to_numpy(dtype=int)
        yes = part.english_yes.to_numpy(dtype=bool)
        if not len(orders):
            continue
        totals["students"] += 1
        first_segment_end = len(orders)
        for i in range(1, len(orders)):
            if orders[i] != orders[i - 1] + 1:
                first_segment_end = i
                totals["students_with_observation_gap"] += 1
                break
        if len(orders) >= 8 and all(orders[i] == orders[0] + i for i in range(8)):
            complete_eight_students += 1
            complete_eight_with_english += int(yes[:8].any())
        happened = False
        for step, active in enumerate(yes[:first_segment_end], start=1):
            if happened:
                break
            first_event[step]["at_risk"] += 1
            if active:
                first_event[step]["first_visible_english"] += 1
                happened = True
        if happened:
            totals["first_visible_english_in_first_segment"] += 1
        else:
            totals["no_english_before_censoring"] += 1
        for i in range(1, len(orders)):
            if orders[i] != orders[i - 1] + 1:
                continue
            key = (TERMS[orders[i]], int(yes[i - 1]), int(yes[i]))
            transitions[key]["student_pairs"] += 1
    first = pd.DataFrame([
        {"observed_step": step, "at_risk": c["at_risk"],
         "first_visible_english": c["first_visible_english"],
         "first_event_pct": round(100 * c["first_visible_english"] / c["at_risk"], 2)}
        for step, c in sorted(first_event.items())
    ])
    flow = pd.DataFrame([
        {"term_code": term, "from_english": before, "to_english": after,
         "student_pairs": c["student_pairs"]}
        for (term, before, after), c in sorted(transitions.items())
    ])
    summary = {
        **totals,
        "adjacent_student_term_pairs": int(flow.student_pairs.sum()),
        "complete_first_eight_observed_semesters": complete_eight_students,
        "complete_eight_with_any_english": complete_eight_with_english,
        "eight_semesters_interpretation": "可作推定大一至大四視窗；沒有正式入學學期，不能確認實際年級",
        "left_censoring": "首次可見修讀不代表學生人生首次修讀",
        "right_censoring": "缺席學期或資料截止後不判為未修讀",
    }
    return first, flow, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql", type=Path, default=DEFAULT_MYSQL)
    parser.add_argument("--login-path", default="codex-local")
    parser.add_argument("--database", default="ncu_course_flow_1150012")
    parser.add_argument("--department-rules", type=Path,
                        default=HERE / "undergraduate_department_rules.json")
    parser.add_argument("--output-dir", type=Path,
                        default=HERE / "outputs" / "shared_layer")
    args = parser.parse_args()
    roster, _, excluded = student_term_data(args)
    first, flow, summary = aggregate_paths(roster)
    summary["excluded_language_course_attempts"] = excluded
    summary["observed_student_terms"] = len(roster)
    summary["english_participating_student_terms"] = int(roster.english_yes.sum())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    first.to_csv(args.output_dir / "first_english_by_observed_step.csv",
                 index=False, encoding="utf-8-sig")
    flow.to_csv(args.output_dir / "adjacent_term_transitions.csv",
                index=False, encoding="utf-8-sig")
    (args.output_dir / "student_sequence_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
