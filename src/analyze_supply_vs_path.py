"""比較固定八學期路徑與「起始系所同學期開課」供給代理指標。

同系開課不等於學生符合資格、沒有衝堂或實際有名額；輸出只含彙總。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from analyze_pathways_course_types import MIN_GROUP, department_names, make_eight_cohort
from analyze_trends_sequences import supply_by_term_department
from english_taught_analysis import DEFAULT_MYSQL, HERE
from run_dual_project_stats import save_csv, source_completeness_by_term, student_term_data


def attach_same_department_supply(terms: pd.DataFrame, students: pd.DataFrame,
                                  supply: pd.DataFrame) -> pd.DataFrame:
    own = students[["student_key", "first_observed_term", "initial_department_code",
                    "path_type", "late_only"]]
    rows = terms.merge(own, on="student_key", validate="many_to_one")
    all_degrees = supply.groupby(["term_code", "offering_department_code"], as_index=False)[
        "english_offerings"
    ].sum().rename(columns={"english_offerings": "same_department_english_offerings"})
    bachelor = supply.loc[supply.degree_level.eq("學士班")].groupby(
        ["term_code", "offering_department_code"], as_index=False
    )["english_offerings"].sum().rename(columns={
        "english_offerings": "same_department_bachelor_english_offerings"
    })
    for offer in [all_degrees, bachelor]:
        rows = rows.merge(offer, left_on=["term_code", "initial_department_code"],
                          right_on=["term_code", "offering_department_code"],
                          how="left", validate="many_to_one")
        rows = rows.drop(columns="offering_department_code")
    columns = ["same_department_english_offerings",
               "same_department_bachelor_english_offerings"]
    rows[columns] = rows[columns].fillna(0).astype(int)
    if len(rows) != 8 * len(students):
        raise ValueError("供給合併使固定八學期學生學期數改變")
    return rows


def by_assumed_year(rows: pd.DataFrame, groups: list[str], minimum: int) -> pd.DataFrame:
    result = rows.groupby(groups, dropna=False).agg(
        student_terms=("student_key", "size"),
        participating_terms=("english_yes", "sum"),
        mean_same_department_english_offerings=(
            "same_department_english_offerings", "mean"),
        mean_same_department_bachelor_english_offerings=(
            "same_department_bachelor_english_offerings", "mean"),
        student_terms_with_same_department_english_offering=(
            "same_department_english_offerings", lambda x: int(x.gt(0).sum())),
    ).reset_index()
    result = result.loc[result.student_terms.ge(minimum)].copy()
    result["participation_pct"] = (
        100 * result.participating_terms / result.student_terms
    ).round(2)
    result["same_department_supply_present_pct"] = (
        100 * result.student_terms_with_same_department_english_offering /
        result.student_terms
    ).round(2)
    for column in ["mean_same_department_english_offerings",
                   "mean_same_department_bachelor_english_offerings"]:
        result[column] = result[column].round(2)
    return result.sort_values(groups)


def student_supply_profile(rows: pd.DataFrame, students: pd.DataFrame) -> pd.DataFrame:
    rows = rows.copy()
    rows["half"] = rows.position.le(4).map({True: "early", False: "late"})
    totals = rows.groupby(["student_key", "half"], observed=True).agg(
        own_english=("same_department_english_offerings", "sum"),
        own_bachelor_english=("same_department_bachelor_english_offerings", "sum"),
    ).unstack("half")
    totals.columns = [f"{half}_{metric}" for metric, half in totals.columns]
    totals = totals.reset_index()
    result = students.merge(totals, on="student_key", validate="one_to_one")
    result["late_supply_exceeds_early"] = (
        result.late_own_english > result.early_own_english
    )
    result["early_supply_absent"] = result.early_own_english.eq(0)
    result["early_bachelor_supply_absent"] = result.early_own_bachelor_english.eq(0)
    result["late_bachelor_supply_exceeds_early"] = (
        result.late_own_bachelor_english > result.early_own_bachelor_english
    )
    return result


def group_student_supply(students: pd.DataFrame, groups: list[str], minimum: int):
    result = students.groupby(groups, dropna=False).agg(
        students=("student_key", "size"),
        late_only_students=("late_only", "sum"),
        mean_early_english_offerings=("early_own_english", "mean"),
        mean_late_english_offerings=("late_own_english", "mean"),
        mean_early_bachelor_english_offerings=("early_own_bachelor_english", "mean"),
        mean_late_bachelor_english_offerings=("late_own_bachelor_english", "mean"),
        students_with_no_early_same_department_supply=("early_supply_absent", "sum"),
        students_with_no_early_same_department_bachelor_supply=(
            "early_bachelor_supply_absent", "sum"),
        students_with_late_supply_increase=("late_supply_exceeds_early", "sum"),
        students_with_late_bachelor_supply_increase=(
            "late_bachelor_supply_exceeds_early", "sum"),
    ).reset_index()
    result = result.loc[result.students.ge(minimum)].copy()
    result["late_only_pct"] = (100 * result.late_only_students / result.students).round(2)
    result["no_early_supply_pct"] = (
        100 * result.students_with_no_early_same_department_supply / result.students
    ).round(2)
    result["no_early_bachelor_supply_pct"] = (
        100 * result.students_with_no_early_same_department_bachelor_supply /
        result.students
    ).round(2)
    result["late_supply_increase_pct"] = (
        100 * result.students_with_late_supply_increase / result.students
    ).round(2)
    result["late_bachelor_supply_increase_pct"] = (
        100 * result.students_with_late_bachelor_supply_increase / result.students
    ).round(2)
    for column in result.columns:
        if column.startswith("mean_"):
            result[column] = result[column].round(2)
    return result.sort_values(groups)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql", type=Path, default=DEFAULT_MYSQL)
    parser.add_argument("--login-path", default="codex-local")
    parser.add_argument("--database", default="ncu_course_flow_1150012")
    parser.add_argument("--department-rules", type=Path,
                        default=HERE / "undergraduate_department_rules.json")
    parser.add_argument("--output-dir", type=Path,
                        default=HERE / "outputs" / "supply_vs_path_1051_1142")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    roster, _, _ = student_term_data(args)
    completeness = source_completeness_by_term(args)
    complete_terms = completeness.loc[
        completeness.credit_nonblank_pct.ge(50) & completeness.grade_nonblank_pct.ge(50),
        "term_code",
    ].tolist()
    students, terms = make_eight_cohort(roster, complete_terms)
    previous = json.loads((HERE / "outputs" / "trends_sequences_1051_1151" /
                           "summary.json").read_text(encoding="utf-8"))
    if len(students) != previous["sequence_audit"]["eligible_eight_consecutive_terms"]:
        raise ValueError("八學期資格人數與前次稽核不符")
    supply = supply_by_term_department(args)
    rows = attach_same_department_supply(terms, students, supply)
    profiles = student_supply_profile(rows, students)
    names = department_names(args)
    outputs = {
        "supply_and_participation_by_assumed_year.csv": by_assumed_year(
            rows, ["assumed_year"], 0),
        "supply_and_participation_by_first_term_year.csv": by_assumed_year(
            rows, ["first_observed_term", "assumed_year"], MIN_GROUP),
        "supply_and_participation_by_department_year.csv": by_assumed_year(
            rows, ["initial_department_code", "assumed_year"], MIN_GROUP,
        ).merge(names, on="initial_department_code", how="left", validate="many_to_one"),
        "supply_and_participation_by_first_term_department_year.csv": by_assumed_year(
            rows, ["first_observed_term", "initial_department_code", "assumed_year"],
            MIN_GROUP,
        ).merge(names, on="initial_department_code", how="left", validate="many_to_one"),
        "supply_profile_by_path_type.csv": group_student_supply(
            profiles, ["path_type"], 0),
        "supply_profile_by_first_term.csv": group_student_supply(
            profiles, ["first_observed_term"], MIN_GROUP),
        "supply_profile_by_initial_department.csv": group_student_supply(
            profiles, ["initial_department_code"], MIN_GROUP,
        ).merge(names, on="initial_department_code", how="left", validate="many_to_one"),
        "supply_profile_by_first_term_department.csv": group_student_supply(
            profiles, ["first_observed_term", "initial_department_code"], MIN_GROUP,
        ).merge(names, on="initial_department_code", how="left", validate="many_to_one"),
    }
    for filename, data in outputs.items():
        save_csv(data, args.output_dir / filename)
    report = {
        "eligible_students": len(students),
        "student_terms": len(rows),
        "assumed_year_one_is_first_observed_term": True,
        "supply_proxy": "同一學生起始系所於該學期正常開設、排除語言學習課的英語授課班次；另列學士班子集。",
        "not_measured": ["個別選課資格", "先修與衝堂", "實際名額", "跨系所可選課程", "修課動機"],
        "minimum_published_group_size": MIN_GROUP,
        "no_individual_rows_exported": True,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"完成：{len(students)} 人、{len(rows)} 學生學期；輸出 {len(outputs)} 份彙總表")


if __name__ == "__main__":
    main()
