"""固定八學期：起始系所／學期、修課轉移與授課方式的彙總分析。

首次可見學期在本分析中定義為「推定一年級上學期」，不是正式學籍年級。
只輸出彙總表，不輸出學生鍵或個別修課紀錄。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from english_taught_analysis import DEFAULT_MYSQL, HERE, TERMS, frame
from run_dual_project_stats import save_csv, source_completeness_by_term, student_term_data


MIN_GROUP = 30


def make_eight_cohort(roster: pd.DataFrame, complete_terms: list[str]):
    """每位學生僅取最早八個連續可見學期，不把重複滑動視窗當成新學生。"""
    ordered = roster.loc[roster.term_code.isin(complete_terms)].sort_values(
        ["student_key", "order"]
    )
    last_order = max(TERMS.index(term) for term in complete_terms)
    student_rows = []
    term_rows = []
    for key, part in ordered.groupby("student_key", sort=False):
        first = part.head(8)
        if len(first) != 8 or int(first.order.iloc[0]) + 7 > last_order:
            continue
        expected = np.arange(int(first.order.iloc[0]), int(first.order.iloc[0]) + 8)
        if not np.array_equal(first.order.to_numpy(dtype=int), expected):
            continue
        sequence = first.english_yes.to_numpy(dtype=bool)
        early = bool(sequence[:4].any())
        late = bool(sequence[4:].any())
        path_type = ("前後四學期皆有" if early and late else
                     "僅前四學期" if early else
                     "僅後四學期" if late else "從未觀察到")
        student_rows.append({
            "student_key": key,
            "first_observed_term": str(first.term_code.iloc[0]),
            "initial_department_code": str(first.department_code.iloc[0]),
            "department_changed_in_window": first.department_code.nunique() > 1,
            "path_type": path_type,
            "late_only": path_type == "僅後四學期",
        })
        for position, row in enumerate(first.itertuples(index=False), start=1):
            term_rows.append({
                "student_key": key,
                "term_code": row.term_code,
                "position": position,
                "assumed_year": (position + 1) // 2,
                "english_yes": bool(row.english_yes),
            })
    students = pd.DataFrame(student_rows)
    terms = pd.DataFrame(term_rows)
    if students.empty:
        raise ValueError("固定八學期無合格學生")
    if terms.duplicated(["student_key", "term_code"]).any():
        raise ValueError("固定八學期學生與學期鍵重複")
    return students, terms


def department_names(args: argparse.Namespace) -> pd.DataFrame:
    data = frame(args.mysql, args.login_path, args.database, """
        SELECT department_code, department_name, COUNT(*) AS rows_count
        FROM student_terms
        WHERE department_code IS NOT NULL AND department_name IS NOT NULL
        GROUP BY department_code, department_name
    """)
    data["rows_count"] = pd.to_numeric(data.rows_count)
    return data.sort_values("rows_count", ascending=False).drop_duplicates(
        "department_code"
    )[["department_code", "department_name"]].rename(columns={
        "department_code": "initial_department_code",
        "department_name": "initial_department_name",
    })


def path_group_table(students: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    result = students.groupby(group_columns, dropna=False).agg(
        students=("student_key", "size"), late_only_students=("late_only", "sum"),
        department_changed_students=("department_changed_in_window", "sum"),
    ).reset_index()
    result = result.loc[result.students.ge(MIN_GROUP)].copy()
    result["late_only_pct"] = (100 * result.late_only_students / result.students).round(2)
    result["department_changed_pct"] = (
        100 * result.department_changed_students / result.students
    ).round(2)
    return result.sort_values(group_columns)


def transition_tables(terms: pd.DataFrame, students: pd.DataFrame):
    ordered = terms.sort_values(["student_key", "position"]).copy()
    ordered["next_english"] = ordered.groupby("student_key", sort=False).english_yes.shift(-1)
    pairs = ordered.loc[ordered.position.lt(8)].copy()
    pairs = pairs.merge(students[["student_key", "first_observed_term",
                                  "initial_department_code"]],
                        on="student_key", validate="many_to_one")
    pairs["from_english"] = pairs.english_yes.astype(int)
    pairs["to_english"] = pairs.next_english.astype(int)
    pairs["assumed_year_from"] = (pairs.position + 1) // 2
    pairs["assumed_year_to"] = (pairs.position + 2) // 2
    def summarise(groups: list[str], threshold: int = 0):
        counts = pairs.groupby(groups + ["from_english", "to_english"],
                               dropna=False).size().rename("students").reset_index()
        base = pairs.groupby(groups + ["from_english"], dropna=False).size().rename(
            "same_start_students"
        ).reset_index()
        result = counts.merge(base, on=groups + ["from_english"], validate="many_to_one")
        result = result.loc[result.same_start_students.ge(threshold)].copy()
        result["transition_pct"] = (
            100 * result.students / result.same_start_students
        ).round(2)
        return result.sort_values(groups + ["from_english", "to_english"])
    by_position = summarise(["position", "assumed_year_from", "assumed_year_to"])
    by_department = summarise(["position", "initial_department_code"], MIN_GROUP)
    by_cohort = summarise(["position", "first_observed_term"], MIN_GROUP)
    return by_position, by_department, by_cohort


def offering_methods(args: argparse.Namespace) -> pd.DataFrame:
    term_values = ",".join(f"'{term}'" for term in TERMS)
    return frame(args.mysql, args.login_path, args.database, f"""
        SELECT o.offering_id, o.term_code,
               r.teaching_method_lecture AS lecture_flag,
               r.teaching_method_practicum_lab AS practicum_lab_flag,
               r.offering_grade_level AS declared_grade_level
        FROM course_offerings o
        JOIN course_offering_raw r ON r.offering_row_id = o.offering_id
        WHERE o.term_code IN ({term_values})
    """)


def method_type(lecture: pd.Series, practicum: pd.Series) -> np.ndarray:
    lecture_yes = lecture.fillna("").str.strip().eq("是")
    practicum_yes = practicum.fillna("").str.strip().eq("是")
    return np.select(
        [lecture_yes & ~practicum_yes, ~lecture_yes & practicum_yes,
         lecture_yes & practicum_yes],
        ["講授標記", "實作／實驗標記", "兩者皆標記"], default="其他或未標記",
    )


def course_type_tables(attempts: pd.DataFrame, terms: pd.DataFrame,
                       offerings: pd.DataFrame):
    selected = attempts.loc[
        attempts.selected & attempts.target &
        attempts.teaching_language.isin(["國語", "英語"]),
        ["student_key", "term_code", "offering_id", "teaching_language"],
    ].copy()
    selected = selected.merge(terms[["student_key", "term_code", "position", "assumed_year"]],
                              on=["student_key", "term_code"], how="inner", validate="many_to_one")
    offerings["offering_id"] = pd.to_numeric(offerings.offering_id).astype("Int64")
    offerings["method_type"] = method_type(offerings.lecture_flag,
                                            offerings.practicum_lab_flag)
    selected = selected.merge(offerings[["offering_id", "method_type", "declared_grade_level"]],
                              on="offering_id", how="left", validate="many_to_one")
    selected["method_type"] = selected.method_type.fillna("其他或未標記")
    selected["declared_grade_level"] = selected.declared_grade_level.fillna("").str.strip()
    by_year = selected.groupby(["assumed_year", "teaching_language", "method_type"],
                               observed=True).agg(
        course_attempts=("offering_id", "size"),
        students=("student_key", "nunique"),
        distinct_offerings=("offering_id", "nunique"),
    ).reset_index()
    denominator = by_year.groupby(["assumed_year", "teaching_language"])[
        "course_attempts"
    ].sum().rename("all_method_attempts").reset_index()
    by_year = by_year.merge(denominator, on=["assumed_year", "teaching_language"],
                            validate="many_to_one")
    by_year["attempt_share_pct"] = (
        100 * by_year.course_attempts / by_year.all_method_attempts
    ).round(2)
    levels = {"一年級": 1, "二年級": 2, "三年級": 3, "四年級": 4}
    selected["declared_year"] = selected.declared_grade_level.map(levels)
    grade_audit = selected.groupby(["assumed_year", "teaching_language"],
                                   observed=True).agg(
        course_attempts=("offering_id", "size"),
        declared_year_available=("declared_year", "count"),
    ).reset_index()
    grade_audit["declared_year_available_pct"] = (
        100 * grade_audit.declared_year_available / grade_audit.course_attempts
    ).round(2)
    return by_year, grade_audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql", type=Path, default=DEFAULT_MYSQL)
    parser.add_argument("--login-path", default="codex-local")
    parser.add_argument("--database", default="ncu_course_flow_1150012")
    parser.add_argument("--department-rules", type=Path,
                        default=HERE / "undergraduate_department_rules.json")
    parser.add_argument("--output-dir", type=Path,
                        default=HERE / "outputs" / "pathways_course_types_1051_1142")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    roster, attempts, _ = student_term_data(args)
    completeness = source_completeness_by_term(args)
    complete_terms = completeness.loc[
        completeness.credit_nonblank_pct.ge(50) & completeness.grade_nonblank_pct.ge(50),
        "term_code",
    ].tolist()
    students, terms = make_eight_cohort(roster, complete_terms)
    # 與前一份分析的資格數交叉核對，防止本腳本暗中改變研究分母。
    prior = json.loads((HERE / "outputs" / "trends_sequences_1051_1151" /
                        "summary.json").read_text(encoding="utf-8"))
    expected = prior["sequence_audit"]["eligible_eight_consecutive_terms"]
    if len(students) != expected:
        raise ValueError(f"固定八學期人數與既有稽核不符：{len(students)} vs {expected}")
    names = department_names(args)
    path_tables = {
        "path_by_first_term.csv": path_group_table(students, ["first_observed_term"]),
        "path_by_initial_department.csv": path_group_table(
            students, ["initial_department_code"]
        ).merge(names, on="initial_department_code", how="left", validate="many_to_one"),
        "path_by_first_term_department.csv": path_group_table(
            students, ["first_observed_term", "initial_department_code"]
        ).merge(names, on="initial_department_code", how="left", validate="many_to_one"),
    }
    by_position, by_department, by_cohort = transition_tables(terms, students)
    method_by_year, declared_grade_audit = course_type_tables(
        attempts, terms, offering_methods(args)
    )
    outputs = {**path_tables,
               "transition_by_assumed_year_position.csv": by_position,
               "transition_by_initial_department.csv": by_department,
               "transition_by_first_term.csv": by_cohort,
               "method_type_by_assumed_year.csv": method_by_year,
               "declared_course_grade_coverage.csv": declared_grade_audit}
    for filename, data in outputs.items():
        save_csv(data, args.output_dir / filename)
    report = {
        "period_for_eight_term_paths": [complete_terms[0], complete_terms[-1]],
        "eligible_students": len(students),
        "first_observed_term_assumed_to_be_year_one": True,
        "year_positions": {"1": [1, 2], "2": [3, 4], "3": [5, 6], "4": [7, 8]},
        "students_with_department_change_in_window": int(
            students.department_changed_in_window.sum()),
        "minimum_published_group_size": MIN_GROUP,
        "method_definition": {
            "講授標記": "講授=是、實作／實驗=不是",
            "實作／實驗標記": "講授=不是、實作／實驗=是",
            "兩者皆標記": "兩欄皆是",
            "其他或未標記": "其餘與欄位缺漏",
        },
        "limitations": [
            "推定年級是分析假設，未經正式入學學期與學籍年級核對。",
            "教學方法標記是課型代理變數，不能直接斷言理論或實作內容。",
            "系所比較以首次可見學期所屬系所分組，轉系者仍留在起始系所。",
        ],
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"完成：固定八學期 {len(students)} 人；彙總表 {len(outputs)} 份")


if __name__ == "__main__":
    main()
