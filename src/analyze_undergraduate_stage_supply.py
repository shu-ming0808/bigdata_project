"""Study first English-course entry against stage-aligned offering proxies.

All exports are aggregates. Course-code thousands are a proxy for course level,
not an official prerequisite or a student's actual eligibility to enroll.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from analyze_undergraduate_eight_plus import COLLEGES, summarize
from english_taught_analysis import DEFAULT_MYSQL, HERE, TERMS, frame
from run_dual_project_stats import student_term_data


def offering_data(args: argparse.Namespace) -> pd.DataFrame:
    terms = ",".join(f"'{term}'" for term in TERMS)
    offerings = frame(args.mysql, args.login_path, args.database, f"""
        SELECT o.offering_id, o.term_code, o.department_code,
               o.course_code, r.degree_level_name AS degree_level,
               r.offering_grade_level
        FROM course_offerings o
        JOIN course_offering_raw r ON r.offering_row_id = o.offering_id
        LEFT JOIN offering_english_level l ON l.offering_id = o.offering_id
        WHERE o.term_code IN ({terms})
          AND o.offering_status_raw = '正常'
          AND o.teaching_language_raw = '英語'
          AND COALESCE(o.course_code, '') NOT LIKE 'LN%'
          AND COALESCE(o.course_name, '') NOT REGEXP
              '大一英文|進修英文|TOEIC|英文能力鑑定|英語能力鑑定'
          AND COALESCE(l.english_level, '') NOT IN
              ('beginner', 'intermediate', 'advanced')
    """)
    offerings["offering_id"] = pd.to_numeric(offerings.offering_id)
    offerings["college"] = offerings.department_code.fillna("").str[:1].map(COLLEGES)
    offerings["code_level"] = pd.to_numeric(
        offerings.course_code.fillna("").str.extract(
            r"^[A-Za-z]+([1-4])\d{3}$", expand=False), errors="coerce")
    offerings["degree_level"] = offerings.degree_level.fillna("")
    offerings["offering_grade_level"] = offerings.offering_grade_level.fillna("")
    return offerings


def stage_supply(offerings: pd.DataFrame, bachelor_only: bool = True) -> pd.DataFrame:
    usable = offerings.loc[offerings.college.notna()].copy()
    if bachelor_only:
        usable = usable.loc[usable.degree_level.eq("學士班")].copy()
    all_local = usable.groupby(["term_code", "college"], observed=True).size(
    ).rename("all_local_bachelor_english")
    level = usable.loc[usable.code_level.notna()].copy()
    grid = pd.MultiIndex.from_product(
        [TERMS, list(COLLEGES.values()), range(1, 5)],
        names=["term_code", "college", "assumed_year"])
    result = pd.DataFrame(index=grid).reset_index()
    result["code_level"] = result.assumed_year
    exact = level.groupby(["term_code", "college", "code_level"], observed=True
                          ).size().rename("same_year_offerings")
    result = result.join(exact, on=["term_code", "college", "code_level"])
    result = result.join(all_local, on=["term_code", "college"])
    cum = []
    for year in range(1, 5):
        part = level.loc[level.code_level.le(year)].groupby(
            ["term_code", "college"], observed=True).size().rename(
                "up_to_year_offerings")
        cum.append(result.loc[result.assumed_year.eq(year),
                               ["term_code", "college", "assumed_year"]].join(
                                   part, on=["term_code", "college"]))
    cumulative = pd.concat(cum, ignore_index=True)
    result = result.merge(cumulative, on=["term_code", "college", "assumed_year"],
                          how="left", validate="one_to_one")
    counts = ["same_year_offerings", "up_to_year_offerings",
              "all_local_bachelor_english"]
    result[counts] = result[counts].fillna(0).astype(int)
    return result.drop(columns="code_level")


def department_stage_supply(offerings: pd.DataFrame,
                            cohort: pd.DataFrame) -> pd.DataFrame:
    keys = ["term_code", "current_department_code", "assumed_year"]
    grid = cohort[keys].drop_duplicates().copy()
    bachelor = offerings.loc[offerings.degree_level.eq("學士班")].copy()
    bachelor = bachelor.rename(columns={"department_code": "current_department_code"})
    levels = bachelor.loc[bachelor.code_level.notna()].copy()
    total = bachelor.groupby(["term_code", "current_department_code"],
                             observed=True).size().rename("all_department_offerings")
    grid = grid.join(total, on=["term_code", "current_department_code"])
    year_parts = []
    for year in range(1, 5):
        counts = levels.loc[levels.code_level.le(year)].groupby(
            ["term_code", "current_department_code"], observed=True).size(
            ).rename("department_up_to_year_offerings")
        year_parts.append(grid.loc[grid.assumed_year.eq(year), keys].join(
            counts, on=["term_code", "current_department_code"]))
    cumulative = pd.concat(year_parts, ignore_index=True)
    grid = grid.merge(cumulative, on=keys, how="left", validate="one_to_one")
    columns = ["all_department_offerings", "department_up_to_year_offerings"]
    grid[columns] = grid[columns].fillna(0).astype(int)
    return grid


def first_start_risk(cohort: pd.DataFrame, supply: pd.DataFrame) -> pd.DataFrame:
    rows = cohort.copy()
    rows["assumed_year"] = (rows.position + 1) // 2
    rows = rows.merge(supply, on=["term_code", "college", "assumed_year"],
                      how="left", validate="many_to_one")
    if rows.up_to_year_offerings.isna().any():
        raise ValueError("Some student-term rows have no supply-grid match")
    rows = rows.sort_values(["student_key", "position"])
    rows["prior_english"] = (rows.groupby("student_key", sort=False).english_yes
                             .cumsum() - rows.english_yes.astype(int))
    risk = rows.loc[rows.prior_english.eq(0)].copy()
    risk["first_start"] = risk.english_yes.astype(int)
    return risk


def supply_model(risk: pd.DataFrame, column: str,
                 department_control: bool = False) -> dict:
    unit = "current_department_code" if department_control else "college"
    data = risk[[column, "position", unit, "first_observed_term"]].copy()
    data[column] = np.log1p(data[column].astype(float))
    design_frame = pd.get_dummies(
        data, columns=["position", unit, "first_observed_term"],
        drop_first=True, dtype=float)
    x = design_frame.to_numpy(dtype=float)
    y = risk.first_start.to_numpy(dtype=int)
    model = LogisticRegression(C=1e6, max_iter=800, solver="lbfgs")
    model.fit(x, y)
    coefficient_index = design_frame.columns.get_loc(column)
    coefficient = float(model.coef_[0, coefficient_index])
    p = model.predict_proba(x)[:, 1]
    full_design = np.column_stack([np.ones(len(x)), x])
    info = full_design.T @ (full_design * (p * (1 - p))[:, None])
    bread = np.linalg.pinv(info)
    scores = pd.DataFrame(full_design * (y - p)[:, None])
    scores["supply_group"] = (risk[unit].astype(str) + ":" +
                              risk.term_code.astype(str)).to_numpy()
    group_scores = scores.groupby("supply_group", sort=False).sum().to_numpy()
    covariance = bread @ (group_scores.T @ group_scores) @ bread
    se = float(np.sqrt(max(0.0, covariance[
        coefficient_index + 1, coefficient_index + 1])))
    scale = np.log(2)
    return {
        "supply_variable": column,
        "at_risk_student_terms": len(risk),
        "first_starts": int(risk.first_start.sum()),
        "odds_ratio_per_doubling_of_1_plus_offerings": round(
            float(np.exp(scale * coefficient)), 3),
        "exposure_group_cluster_95pct_interval": [
            round(float(np.exp(scale * (coefficient - 1.96 * se))), 3),
            round(float(np.exp(scale * (coefficient + 1.96 * se))), 3)],
        "exposure_group_clusters": int(scores.supply_group.nunique()),
        "adjusted_for": ["observed_term_position", unit,
                         "first_observed_term"],
        "note": "Observational association; course code level is not official eligibility",
    }


def start_course_profile(risk: pd.DataFrame, attempts: pd.DataFrame,
                         offerings: pd.DataFrame, output_dir: Path) -> dict:
    starts = risk.loc[risk.first_start.eq(1),
                      ["student_key", "term_code", "college",
                       "current_department_code", "assumed_year"]]
    chosen = attempts.loc[attempts.selected & attempts.target &
                          attempts.teaching_language.eq("英語"),
                          ["student_key", "term_code", "offering_id"]]
    selected = chosen.merge(starts, on=["student_key", "term_code"],
                            how="inner", validate="many_to_one")
    selected = selected.merge(
        offerings[["offering_id", "college", "department_code",
                   "degree_level", "code_level"]],
        on="offering_id", how="left", validate="many_to_one",
        suffixes=("_student", "_offering"))
    selected["cross_college"] = selected.college_student.ne(selected.college_offering)
    selected["cross_department"] = selected.current_department_code.ne(
        selected.department_code)
    selected["non_bachelor"] = selected.degree_level.ne("學士班")
    selected["course_level_above_year"] = selected.code_level.gt(selected.assumed_year)
    degree = selected.groupby("degree_level", observed=True).size().rename(
        "selected_course_rows").reset_index().sort_values(
            "selected_course_rows", ascending=False)
    degree.to_csv(output_dir / "first_start_course_degree_levels.csv",
                  index=False, encoding="utf-8-sig")
    stage = selected.groupby(["assumed_year", "code_level"], observed=True).size(
    ).rename("selected_course_rows").reset_index()
    stage.to_csv(output_dir / "selected_code_level_by_assumed_year.csv",
                 index=False, encoding="utf-8-sig")
    by_student = selected.groupby("student_key", observed=True).agg(
        any_cross_college=("cross_college", "max"),
        all_cross_college=("cross_college", "min"),
        any_cross_department=("cross_department", "max"),
        all_cross_department=("cross_department", "min"),
        any_non_bachelor=("non_bachelor", "max"),
        any_above_year=("course_level_above_year", "max"),
    )
    by_student = starts.merge(by_student, on="student_key", how="left",
                              validate="one_to_one")
    by_college_year = by_student.groupby(["college", "assumed_year"],
                                        observed=True).agg(
        first_starters=("student_key", "size"),
        any_cross_college=("any_cross_college", "sum"),
        only_cross_college=("all_cross_college", "sum"),
        any_non_bachelor=("any_non_bachelor", "sum"),
    ).reset_index()
    by_college_year.to_csv(output_dir / "first_start_course_source_by_college_year.csv",
                           index=False, encoding="utf-8-sig")
    return {
        "first_start_students": len(starts),
        "first_start_course_rows": len(selected),
        "students_with_any_cross_college_course_at_start": int(
            by_student.any_cross_college.sum()),
        "students_with_only_cross_college_courses_at_start": int(
            by_student.all_cross_college.sum()),
        "students_with_any_cross_department_course_at_start": int(
            by_student.any_cross_department.sum()),
        "students_with_only_cross_department_courses_at_start": int(
            by_student.all_cross_department.sum()),
        "students_with_any_non_bachelor_course_at_start": int(
            by_student.any_non_bachelor.sum()),
        "students_with_any_code_level_above_assumed_year": int(
            by_student.any_above_year.sum()),
        "first_start_course_rows_by_degree_level": {
            str(row.degree_level or "未知"): int(row.selected_course_rows)
            for row in degree.itertuples(index=False)
        },
    }


def analyze(args: argparse.Namespace) -> dict:
    roster, attempts, _ = student_term_data(
        args, degree_scope="observed_undergraduate", exclude_english_major=False)
    cohort_summary, _, _, cohort = summarize(roster)
    current_college = roster[["student_key", "term_code", "department_code"]].copy()
    current_college["current_college"] = (
        current_college.department_code.fillna("").str[:1].map(COLLEGES))
    college_audit = cohort[["student_key", "term_code", "college"]].merge(
        current_college[["student_key", "term_code", "current_college",
                         "department_code"]],
        on=["student_key", "term_code"], how="left", validate="one_to_one")
    changed_college_student_terms = int(
        college_audit.current_college.ne(college_audit.college).sum())
    cohort = cohort.drop(columns="college").merge(
        college_audit[["student_key", "term_code", "current_college",
                       "department_code"]],
        on=["student_key", "term_code"], how="left", validate="one_to_one"
    ).rename(columns={"current_college": "college",
                      "department_code": "current_department_code"})
    english_major_students = set(cohort.loc[
        cohort.current_department_code.eq("1002"), "student_key"])
    cohort["english_major"] = cohort.student_key.isin(english_major_students)
    offerings = offering_data(args)
    bachelor = offerings.loc[offerings.degree_level.eq("學士班")]
    declared_years = {"一年級": 1, "二年級": 2, "三年級": 3, "四年級": 4}
    declared = bachelor.loc[bachelor.offering_grade_level.isin(declared_years)].copy()
    declared["declared_level"] = declared.offering_grade_level.map(declared_years)
    supply = stage_supply(offerings)
    broad = stage_supply(offerings, bachelor_only=False).rename(columns={
        "same_year_offerings": "broad_same_year_offerings",
        "up_to_year_offerings": "broad_up_to_year_offerings",
        "all_local_bachelor_english": "all_local_english",
    })
    supply = supply.merge(broad, on=["term_code", "college", "assumed_year"],
                          validate="one_to_one")
    cohort["assumed_year"] = (cohort.position + 1) // 2
    department_supply = department_stage_supply(offerings, cohort)
    cohort = cohort.merge(department_supply,
                          on=["term_code", "current_department_code", "assumed_year"],
                          how="left", validate="many_to_one")
    risk = first_start_risk(cohort, supply)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    by_group = risk.groupby(["college", "assumed_year"], observed=True).agg(
        at_risk=("student_key", "size"),
        first_starts=("first_start", "sum"),
        mean_same_year_offerings=("same_year_offerings", "mean"),
        mean_up_to_year_offerings=("up_to_year_offerings", "mean"),
        mean_broad_up_to_year_offerings=("broad_up_to_year_offerings", "mean"),
        mean_all_local_offerings=("all_local_bachelor_english", "mean"),
        mean_department_up_to_year_offerings=(
            "department_up_to_year_offerings", "mean"),
        zero_same_year_terms=("same_year_offerings", lambda s: int(s.eq(0).sum())),
        zero_up_to_year_terms=("up_to_year_offerings", lambda s: int(s.eq(0).sum())),
        zero_broad_up_to_year_terms=(
            "broad_up_to_year_offerings", lambda s: int(s.eq(0).sum())),
        zero_department_up_to_year_terms=(
            "department_up_to_year_offerings", lambda s: int(s.eq(0).sum())),
    ).reset_index()
    by_group["first_start_pct"] = (
        100 * by_group.first_starts / by_group.at_risk).round(2)
    for column in by_group.columns:
        if column.startswith("mean_"):
            by_group[column] = by_group[column].round(2)
    by_group["zero_up_to_year_pct"] = (
        100 * by_group.zero_up_to_year_terms / by_group.at_risk).round(2)
    by_group["zero_department_up_to_year_pct"] = (
        100 * by_group.zero_department_up_to_year_terms / by_group.at_risk).round(2)
    by_group.to_csv(output_dir / "stage_supply_by_college_year.csv", index=False,
                    encoding="utf-8-sig")
    no_major = risk.loc[~risk.english_major].groupby(
        ["college", "assumed_year"], observed=True).agg(
            at_risk=("student_key", "size"),
            first_starts=("first_start", "sum"),
            mean_up_to_year_offerings=("up_to_year_offerings", "mean"),
            mean_department_up_to_year_offerings=(
                "department_up_to_year_offerings", "mean"),
            zero_up_to_year_terms=(
                "up_to_year_offerings", lambda s: int(s.eq(0).sum())),
            zero_department_up_to_year_terms=(
                "department_up_to_year_offerings", lambda s: int(s.eq(0).sum())),
        ).reset_index()
    no_major["first_start_pct"] = (
        100 * no_major.first_starts / no_major.at_risk).round(2)
    for column in ["mean_up_to_year_offerings",
                   "mean_department_up_to_year_offerings"]:
        no_major[column] = no_major[column].round(2)
    no_major["zero_up_to_year_pct"] = (
        100 * no_major.zero_up_to_year_terms / no_major.at_risk).round(2)
    no_major["zero_department_up_to_year_pct"] = (
        100 * no_major.zero_department_up_to_year_terms / no_major.at_risk
    ).round(2)
    no_major.to_csv(output_dir / "stage_supply_by_college_year_no_english_major.csv",
                    index=False, encoding="utf-8-sig")

    by_position = risk.groupby("position", observed=True).agg(
        at_risk=("student_key", "size"), first_starts=("first_start", "sum"),
        mean_same_year_offerings=("same_year_offerings", "mean"),
        mean_up_to_year_offerings=("up_to_year_offerings", "mean"),
        mean_broad_up_to_year_offerings=("broad_up_to_year_offerings", "mean"),
        zero_up_to_year_terms=("up_to_year_offerings", lambda s: int(s.eq(0).sum())),
    ).reset_index()
    by_position["first_start_pct"] = (
        100 * by_position.first_starts / by_position.at_risk).round(2)
    for column in ["mean_same_year_offerings", "mean_up_to_year_offerings",
                   "mean_broad_up_to_year_offerings"]:
        by_position[column] = by_position[column].round(2)
    by_position.to_csv(output_dir / "stage_supply_by_position.csv", index=False,
                       encoding="utf-8-sig")

    risk["any_up_to_year_offering"] = risk.up_to_year_offerings.gt(0)
    zero = risk.groupby(["assumed_year", "any_up_to_year_offering"],
                        observed=True).agg(
                            at_risk=("student_key", "size"),
                            first_starts=("first_start", "sum")
                        ).reset_index()
    zero["first_start_pct"] = (
        100 * zero.first_starts / zero.at_risk).round(2)
    zero.to_csv(output_dir / "stage_supply_zero_vs_positive.csv",
                index=False, encoding="utf-8-sig")
    within = risk.groupby(["college", "assumed_year", "any_up_to_year_offering"],
                          observed=True).agg(
                              at_risk=("student_key", "size"),
                              first_starts=("first_start", "sum")
                          ).reset_index()
    within["first_start_pct"] = (
        100 * within.first_starts / within.at_risk).round(2)
    within.to_csv(output_dir / "stage_supply_zero_vs_positive_by_college_year.csv",
                  index=False, encoding="utf-8-sig")

    result = {
        "cohort_students": cohort_summary[
            "students_with_eight_or_more_consecutive_terms_from_first_visible_term"],
        "at_risk_student_terms": len(risk),
        "first_starts": int(risk.first_start.sum()),
        "english_major_students": int(cohort.loc[cohort.english_major, "student_key"].nunique()),
        "student_terms_with_college_changed_from_first_visible":
            changed_college_student_terms,
        "students_with_college_changed_from_first_visible": int(
            college_audit.loc[college_audit.current_college.ne(
                college_audit.college), "student_key"].nunique()),
        "first_starters_with_zero_local_stage_supply": int(
            (risk.first_start.eq(1) & risk.up_to_year_offerings.eq(0)).sum()),
        "first_starters_with_zero_own_department_stage_supply": int(
            (risk.first_start.eq(1) &
             risk.department_up_to_year_offerings.eq(0)).sum()),
        "bachelor_english_offerings": len(bachelor),
        "bachelor_english_offerings_with_code_level_1_to_4": int(
            bachelor.code_level.notna().sum()),
        "bachelor_english_offerings_with_explicit_year_1_to_4": len(declared),
        "explicit_year_equal_to_code_level": int(
            declared.declared_level.eq(declared.code_level).sum()),
        "same_college_year_or_lower_supply_model": supply_model(
            risk, "up_to_year_offerings"),
        "same_department_year_or_lower_supply_model": supply_model(
            risk, "department_up_to_year_offerings", department_control=True),
        "same_department_excluding_english_major_model": supply_model(
            risk.loc[~risk.english_major],
            "department_up_to_year_offerings", department_control=True),
        "first_two_assumed_years_stage_supply_model": supply_model(
            risk.loc[risk.assumed_year.le(2)], "up_to_year_offerings"),
        "first_two_assumed_years_excluding_english_major_model": supply_model(
            risk.loc[risk.assumed_year.le(2) & ~risk.english_major],
            "up_to_year_offerings"),
        "last_two_assumed_years_stage_supply_model": supply_model(
            risk.loc[risk.assumed_year.ge(3)], "up_to_year_offerings"),
        "all_degree_labels_year_or_lower_supply_model": supply_model(
            risk, "broad_up_to_year_offerings"),
        "excluding_english_major_stage_supply_model": supply_model(
            risk.loc[~risk.english_major], "up_to_year_offerings"),
        "same_college_all_bachelor_supply_model": supply_model(
            risk, "all_local_bachelor_english"),
        "first_start_course_profile": start_course_profile(
            risk, attempts, offerings, output_dir),
        "limitations": [
            "code thousands are a stage proxy, not an official grade restriction",
            "first visible semester is not a verified admission semester",
            "cross-college courses, seats, prerequisites, and timetable are not eligibility data",
            "same-term availability and first entry are observational, not causal",
            "uncertainty clusters at the supply exposure group (college-term or department-term)",
        ],
        "student_identifiers_exported": False,
    }
    (output_dir / "stage_supply_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql", type=Path, default=DEFAULT_MYSQL)
    parser.add_argument("--login-path", default="codex-local")
    parser.add_argument("--database", default="ncu_course_flow_1150012")
    parser.add_argument("--department-rules", type=Path,
                        default=HERE / "undergraduate_department_rules.json")
    parser.add_argument("--output-dir", type=Path,
                        default=HERE / "outputs" / "undergraduate_stage_supply")
    args = parser.parse_args()
    print(json.dumps(analyze(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
