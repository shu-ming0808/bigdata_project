"""1101–1142 學生學習模式與資工系單一教師推薦證據（唯讀 MySQL）。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import StandardScaler

from english_taught_analysis import (
    DEFAULT_MYSQL, HERE, LEVELS, LEVEL_ZH, TERMS, assign_prior_levels, frame, prepare,
    read_sources,
)

THRESHOLDS = {
    (110, "學測"): (13, 12, 8), (111, "學測"): (13, 12, 8),
    (112, "學測"): (13, 11, 8), (113, "學測"): (13, 11, 8),
    (114, "學測"): (13, 11, 8), (110, "指考"): (84, 76, 54),
}
TERM_ORDER = {term: i for i, term in enumerate(TERMS)}


def save_csv(data: pd.DataFrame, path: Path) -> None:
    data.to_csv(path, index=False, encoding="utf-8-sig")


def ratio(numerator: int, denominator: int) -> float | None:
    return round(100 * numerator / denominator, 2) if denominator else None


def student_term_data(args):
    mapping, student_terms, offerings, raw = read_sources(args)
    cohort, _, attempts = prepare(mapping, student_terms, offerings, raw)
    language_course = (
        attempts.course_code.str.startswith("LN") |
        attempts.course_name.str.contains(
            "大一英文|進修英文|TOEIC|英文能力鑑定|英語能力鑑定", regex=True) |
        attempts.english_level.isin(LEVELS[:-1])
    )
    if (attempts.selected & attempts.target & language_course).any():
        raise ValueError("語言學習課程混入英語授課專業課分析")
    cohort = assign_prior_levels(cohort, attempts)
    selected = attempts.loc[attempts.selected & attempts.target].copy()
    selected["english"] = selected.teaching_language.eq("英語")
    selected["credits_valid"] = selected.credits_num.where(selected.credits_num.between(0, 50), 0)
    selected["english_credits"] = selected.credits_valid.where(selected.english, 0)
    per_term = selected.groupby(["student_key", "term_code"], observed=True).agg(
        course_count=("offering_id", "size"),
        english_courses=("english", "sum"),
        total_credits=("credits_valid", "sum"),
        english_credits=("english_credits", "sum"),
    ).reset_index()
    roster = cohort.merge(per_term, how="left", on=["student_key", "term_code"],
                          validate="one_to_one")
    numeric = ["course_count", "english_courses", "total_credits", "english_credits"]
    roster[numeric] = roster[numeric].fillna(0)
    roster["english_yes"] = roster.english_courses.gt(0)
    roster["order"] = roster.term_code.map(TERM_ORDER).astype(int)
    excluded_language_attempts = int((attempts.selected & language_course).sum())
    return roster, attempts, excluded_language_attempts


def grouped_participation(roster: pd.DataFrame, group: str | list[str]) -> pd.DataFrame:
    out = roster.groupby(group, dropna=False, observed=True).agg(
        student_terms=("student_key", "size"),
        participating_terms=("english_yes", "sum"),
        english_courses=("english_courses", "sum"),
        english_credits=("english_credits", "sum"),
    ).reset_index()
    out["participation_pct"] = (
        100 * out.participating_terms / out.student_terms).round(2)
    return out.sort_values(group)


def offering_counts_by_term(args) -> pd.DataFrame:
    """正常開課班次數；研究欄位排除語言學習課及可見大一英文級別。"""
    return frame(args.mysql, args.login_path, args.database, """
        SELECT o.term_code,
               SUM(o.teaching_language_raw = '英語') AS all_english_classes,
               SUM(o.teaching_language_raw = '英語'
                   AND o.course_code NOT LIKE 'LN%'
                   AND o.course_name NOT REGEXP '大一英文|進修英文|TOEIC|英文能力鑑定|英語能力鑑定'
                   AND COALESCE(l.english_level, '') NOT IN ('beginner','intermediate','advanced')
               ) AS target_english_classes,
               COUNT(DISTINCT CASE WHEN o.teaching_language_raw = '英語'
                   AND o.course_code NOT LIKE 'LN%'
                   AND o.course_name NOT REGEXP '大一英文|進修英文|TOEIC|英文能力鑑定|英語能力鑑定'
                   AND COALESCE(l.english_level, '') NOT IN ('beginner','intermediate','advanced')
                   THEN o.course_code END) AS target_course_codes
        FROM course_offerings o
        LEFT JOIN offering_english_level l ON l.offering_id = o.offering_id
        WHERE o.offering_status_raw = '正常'
        GROUP BY o.term_code
        ORDER BY o.term_code
    """)


def transition_stats(roster: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    ordered = roster.sort_values(["student_key", "order"]).copy()
    g = ordered.groupby("student_key", sort=False)
    ordered["next_order"] = g.order.shift(-1)
    ordered["next_yes"] = g.english_yes.shift(-1)
    pairs = ordered.loc[ordered.next_order.eq(ordered.order + 1)].copy()
    rows = []
    for level in ["beginner", "intermediate", "advanced", "unknown"]:
        section = pairs.loc[pairs.prior_level.eq(level)]
        for current in [False, True]:
            den = int(section.english_yes.eq(current).sum())
            for following in [False, True]:
                n = int((section.english_yes.eq(current) & section.next_yes.eq(following)).sum())
                rows.append({"prior_level": LEVEL_ZH[level], "from_english": int(current),
                             "to_english": int(following), "count": n,
                             "same_start_count": den, "transition_pct": ratio(n, den)})
    # 再進入要求先觀察到曾修讀、後有可見的連續未修學期，最後重新修讀。
    reentry = 0
    for _, part in ordered.groupby("student_key", sort=False):
        prev_order = None
        seen_yes = False
        gap_after_yes = False
        for row in part.itertuples(index=False):
            if prev_order is not None and row.order != prev_order + 1:
                seen_yes = False
                gap_after_yes = False
            if row.english_yes:
                reentry += int(seen_yes and gap_after_yes)
                seen_yes = True
                gap_after_yes = False
            elif seen_yes:
                gap_after_yes = True
            prev_order = row.order
    # 首次「觀察到」英語授課，按各學生資料的第幾個相鄰學期計算風險率。
    risk = []
    for _, part in ordered.groupby("student_key", sort=False):
        first_order = None
        prev_order = None
        for row in part.itertuples(index=False):
            if prev_order is not None and row.order != prev_order + 1:
                break  # 缺席學期後視為截尾，不重新納入風險集。
            if first_order is None:
                first_order = row.order
            risk.append((row.order - first_order + 1, bool(row.english_yes)))
            prev_order = row.order
            if row.english_yes:
                break
    risk_df = pd.DataFrame(risk, columns=["observed_term_number", "event"])
    hazard = risk_df.groupby("observed_term_number").event.agg(["size", "sum"])
    hazard["hazard_pct"] = (100 * hazard["sum"] / hazard["size"]).round(2)
    return pd.DataFrame(rows), {
        "adjacent_student_term_pairs": len(pairs),
        "observed_reentry_events": reentry,
        "first_observed_english_hazard": hazard.reset_index().rename(
            columns={"size": "at_risk", "sum": "first_observed_english"}
        ).to_dict(orient="records"),
    }


def cluster_students(roster: pd.DataFrame, attempts: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows = []
    for _, part in roster.sort_values("order").groupby("student_key", sort=False):
        if len(part) < 2:
            continue
        orders = part.order.to_numpy(dtype=int)
        yes = part.english_yes.to_numpy(dtype=bool)
        first = int(orders[np.argmax(yes)] - orders[0] + 1) if yes.any() else len(TERMS) + 1
        longest = 0
        streak = 0
        reentries = 0
        was_yes = False
        gap = False
        previous = None
        for order, active in zip(orders, yes):
            if previous is not None and order != previous + 1:
                streak = 0
                was_yes = False
                gap = False
            if active:
                streak += 1
                longest = max(longest, streak)
                reentries += int(was_yes and gap)
                was_yes = True
                gap = False
            else:
                streak = 0
                if was_yes:
                    gap = True
            previous = order
        credits = float(part.total_credits.sum())
        rows.append({"student_key": part.student_key.iloc[0],
                     "observed_terms": len(part), "english_courses": int(part.english_courses.sum()),
                     "english_credit_share": float(part.english_credits.sum()) / credits if credits > 0 else 0,
                     "first_observed_term": first, "longest_consecutive_terms": longest,
                     "reentry_count": reentries})
    features = pd.DataFrame(rows)
    if len(features) < 10:
        return pd.DataFrame(), {"status": "fewer_than_10_students"}
    scored = attempts.loc[attempts.target & attempts.score_ok & attempts.credits_num.gt(0),
                          ["student_key", "grade_num", "credits_num"]].copy()
    scored["weighted_score"] = scored.grade_num * scored.credits_num
    grades = scored.groupby("student_key").agg(
        weighted_score=("weighted_score", "sum"), graded_credits=("credits_num", "sum")
    ).reset_index()
    grades["observed_grade_average"] = grades.weighted_score / grades.graded_credits
    features = features.merge(grades[["student_key", "observed_grade_average"]],
                              on="student_key", how="left", validate="one_to_one")
    cols = ["english_courses", "english_credit_share", "first_observed_term",
            "longest_consecutive_terms", "reentry_count"]
    x = StandardScaler().fit_transform(features[cols].to_numpy(dtype=float))
    max_k = min(5, len(features) - 1, len(np.unique(x, axis=0)))
    candidates = []
    for k in range(2, max_k + 1):
        labels = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(x)
        n_sample = min(3000, len(x))
        score = silhouette_score(x, labels, sample_size=n_sample, random_state=42)
        candidates.append((k, float(score)))
    if not candidates:
        return pd.DataFrame(), {"status": "insufficient_distinct_profiles"}
    chosen = max(candidates, key=lambda item: item[1])[0]
    features["cluster"] = KMeans(n_clusters=chosen, n_init=10, random_state=42).fit_predict(x)
    result = features.groupby("cluster").agg(
        students=("student_key", "size"),
        mean_observed_terms=("observed_terms", "mean"),
        mean_english_courses=("english_courses", "mean"),
        mean_english_credit_share=("english_credit_share", "mean"),
        mean_first_observed_term=("first_observed_term", "mean"),
        mean_longest_consecutive_terms=("longest_consecutive_terms", "mean"),
        mean_reentry_count=("reentry_count", "mean"),
        students_with_numeric_grade=("observed_grade_average", "count"),
        mean_observed_grade=("observed_grade_average", "mean"),
    ).reset_index()
    for col in result.columns:
        if col.startswith("mean_"):
            result[col] = result[col].round(3)
    return result, {"status": "ok", "cluster_count": chosen,
                    "silhouette_candidates": [{"k": k, "score": round(s, 4)} for k, s in candidates],
                    "clustered_students": len(features)}


def exam_reference(roster: pd.DataFrame, path: Path | None) -> tuple[pd.DataFrame, dict]:
    if path is None:
        return pd.DataFrame(), {"status": "missing_individual_exam_scores"}
    exam = pd.read_csv(path, dtype="string", encoding="utf-8-sig")
    required = {"student_key", "exam_year", "exam_type", "english_score"}
    if not required.issubset(exam.columns):
        raise ValueError(f"入學考 CSV 缺欄位：{sorted(required - set(exam.columns))}")
    exam["student_key"] = pd.to_numeric(exam.student_key, errors="raise").astype("Int64")
    if exam.student_key.duplicated().any():
        raise ValueError("入學考 CSV 的 student_key 必須一人一筆；請先確認重考或多測驗取捨")
    exam["exam_year"] = pd.to_numeric(exam.exam_year, errors="raise").astype(int)
    exam["english_score"] = pd.to_numeric(exam.english_score, errors="coerce")
    exam["exam_type"] = exam.exam_type.str.strip()
    def band(row):
        thresholds = THRESHOLDS.get((row.exam_year, row.exam_type))
        if thresholds is None or pd.isna(row.english_score):
            return "對照缺漏"
        top, front, median = thresholds
        score = row.english_score
        if score >= top:
            return "達頂標"
        if score >= front:
            return "達前標未達頂標"
        if score >= median:
            return "達均標未達前標"
        return "未達均標"
    exam["exam_band"] = exam.apply(band, axis=1)
    merged = roster.merge(exam[["student_key", "exam_band", "exam_year", "exam_type"] +
                               (["listening_level"] if "listening_level" in exam.columns else [])],
                          on="student_key", how="left", validate="many_to_one")
    merged["exam_band"] = merged.exam_band.fillna("無個人成績")
    result = grouped_participation(merged, "exam_band")
    if "listening_level" in merged.columns:
        listening = grouped_participation(merged.assign(
            listening_level=merged.listening_level.fillna("未知")), "listening_level")
    else:
        listening = pd.DataFrame()
    return (result, listening), {"status": "ok", "exam_students_matched": int(
        merged.loc[merged.exam_band.ne("無個人成績"), "student_key"].nunique()),
        "unsupported_or_missing_score_rows": int(exam.exam_band.eq("對照缺漏").sum())}


def run_student(args):
    roster, attempts, excluded_language_attempts = student_term_data(args)
    save_csv(offering_counts_by_term(args), args.output_dir / "offering_counts_by_term.csv")
    save_csv(grouped_participation(roster, "term_code"), args.output_dir / "participation_by_term.csv")
    save_csv(grouped_participation(roster, "department_code"),
             args.output_dir / "participation_by_department.csv")
    save_csv(grouped_participation(roster, ["term_code", "department_code"]),
             args.output_dir / "participation_term_department.csv")
    save_csv(grouped_participation(roster, ["department_code", "prior_level"]),
             args.output_dir / "participation_department_level.csv")
    save_csv(grouped_participation(roster, "prior_level"),
             args.output_dir / "participation_by_prior_level.csv")
    transitions, flow_summary = transition_stats(roster)
    save_csv(transitions, args.output_dir / "transition_matrix.csv")
    clusters, cluster_summary = cluster_students(roster, attempts)
    save_csv(clusters, args.output_dir / "student_clusters.csv")
    exam_tables, exam_summary = exam_reference(roster, args.exam_csv)
    if exam_summary["status"] == "ok":
        exam, listening = exam_tables
        save_csv(exam, args.output_dir / "participation_by_exam_band.csv")
        if not listening.empty:
            save_csv(listening, args.output_dir / "participation_by_listening_level.csv")
    summary = {"period": [TERMS[0], TERMS[-1]], "student_terms": len(roster),
               "observed_students": int(roster.student_key.nunique()),
               "excluded_language_course_attempts": excluded_language_attempts,
               "english_participating_student_terms": int(roster.english_yes.sum()),
               "flow": flow_summary, "clustering": cluster_summary, "exam": exam_summary}
    (args.output_dir / "student_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"學生分析完成：{len(roster)} 學生學期；{summary['observed_students']} 位可見學生")


def run_teacher(args):
    sql = """SELECT offering_id, term_code, course_code, course_name,
                    department_name, teaching_language_raw, instructor_name
             FROM solo_teacher_offering_evidence"""
    evidence = frame(args.mysql, args.login_path, args.database, sql)
    for col in ["course_code", "course_name", "department_name", "teaching_language_raw", "instructor_name"]:
        evidence[col] = evidence[col].fillna("").str.strip()
    evidence = evidence.loc[evidence.instructor_name.ne("")].copy()
    cs = evidence.loc[evidence.department_name.eq("資訊工程學系")].copy()
    language_mask = (
        evidence.course_code.str.startswith("LN") |
        evidence.course_name.str.contains(
            "大一英文|進修英文|TOEIC|英文能力鑑定|英語能力鑑定", regex=True)
    )
    comparable = evidence.loc[
        ~language_mask & evidence.course_code.ne("") &
        evidence.teaching_language_raw.isin(["國語", "英語"])
    ].copy()
    cs_comparable = comparable.loc[comparable.department_name.eq("資訊工程學系")].copy()

    def both_languages(data: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
        grouped = data.groupby(keys, observed=True).teaching_language_raw.nunique().reset_index()
        return grouped.loc[grouped.teaching_language_raw.eq(2), keys]

    all_pairs = both_languages(comparable, ["instructor_name", "course_code"])
    cs_pairs = both_languages(cs_comparable, ["instructor_name", "course_code"])
    all_same_term = both_languages(comparable, ["instructor_name", "course_code", "term_code"])
    cs_same_term = both_languages(cs_comparable, ["instructor_name", "course_code", "term_code"])
    course_summary = cs_pairs.groupby("course_code").size().rename("matching_teachers").reset_index()
    cs_names = cs_comparable.sort_values("term_code").drop_duplicates("course_code", keep="last")
    course_summary = course_summary.merge(cs_names[["course_code", "course_name"]],
                                          on="course_code", how="left", validate="one_to_one")
    save_csv(course_summary[["course_code", "course_name", "matching_teachers"]],
             args.output_dir / "same_teacher_language_courses.csv")
    teacher_language_summary = {
        "same_teacher_same_course_across_terms": {
            "all_course_codes": int(all_pairs.course_code.nunique()),
            "all_teacher_course_pairs": len(all_pairs),
            "cs_course_codes": int(cs_pairs.course_code.nunique()),
            "cs_teacher_course_pairs": len(cs_pairs),
        },
        "same_teacher_same_course_same_term": {
            "all_course_codes": int(all_same_term.course_code.nunique()),
            "all_teacher_course_term_groups": len(all_same_term),
            "cs_course_codes": int(cs_same_term.course_code.nunique()),
            "cs_teacher_course_term_groups": len(cs_same_term),
        },
    }
    (args.output_dir / "teacher_language_summary.json").write_text(
        json.dumps(teacher_language_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    targets = frame(args.mysql, args.login_path, args.database, """
        SELECT course_code, course_name, term_code FROM solo_teacher_offering_evidence
        WHERE department_name = '資訊工程學系'
          AND course_code IS NOT NULL AND TRIM(course_code) <> ''
    """)
    for col in ["course_code", "course_name", "term_code"]:
        targets[col] = targets[col].fillna("").str.strip()
    targets = targets.sort_values("term_code").drop_duplicates("course_code", keep="last")
    if args.course_code:
        targets = targets.loc[targets.course_code.eq(args.course_code)].copy()
        if targets.empty:
            raise ValueError(f"資工系正常開課資料查無課號：{args.course_code}")
    # 課名相似度是候選發現工具；同課號是較強的客觀證據。
    names = pd.concat([targets.course_name, cs.course_name], ignore_index=True).fillna("")
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4))
    matrix = vectorizer.fit_transform(names)
    similarities = cosine_similarity(matrix[:len(targets)], matrix[len(targets):])
    cs = cs.reset_index(drop=True)
    cs["term_order"] = cs.term_code.map(TERM_ORDER).fillna(-1).astype(int)
    coverage = []
    top = []
    for target_index, target in enumerate(targets.itertuples(index=False)):
        candidate_rows = cs.copy()
        candidate_rows["similarity"] = similarities[target_index]
        candidate_rows["same_code"] = candidate_rows.course_code.eq(target.course_code)
        candidate_rows["related"] = candidate_rows.similarity.ge(0.25) & ~candidate_rows.same_code
        candidate_rows = candidate_rows.loc[candidate_rows.same_code | candidate_rows.related]
        candidates = []
        for instructor, part in candidate_rows.groupby("instructor_name", sort=False):
            same = part.loc[part.same_code]
            related = part.loc[part.related].sort_values("similarity", ascending=False)
            all_history = cs.loc[cs.instructor_name.eq(instructor)]
            english_count = int(all_history.teaching_language_raw.eq("英語").sum())
            recent = all_history.sort_values("term_order").iloc[-1].term_code
            same_n = len(same)
            related_n = len(related)
            max_sim = float(related.similarity.max()) if related_n else 0.0
            recency = max(0, int(all_history.term_order.max())) / max(1, len(TERMS) - 1)
            score = 5 * min(same_n, 3) + 2 * max_sim + min(english_count, 5) + recency
            candidates.append({"course_code": target.course_code,
                               "course_name": target.course_name,
                               "instructor_name": instructor,
                               "same_course_offerings": same_n,
                               "related_course_offerings": related_n,
                               "related_course_example": related.iloc[0].course_name if related_n else "",
                               "related_title_similarity": round(max_sim, 3),
                               "past_english_offerings": english_count,
                               "latest_observed_term": recent,
                               "score": round(score, 3),
                               "administrative_eligibility": "待人工確認",
                               "official_emi_status": "未核對"})
        candidates.sort(key=lambda row: (-row["score"], -row["same_course_offerings"],
                                         -row["past_english_offerings"], row["instructor_name"]))
        coverage.append({"course_code": target.course_code, "course_name": target.course_name,
                         "evidence_based_candidates": len(candidates),
                         "at_least_three": int(len(candidates) >= 3)})
        for rank, candidate in enumerate(candidates[:3], start=1):
            top.append({"rank": rank, **candidate})
    save_csv(pd.DataFrame(coverage), args.output_dir / "teacher_coverage.csv")
    save_csv(pd.DataFrame(top), args.output_dir / "teacher_top3.csv")
    count = sum(row["at_least_three"] for row in coverage)
    print(f"教師推薦完成：{len(coverage)} 個資工系課號；{count} 個有至少三位證據候選人")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--student", action="store_true")
    parser.add_argument("--teacher", action="store_true")
    parser.add_argument("--course-code", help="限定資工系課號；僅用於教師推薦")
    parser.add_argument("--exam-csv", type=Path, help="獲授權取得的個人入學英文成績 CSV")
    parser.add_argument("--mysql", type=Path, default=DEFAULT_MYSQL)
    parser.add_argument("--login-path", default="codex-local")
    parser.add_argument("--database", default="ncu_course_flow_1101_1142")
    parser.add_argument("--department-rules", type=Path,
                        default=HERE / "undergraduate_department_rules.json")
    parser.add_argument("--output-dir", type=Path, default=HERE / "outputs" / "dual_project")
    args = parser.parse_args()
    if not args.student and not args.teacher:
        parser.error("請指定 --student 或 --teacher（可同時指定）")
    if args.course_code and not args.teacher:
        parser.error("--course-code 需搭配 --teacher")
    if args.exam_csv and not args.student:
        parser.error("--exam-csv 需搭配 --student")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.student:
        run_student(args)
    if args.teacher:
        run_teacher(args)


if __name__ == "__main__":
    main()
