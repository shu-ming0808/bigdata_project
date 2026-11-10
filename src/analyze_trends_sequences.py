"""115-0012：1051–1151 英語授課供給／參與趨勢及固定八學期路徑。

只輸出彙總；不輸出學生鍵、個別修課紀錄或原始 CSV。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from english_taught_analysis import DEFAULT_MYSQL, HERE, TERMS, frame
from run_dual_project_stats import (
    grouped_participation, save_csv, source_completeness_by_term, student_term_data,
)


def supply_by_term_department(args: argparse.Namespace) -> pd.DataFrame:
    """開課系所與學制的正常班次；語言學習課排除規則與既有分析一致。"""
    term_values = ",".join(f"'{term}'" for term in TERMS)
    data = frame(args.mysql, args.login_path, args.database, f"""
        SELECT o.term_code, COALESCE(o.department_code, '') AS offering_department_code,
               COALESCE(NULLIF(TRIM(r.degree_level_name), ''), '未知') AS degree_level,
               COUNT(*) AS target_offerings,
               SUM(o.teaching_language_raw = '英語') AS english_offerings
        FROM course_offerings o
        JOIN course_offering_raw r ON r.offering_row_id = o.offering_id
        LEFT JOIN offering_english_level l ON l.offering_id = o.offering_id
        WHERE o.term_code IN ({term_values}) AND o.offering_status_raw = '正常'
          AND COALESCE(o.course_code, '') NOT LIKE 'LN%'
          AND COALESCE(o.course_name, '') NOT REGEXP
              '大一英文|進修英文|TOEIC|英文能力鑑定|英語能力鑑定'
          AND COALESCE(l.english_level, '') NOT IN
              ('beginner', 'intermediate', 'advanced')
        GROUP BY o.term_code, o.department_code, degree_level
        ORDER BY o.term_code, o.department_code, degree_level
    """)
    for column in ["target_offerings", "english_offerings"]:
        data[column] = pd.to_numeric(data[column])
    data["english_share_pct"] = (
        100 * data.english_offerings / data.target_offerings
    ).round(2)
    return data


def trend_tables(roster: pd.DataFrame, supply: pd.DataFrame):
    participation = grouped_participation(roster, "term_code").drop(columns="english_credits")
    supply_all = supply.groupby("term_code", as_index=False)[
        ["target_offerings", "english_offerings"]
    ].sum()
    bachelor = supply.loc[supply.degree_level.eq("學士班")].groupby(
        "term_code", as_index=False
    )[["target_offerings", "english_offerings"]].sum().rename(columns={
        "target_offerings": "bachelor_target_offerings",
        "english_offerings": "bachelor_english_offerings",
    })
    trend = participation.merge(supply_all, on="term_code", validate="one_to_one")
    trend = trend.merge(bachelor, on="term_code", how="left", validate="one_to_one")
    trend["english_offering_share_pct"] = (
        100 * trend.english_offerings / trend.target_offerings
    ).round(2)
    trend["bachelor_english_offering_share_pct"] = (
        100 * trend.bachelor_english_offerings / trend.bachelor_target_offerings
    ).round(2)
    trend["english_courses_per_100_student_terms"] = (
        100 * trend.english_courses / trend.student_terms
    ).round(2)
    student_dept = grouped_participation(
        roster, ["term_code", "department_code"]
    ).drop(columns="english_credits")
    offering_dept = supply.groupby(
        ["term_code", "offering_department_code"], as_index=False
    )[["target_offerings", "english_offerings"]].sum()
    offering_dept["english_share_pct"] = (
        100 * offering_dept.english_offerings / offering_dept.target_offerings
    ).round(2)
    return trend, student_dept, offering_dept


def fixed_eight_sequences(roster: pd.DataFrame, complete_terms: list[str]):
    """每人從首次可見學期起取八個連續、且結果欄位完整的學期。"""
    if len(complete_terms) < 8:
        raise ValueError("完整結果學期不足八個")
    complete = roster.loc[roster.term_code.isin(complete_terms)].sort_values(
        ["student_key", "order"]
    )
    last_order = max(TERMS.index(term) for term in complete_terms)
    sequences = []
    starts = []
    no_followup = 0
    gaps = 0
    for _, part in complete.groupby("student_key", sort=False):
        first_eight = part.head(8)
        start = int(part.order.iloc[0])
        start_term = str(part.term_code.iloc[0])
        eligible = start + 7 <= last_order and len(first_eight) == 8 and np.array_equal(
            first_eight.order.to_numpy(dtype=int), np.arange(start, start + 8)
        )
        starts.append((start_term, eligible))
        if eligible:
            sequences.append(first_eight.english_yes.to_numpy(dtype=int))
        elif start + 7 > last_order:
            no_followup += 1
        else:
            gaps += 1
    cohort = pd.DataFrame(starts, columns=["first_observed_term", "eight_terms_observed"])
    cohort = cohort.groupby("first_observed_term", as_index=False).agg(
        students=("eight_terms_observed", "size"),
        eligible_students=("eight_terms_observed", "sum"),
    )
    cohort["eligible_pct"] = (100 * cohort.eligible_students / cohort.students).round(2)
    x = np.asarray(sequences, dtype=int)
    audit = {
        "students_with_complete_outcome_term": len(starts),
        "eligible_eight_consecutive_terms": len(x),
        "insufficient_followup_before_last_complete_term": no_followup,
        "gap_within_first_eight_terms": gaps,
        "last_complete_term": complete_terms[-1],
        "first_term_is_first_observed_not_verified_admission_term": True,
    }
    return x, cohort, audit


def sequence_tables(x: np.ndarray):
    if len(x) < 10:
        raise ValueError("固定八學期有效學生少於十人")
    # 加 S 前綴，避免 Excel 將 00000001 自動轉成數字 1。
    patterns = pd.Series(["S" + "".join(map(str, row)) for row in x], name="sequence")
    top_patterns = patterns.value_counts().head(20).rename_axis("sequence").reset_index(
        name="students"
    )
    categories = np.select(
        [x.sum(axis=1) == 0,
         (x[:, :4].sum(axis=1) > 0) & (x[:, 4:].sum(axis=1) == 0),
         (x[:, :4].sum(axis=1) == 0) & (x[:, 4:].sum(axis=1) > 0)],
        ["從未觀察到", "僅前四學期", "僅後四學期"],
        default="前後四學期皆有",
    )
    category_counts = pd.Series(categories, name="path_type").value_counts().rename_axis(
        "path_type"
    ).reset_index(name="students")
    candidate_scores = []
    distinct = len(np.unique(x, axis=0))
    for k in range(2, min(6, distinct, len(x) - 1) + 1):
        labels = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(x)
        score = silhouette_score(x, labels, sample_size=min(2000, len(x)), random_state=42)
        candidate_scores.append((k, round(float(score), 4)))
    chosen = max(candidate_scores, key=lambda pair: pair[1])[0]
    labels = KMeans(n_clusters=chosen, n_init=10, random_state=42).fit_predict(x)
    cluster_rows = []
    for cluster in range(chosen):
        members = x[labels == cluster]
        row = {"cluster": cluster, "students": len(members),
               "mean_participating_terms": round(float(members.sum(axis=1).mean()), 3)}
        row.update({f"term_{i + 1}_participation_pct": round(float(100 * members[:, i].mean()), 2)
                    for i in range(8)})
        cluster_rows.append(row)
    cluster_table = pd.DataFrame(cluster_rows).sort_values("cluster")
    transitions = []
    for position in range(7):
        for current in (0, 1):
            den = int((x[:, position] == current).sum())
            for following in (0, 1):
                n = int(((x[:, position] == current) & (x[:, position + 1] == following)).sum())
                transitions.append({"from_term_position": position + 1,
                                    "from_english": current, "to_english": following,
                                    "students": n, "same_start_students": den,
                                    "transition_pct": round(100 * n / den, 2) if den else None})
    return top_patterns, category_counts, cluster_table, pd.DataFrame(transitions), {
        "chosen_k": chosen,
        "silhouette_candidates": [{"k": k, "score": score} for k, score in candidate_scores],
        "sequence_is_eight_binary_terms": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql", type=Path, default=DEFAULT_MYSQL)
    parser.add_argument("--login-path", default="codex-local")
    parser.add_argument("--database", default="ncu_course_flow_1150012")
    parser.add_argument("--department-rules", type=Path,
                        default=HERE / "undergraduate_department_rules.json")
    parser.add_argument("--output-dir", type=Path,
                        default=HERE / "outputs" / "trends_sequences_1051_1151")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    roster, _, excluded_language_attempts = student_term_data(args)
    completeness = source_completeness_by_term(args)
    complete_terms = completeness.loc[
        completeness.credit_nonblank_pct.ge(50) & completeness.grade_nonblank_pct.ge(50),
        "term_code",
    ].tolist()
    supply = supply_by_term_department(args)
    trend, student_dept, offering_dept = trend_tables(roster, supply)
    x, cohorts, audit = fixed_eight_sequences(roster, complete_terms)
    patterns, categories, clusters, transitions, model = sequence_tables(x)
    outputs = {
        "term_trend.csv": trend,
        "student_department_term.csv": student_dept,
        "offering_department_term.csv": offering_dept,
        "offering_degree_term.csv": supply.groupby(
            ["term_code", "degree_level"], as_index=False
        )[["target_offerings", "english_offerings"]].sum(),
        "first_observed_cohort_eligibility.csv": cohorts,
        "top_eight_term_sequences.csv": patterns,
        "eight_term_path_types.csv": categories,
        "eight_term_clusters.csv": clusters,
        "eight_term_transitions.csv": transitions,
    }
    for filename, data in outputs.items():
        save_csv(data, args.output_dir / filename)
    summary = {
        "period": [TERMS[0], TERMS[-1]], "complete_outcome_terms": complete_terms,
        "observed_undergraduates": int(roster.student_key.nunique()),
        "student_terms": len(roster), "excluded_language_attempts": excluded_language_attempts,
        "sequence_audit": audit, "sequence_model": model,
        "interpretation": "開課系所與學生所屬系所是不同概念；供給與參與的同期變化不是因果分解。",
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"完成：{len(trend)} 學期；固定八學期學生 {len(x)} 人；分群 {model['chosen_k']} 群")


if __name__ == "__main__":
    main()
