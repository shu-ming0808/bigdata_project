"""Eight-or-more consecutive observed undergraduate semesters, aggregate only.

Semester positions 1–2 are *assumed* year 1, 3–4 year 2, etc. Missing
semester degree labels are accepted only when the student has an explicit
undergraduate label elsewhere and before any explicit graduate label.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from english_taught_analysis import DEFAULT_MYSQL, HERE
from run_dual_project_stats import student_term_data


COLLEGES = {
    "1": "文學院", "2": "理學院", "3": "工學院", "4": "管理學院",
    "5": "資訊電機學院", "6": "地球科學學院", "7": "客家學院",
    "8": "生醫理工學院",
}


def summarize(roster: pd.DataFrame) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    years: dict[int, Counter] = {}
    paths = Counter()
    eligible = 0
    at_least_eight_observed = 0
    with_english = 0
    newest_incomplete = 0
    seven_then_missing_eighth = 0
    cohort_terms = []
    observed_students = int(roster.student_key.nunique())
    newest_order = int(roster.order.max())
    for student_key, part in roster.sort_values(["student_key", "order"]).groupby(
            "student_key", sort=False):
        orders = part.order.to_numpy(dtype=int)
        if orders[-1] == newest_order and len(orders) < 8:
            newest_incomplete += 1
        if len(orders) >= 8:
            at_least_eight_observed += 1
        segment_length = 1
        while (segment_length < len(orders) and
               orders[segment_length] == orders[segment_length - 1] + 1):
            segment_length += 1
        if (segment_length == 7 and orders[0] + 7 <= newest_order and
                not (orders[-1] == newest_order and len(orders) < 8)):
            seven_then_missing_eighth += 1
        if segment_length < 8:
            continue
        eligible += 1
        yes = part.english_yes.to_numpy(dtype=bool)[:segment_length]
        college = COLLEGES.get(str(part.department_code.iloc[0])[:1], "未知學院")
        start_term = str(part.term_code.iloc[0])
        with_english += int(yes[:8].any())
        early, late = bool(yes[:4].any()), bool(yes[4:8].any())
        name = ("前後四學期皆有" if early and late else
                "僅前四學期" if early else
                "僅後四學期" if late else "前八學期未修")
        paths[name] += 1
        for position, active in enumerate(yes, start=1):
            year = (position + 1) // 2
            years.setdefault(year, Counter())["student_terms"] += 1
            years[year]["english_student_terms"] += int(active)
            if position <= 8:
                cohort_terms.append({
                    "student_key": student_key,
                    "term_code": str(part.term_code.iloc[position - 1]),
                    "position": position,
                    "college": college,
                    "first_observed_term": start_term,
                    "english_yes": active,
                })
    by_year = pd.DataFrame([
        {"assumed_year": year, "student_terms": c["student_terms"],
         "english_student_terms": c["english_student_terms"],
         "participation_pct": round(
             100 * c["english_student_terms"] / c["student_terms"], 2)}
        for year, c in sorted(years.items())
    ])
    by_path = pd.DataFrame([
        {"path_type": name, "students": paths[name],
         "share_pct": round(100 * paths[name] / eligible, 2)}
        for name in ["前八學期未修", "僅前四學期", "僅後四學期", "前後四學期皆有"]
    ])
    summary = {
        "observed_undergraduate_students_denominator": observed_students,
        "newest_term_students_with_fewer_than_eight_observed_terms_excluded_from_share_denominator": newest_incomplete,
        "adjusted_denominator": observed_students - newest_incomplete,
        "first_seven_consecutive_then_eighth_missing_excluded_in_sensitivity": seven_then_missing_eighth,
        "sensitivity_denominator": observed_students - newest_incomplete - seven_then_missing_eighth,
        "students_with_at_least_eight_observed_terms_even_if_gapped": at_least_eight_observed,
        "students_with_eight_or_more_consecutive_terms_from_first_visible_term": eligible,
        "cohort_share_of_adjusted_denominator_pct": round(
            100 * eligible / (observed_students - newest_incomplete), 2),
        "cohort_share_excluding_missing_eighth_pct": round(
            100 * eligible / (observed_students - newest_incomplete - seven_then_missing_eighth), 2),
        "students_with_english_in_first_eight_terms": with_english,
        "degree_scope": "undergraduate department + at least one explicit 大學 label; "
                        "blank labels allowed before any explicit graduate term",
        "grade_estimation": "positions 1–2 -> year 1, 3–4 -> year 2, etc.; "
                            "not verified admission or actual standing",
        "missing_term_rule": "stop at first absent semester; do not treat absence as nonparticipation",
        "outcome_note": "1151 has incomplete grades; participation only",
        "student_identifiers_exported": False,
    }
    return summary, by_year, by_path, pd.DataFrame(cohort_terms)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql", type=Path, default=DEFAULT_MYSQL)
    parser.add_argument("--login-path", default="codex-local")
    parser.add_argument("--database", default="ncu_course_flow_1150012")
    parser.add_argument("--department-rules", type=Path,
                        default=HERE / "undergraduate_department_rules.json")
    parser.add_argument("--output-dir", type=Path,
                        default=HERE / "outputs" / "undergraduate_eight_plus")
    args = parser.parse_args()
    roster, attempts, excluded_language = student_term_data(
        args, degree_scope="observed_undergraduate",
        exclude_english_major=False)
    summary, years, paths, cohort_terms = summarize(roster)
    summary["excluded_language_course_attempts"] = excluded_language
    summary["english_major_included"] = True
    args.output_dir.mkdir(parents=True, exist_ok=True)
    years.to_csv(args.output_dir / "participation_by_assumed_year.csv",
                 index=False, encoding="utf-8-sig")
    paths.to_csv(args.output_dir / "path_types_first_eight.csv",
                 index=False, encoding="utf-8-sig")
    college_year = cohort_terms.assign(
        assumed_year=(cohort_terms.position + 1) // 2
    ).groupby(["college", "assumed_year"], observed=True).agg(
        students=("student_key", "nunique"),
        student_terms=("student_key", "size"),
        english_student_terms=("english_yes", "sum"),
    ).reset_index()
    college_year = college_year.loc[college_year.students.ge(30)].copy()
    college_year["participation_pct"] = (
        100 * college_year.english_student_terms / college_year.student_terms
    ).round(2)
    college_year.to_csv(args.output_dir / "participation_by_college_year.csv",
                        index=False, encoding="utf-8-sig")
    from undergraduate_outcome_model import analyze
    summary["outcome_analysis"] = analyze(
        args, cohort_terms, attempts, COLLEGES, args.output_dir)
    from undergraduate_first_start_supply import analyze as analyze_first_start
    summary["first_start_supply_analysis"] = analyze_first_start(
        args, cohort_terms, COLLEGES, args.output_dir)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
