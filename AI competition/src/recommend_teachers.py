"""Evidence-based teacher shortlisting; no generative Agent is implemented yet.

Read-only access to shared research views. Exports stay in this project's outputs.
"""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

HERE = Path(__file__).resolve().parents[1]
RESEARCH_SRC = HERE.parent / "Big Data Analytics Program" / "src"
sys.path.insert(0, str(RESEARCH_SRC))
from english_taught_analysis import DEFAULT_MYSQL, TERMS, frame
from student_data import save_csv
TERM_ORDER = {term: i for i, term in enumerate(TERMS)}

TEACHER_RUBRIC = {
    "same_course_points": 30,
    "formal_emi_points": 30,
    "english_teaching_points": 15,
    "related_course_points": 15,
    "overall_recency_points": 10,
    "total_points": 100,
    "meaning": "歷史授課證據強度；不是教學品質或行政可派任資格",
}


def run_teacher(args):
    sql = """SELECT offering_id, term_code, course_code, course_name,
                    department_name, course_attribute, degree_level,
                    teaching_language AS teaching_language_raw,
                    formal_emi_status, instructor_name
             FROM shared_1150012_solo_teacher_v"""
    evidence = frame(args.mysql, args.login_path, args.database, sql)
    return rank_teachers(args, evidence)


