"""First English-taught course timing and college-level bachelor course supply.

Outputs aggregates only. College offerings are a supply proxy, not proof that
each student was eligible, had an open seat, or could avoid timetable conflicts.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from analyze_trends_sequences import supply_by_term_department


def analyze(args, cohort_terms: pd.DataFrame, colleges: dict[str, str],
            output_dir: Path) -> dict:
    supply = supply_by_term_department(args)
    supply = supply.loc[supply.degree_level.eq("學士班")].copy()
    supply["college"] = supply.offering_department_code.fillna("").str[:1].map(colleges)
    supply = supply.loc[supply.college.notna()].groupby(
        ["term_code", "college"], observed=True, as_index=False
    ).english_offerings.sum().rename(columns={
        "english_offerings": "college_bachelor_english_offerings"})
    rows = cohort_terms.merge(supply, on=["term_code", "college"], how="left",
                              validate="many_to_one")
    rows["college_bachelor_english_offerings"] = pd.to_numeric(
        rows.college_bachelor_english_offerings.fillna(0))
    rows = rows.sort_values(["student_key", "position"])
    rows["previous_english"] = rows.groupby("student_key", sort=False).english_yes.cumsum() - rows.english_yes.astype(int)
    risk = rows.loc[rows.previous_english.eq(0)].copy()
    risk["first_start"] = risk.english_yes.astype(int)
    risk["assumed_year"] = (risk.position + 1) // 2
    risk["log_supply"] = np.log1p(risk.college_bachelor_english_offerings)

    by_position = risk.groupby("position", observed=True).agg(
        at_risk=("student_key", "size"),
        first_starts=("first_start", "sum"),
        mean_college_bachelor_english_offerings=(
            "college_bachelor_english_offerings", "mean"),
    ).reset_index()
    by_position["first_start_pct"] = (
        100 * by_position.first_starts / by_position.at_risk).round(2)
    by_position["mean_college_bachelor_english_offerings"] = (
        by_position.mean_college_bachelor_english_offerings.round(2))
    by_position.to_csv(output_dir / "first_start_by_position.csv", index=False,
                       encoding="utf-8-sig")

    by_college = risk.groupby(["college", "assumed_year"], observed=True).agg(
        at_risk=("student_key", "size"), first_starts=("first_start", "sum"),
        mean_supply=("college_bachelor_english_offerings", "mean"),
    ).reset_index()
    by_college = by_college.loc[by_college.at_risk.ge(30)].copy()
    by_college["first_start_pct"] = (
        100 * by_college.first_starts / by_college.at_risk).round(2)
    by_college["mean_supply"] = by_college.mean_supply.round(2)
    by_college.to_csv(output_dir / "first_start_by_college_year.csv",
                      index=False, encoding="utf-8-sig")

    # One observation per at-risk student/term. The coefficient describes an
    # association for one unit increase in log(1 + available course sections).
    model = risk[["log_supply", "position", "college", "first_observed_term"]].copy()
    xframe = pd.get_dummies(model, columns=["position", "college",
                                            "first_observed_term"],
                            drop_first=True, dtype=float)
    x = xframe.to_numpy(dtype=float)
    y = risk.first_start.to_numpy(dtype=int)
    clf = LogisticRegression(C=1e6, max_iter=600, solver="lbfgs")
    clf.fit(x, y)
    index = xframe.columns.get_loc("log_supply")
    coef = float(clf.coef_[0, index])
    prob = clf.predict_proba(x)[:, 1]
    design = np.column_stack([np.ones(len(x)), x])
    information = design.T @ (design * (prob * (1 - prob))[:, None])
    bread = np.linalg.pinv(information)
    score_rows = pd.DataFrame(design * (y - prob)[:, None])
    score_rows["student_key"] = risk.student_key.to_numpy()
    cluster_scores = score_rows.groupby("student_key", sort=False).sum().to_numpy()
    covariance = bread @ (cluster_scores.T @ cluster_scores) @ bread
    se = float(np.sqrt(max(0.0, covariance[index + 1, index + 1])))
    result = {
        "status": "ok",
        "eligible_students": int(cohort_terms.student_key.nunique()),
        "at_risk_student_terms": len(risk),
        "first_starts": int(risk.first_start.sum()),
        "students_never_starting_in_first_eight": int(
            cohort_terms.student_key.nunique() - risk.first_start.sum()),
        "total_college_bachelor_offerings_at_risk_mean": round(float(
            risk.college_bachelor_english_offerings.mean()), 2),
        "adjusted_odds_ratio_per_unit_log1p_supply": round(float(np.exp(coef)), 3),
        "cluster_robust_95pct_interval": [
            round(float(np.exp(coef - 1.96 * se)), 3),
            round(float(np.exp(coef + 1.96 * se)), 3)],
        "student_clusters_for_uncertainty": int(risk.student_key.nunique()),
        "adjusted_odds_ratio_per_doubling_of_one_plus_supply": round(
            float(np.exp(coef * np.log(2))), 3),
        "doubling_95pct_interval": [
            round(float(np.exp((coef - 1.96 * se) * np.log(2))), 3),
            round(float(np.exp((coef + 1.96 * se) * np.log(2))), 3)],
        "adjusted_for": ["observed_term_position", "college", "first_observed_term"],
        "interpretation": "association only; course availability is a college-level proxy",
        "not_observed": ["individual_course_eligibility", "available_seats",
                         "schedule_conflicts", "student_preference"],
        "student_identifiers_exported": False,
    }
    (output_dir / "first_start_supply_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
