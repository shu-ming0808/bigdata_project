"""Descriptive, time-ordered grade association for the eight-term cohort.

Among students without English-taught professional courses in terms 1–4,
compare those starting in terms 5–6 with those still not participating.
Outcome is credit-weighted grade in Mandarin-taught professional courses in
terms 7–8. No student-level rows are written to disk.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from analyze_trends_sequences import supply_by_term_department


def graded_average(rows: pd.DataFrame, positions: list[int], prefix: str) -> pd.DataFrame:
    subset = rows.loc[rows.position.isin(positions)].copy()
    subset["weighted"] = subset.grade_num * subset.credits_num
    result = subset.groupby("student_key", observed=True).agg(
        weighted=("weighted", "sum"), credits=("credits_num", "sum")
    ).reset_index()
    result[f"{prefix}_score"] = result.weighted / result.credits
    return result[["student_key", f"{prefix}_score", "credits"]].rename(
        columns={"credits": f"{prefix}_credits"})


def analyze(args, cohort_terms: pd.DataFrame, attempts: pd.DataFrame,
            colleges: dict[str, str], output_dir: Path) -> dict:
    first = cohort_terms.loc[cohort_terms.position.le(4)].groupby(
        "student_key", observed=True).english_yes.any().rename("early_english")
    middle = cohort_terms.loc[cohort_terms.position.isin([5, 6])].groupby(
        "student_key", observed=True).english_yes.any().rename("start_in_5_or_6")
    meta = cohort_terms.loc[cohort_terms.position.eq(1),
                            ["student_key", "college", "first_observed_term"]]
    sample = meta.merge(first, on="student_key", validate="one_to_one").merge(
        middle, on="student_key", validate="one_to_one")
    sample = sample.loc[~sample.early_english].copy()

    # Outcome and baseline have the same non-English professional-course definition.
    scored = attempts.loc[
        attempts.target & attempts.score_ok & attempts.credits_num.gt(0) &
        attempts.teaching_language.eq("國語"),
        ["student_key", "term_code", "grade_num", "credits_num"],
    ].copy()
    scored = scored.merge(cohort_terms[["student_key", "term_code", "position"]],
                          on=["student_key", "term_code"], how="inner",
                          validate="many_to_one")
    baseline = graded_average(scored, [1, 2, 3, 4], "baseline")
    outcome = graded_average(scored, [7, 8], "outcome")
    sample = sample.merge(baseline, on="student_key", how="left",
                          validate="one_to_one").merge(
        outcome, on="student_key", how="left", validate="one_to_one")

    supply = supply_by_term_department(args)
    supply = supply.loc[supply.degree_level.eq("學士班")].copy()
    supply["college"] = supply.offering_department_code.fillna("").str[:1].map(colleges)
    supply = supply.loc[supply.college.notna()].groupby(
        ["term_code", "college"], observed=True, as_index=False
    ).english_offerings.sum().rename(columns={
        "english_offerings": "college_bachelor_english_offerings"
    })
    middle_terms = cohort_terms.loc[cohort_terms.position.isin([5, 6]),
                                    ["student_key", "term_code", "college"]]
    middle_terms = middle_terms.merge(supply, on=["term_code", "college"],
                                      how="left", validate="many_to_one")
    middle_terms["college_bachelor_english_offerings"] = (
        middle_terms.college_bachelor_english_offerings.fillna(0))
    supply_per_student = middle_terms.groupby("student_key", observed=True)[
        "college_bachelor_english_offerings"].sum().rename("supply_terms_5_6")
    sample = sample.merge(supply_per_student, on="student_key", how="left",
                          validate="one_to_one")

    at_risk = len(sample)
    sample = sample.loc[
        sample.baseline_credits.ge(6) & sample.outcome_credits.ge(6) &
        sample.baseline_score.between(0, 100) &
        sample.outcome_score.between(0, 100) &
        sample.college.ne("未知學院")
    ].copy()
    if sample.empty or sample.start_in_5_or_6.nunique() < 2:
        return {"status": "insufficient_comparable_students", "at_risk": at_risk,
                "graded_comparable": len(sample)}

    raw = sample.groupby("start_in_5_or_6").agg(
        students=("student_key", "size"),
        baseline_score=("baseline_score", "mean"),
        outcome_score=("outcome_score", "mean"),
        mean_supply=("supply_terms_5_6", "mean"),
    ).reset_index()
    raw["start_in_5_or_6"] = raw.start_in_5_or_6.astype(int)
    for col in ["baseline_score", "outcome_score", "mean_supply"]:
        raw[col] = raw[col].round(3)
    raw.to_csv(output_dir / "outcome_groups.csv", index=False, encoding="utf-8-sig")

    model = sample[["start_in_5_or_6", "baseline_score", "baseline_credits",
                    "supply_terms_5_6", "college", "first_observed_term"]].copy()
    model["start_in_5_or_6"] = model.start_in_5_or_6.astype(int)
    design = pd.get_dummies(model, columns=["college", "first_observed_term"],
                            drop_first=True, dtype=float)
    design.insert(0, "intercept", 1.0)
    x = design.to_numpy(dtype=float)
    y = sample.outcome_score.to_numpy(dtype=float)
    exposure_index = design.columns.get_loc("start_in_5_or_6")
    coefficient = float(np.linalg.lstsq(x, y, rcond=None)[0][exposure_index])
    rng = np.random.default_rng(42)
    bootstrap = []
    for _ in range(250):
        take = rng.integers(0, len(y), len(y))
        if np.unique(x[take, exposure_index]).size == 2:
            bootstrap.append(float(np.linalg.lstsq(
                x[take], y[take], rcond=None)[0][exposure_index]))
    interval = [float(v) for v in np.quantile(bootstrap, [0.025, 0.975])]
    college_groups = sample.groupby(["college", "start_in_5_or_6"]).agg(
        students=("student_key", "size"),
        mean_outcome_score=("outcome_score", "mean")
    ).reset_index()
    college_groups.loc[college_groups.students.lt(30), "mean_outcome_score"] = np.nan
    college_groups.to_csv(output_dir / "outcome_by_college.csv", index=False,
                          encoding="utf-8-sig")
    result = {
        "status": "ok",
        "at_risk_no_english_in_terms_1_4": at_risk,
        "graded_comparable_students": len(sample),
        "started_in_terms_5_6": int(sample.start_in_5_or_6.sum()),
        "did_not_start_in_terms_5_6": int((~sample.start_in_5_or_6).sum()),
        "raw_outcome_difference_points": round(float(
            raw.loc[raw.start_in_5_or_6.eq(1), "outcome_score"].iloc[0] -
            raw.loc[raw.start_in_5_or_6.eq(0), "outcome_score"].iloc[0]), 3),
        "adjusted_difference_points": round(coefficient, 3),
        "bootstrap_95pct_interval_points": [round(v, 3) for v in interval],
        "adjusted_for": ["baseline_non_English_grade", "baseline_graded_credits",
                         "college", "first_observed_term",
                         "college_bachelor_English_offerings_terms_5_6"],
        "grade_windows": "baseline terms 1-4; exposure terms 5-6; "
                         "non-English professional-course outcome terms 7-8",
        "minimum_graded_credits_each_window": 6,
        "interpretation": "observational association, not a causal EMI effect",
        "student_identifiers_exported": False,
    }
    (output_dir / "outcome_model_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