def rank_teachers(args, evidence):
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
    targets = cs.loc[cs.course_code.ne(""), ["course_code", "course_name", "term_code", "course_attribute", "degree_level"]].copy()
    for col in ["course_code", "course_name", "term_code"]:
        targets[col] = targets[col].fillna("").str.strip()
    if args.required_only:
        targets = targets.loc[
            targets.course_attribute.eq("必修") & targets.degree_level.eq("學士班")
        ].copy()
    targets = targets.sort_values("term_code").drop_duplicates("course_code", keep="last")
    if args.course_code:
        targets = targets.loc[targets.course_code.eq(args.course_code)].copy()
        if targets.empty:
            raise ValueError(f"資工系符合條件的正常開課資料查無課號：{args.course_code}")
    # 課名相似度是候選發現工具；同課號是較強的客觀證據。
    names = pd.concat([targets.course_name, cs.course_name], ignore_index=True).fillna("")
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4))
    matrix = vectorizer.fit_transform(names)
    similarities = cosine_similarity(matrix[:len(targets)], matrix[len(targets):])
    cs = cs.reset_index(drop=True)
    cs["term_order"] = cs.term_code.map(TERM_ORDER).fillna(-1).astype(int)
    coverage = []
    top = []
    required_histories = []
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
            formal_emi_count = int(all_history.formal_emi_status.eq("yes").sum())
            formal_emi_unknown = int(all_history.formal_emi_status.eq("unknown").sum())
            recent = all_history.sort_values("term_order").iloc[-1].term_code
            same_n = len(same)
            same_english = int(same.teaching_language_raw.eq("英語").sum())
            same_emi = int(same.formal_emi_status.eq("yes").sum())
            latest_same = same.sort_values("term_order").iloc[-1].term_code if same_n else ""
            related_n = len(related)
            max_sim = float(related.similarity.max()) if related_n else 0.0
            max_term_order = max(1, len(TERMS) - 1)
            same_recency = (max(0, int(same.term_order.max())) / max_term_order
                            if same_n else 0.0)
            overall_recency = max(0, int(all_history.term_order.max())) / max_term_order
            same_points = 20 * min(same_n, 3) / 3 + 10 * same_recency
            emi_points = (20 * min(same_emi, 2) / 2 +
                          10 * min(max(formal_emi_count - same_emi, 0), 3) / 3)
            english_points = (10 * min(same_english, 2) / 2 +
                              5 * min(max(english_count - same_english, 0), 5) / 5)
            related_points = 10 * max_sim + 5 * min(related_n, 3) / 3
            recent_points = 10 * overall_recency
            score = same_points + emi_points + english_points + related_points + recent_points
            if not 0 <= score <= 100.000001:
                raise ValueError(f"教師證據分數超出 0–100：{score}")
            candidates.append({"course_code": target.course_code,
                               "course_name": target.course_name,
                               "course_attribute": target.course_attribute,
                               "degree_level": target.degree_level,
                               "instructor_name": instructor,
                               "same_course_offerings": same_n,
                               "same_course_english_offerings": same_english,
                               "same_course_formal_emi_offerings": same_emi,
                               "latest_same_course_term": latest_same,
                               "related_course_offerings": related_n,
                               "related_course_example": related.iloc[0].course_name if related_n else "",
                               "related_title_similarity": round(max_sim, 3),
                               "past_english_offerings": english_count,
                               "past_formal_emi_offerings": formal_emi_count,
                               "past_formal_emi_unknown_offerings": formal_emi_unknown,
                               "same_course_offering_ids": ",".join(
                                   str(x) for x in same.offering_id.tolist()),
                               "related_offering_ids": ",".join(
                                   str(x) for x in related.offering_id.tolist()),
                               "latest_observed_term": recent,
                               "same_course_points": round(same_points, 2),
                               "formal_emi_points": round(emi_points, 2),
                               "english_teaching_points": round(english_points, 2),
                               "related_course_points": round(related_points, 2),
                               "overall_recency_points": round(recent_points, 2),
                               "score_0_to_100": round(score, 2),
                               "score_scope": "歷史授課證據，行政資格待核對",
                               "administrative_eligibility": "待人工確認",
                               "instructor_identity_quality": "僅有姓名，未核對教師人事編號"})
        candidates.sort(key=lambda row: (-row["score_0_to_100"], -row["same_course_offerings"],
                                         -row["past_english_offerings"], row["instructor_name"]))
        coverage.append({"course_code": target.course_code, "course_name": target.course_name,
                         "evidence_based_candidates": len(candidates),
                         "at_least_three": int(len(candidates) >= 3)})
        for rank, candidate in enumerate(candidates[:3], start=1):
            top.append({"rank": rank, **candidate})
            history = cs.loc[
                cs.instructor_name.eq(candidate["instructor_name"]) &
                cs.course_attribute.eq("必修") & cs.degree_level.eq("學士班") &
                cs.course_code.ne("")
            ].copy()
            if history.empty:
                continue
            # The same TF-IDF representation used for candidate discovery also
            # gives an explicitly labelled title-similarity *proxy* for display.
            history["title_similarity"] = similarities[target_index, history.index]
            for (code, name), taught in history.groupby(
                    ["course_code", "course_name"], sort=True):
                terms = sorted(set(taught.term_code.tolist()))
                similarity = float(taught.title_similarity.max())
                relation = ("同課號" if code == target.course_code else
                            "課名相近" if similarity >= 0.25 else "其他曾教必修")
                required_histories.append({
                    "target_course_code": target.course_code,
                    "rank": rank,
                    "instructor_name": candidate["instructor_name"],
                    "taught_course_code": code,
                    "taught_course_name": name,
                    "relation_to_target": relation,
                    "title_similarity": round(similarity, 3),
                    "academic_years": ",".join(sorted({t[:3] for t in terms})),
                    "terms_taught": ",".join(terms),
                    "offering_count": len(taught),
                    "english_offerings": int(taught.teaching_language_raw.eq("英語").sum()),
                    "formal_emi_yes_offerings": int(taught.formal_emi_status.eq("yes").sum()),
                    "formal_emi_unknown_offerings": int(
                        taught.formal_emi_status.eq("unknown").sum()),
                    "evidence_offering_ids": ",".join(
                        str(x) for x in taught.offering_id.tolist()),
                    "instructor_identity_quality": "僅有姓名，未核對教師人事編號",
                })
    save_csv(pd.DataFrame(coverage), args.output_dir / "teacher_coverage.csv")
    save_csv(pd.DataFrame(top), args.output_dir / "teacher_top3.csv")
    (args.output_dir / "teacher_rubric.json").write_text(
        json.dumps(TEACHER_RUBRIC, ensure_ascii=False, indent=2), encoding="utf-8")
    history_columns = [
        "target_course_code", "rank", "instructor_name", "taught_course_code",
        "taught_course_name", "relation_to_target", "title_similarity",
        "academic_years", "terms_taught", "offering_count", "english_offerings",
        "formal_emi_yes_offerings", "formal_emi_unknown_offerings",
        "evidence_offering_ids", "instructor_identity_quality",
    ]
    save_csv(pd.DataFrame(required_histories, columns=history_columns),
             args.output_dir / "teacher_required_history.csv")
    count = sum(row["at_least_three"] for row in coverage)
    print(f"教師推薦完成：{len(coverage)} 個資工系課號；{count} 個有至少三位證據候選人")
    return top


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-code", default=None)
    parser.add_argument("--required-only", action="store_true")
    parser.add_argument("--mysql", type=Path, default=DEFAULT_MYSQL)
    parser.add_argument("--login-path", default="codex-local")
    parser.add_argument("--database", default="ncu_course_flow_1150012")
    parser.add_argument("--output-dir", type=Path, default=HERE / "outputs" / "teacher_recommendation")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_teacher(args)

if __name__ == "__main__":
    main()
