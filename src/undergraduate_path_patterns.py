"""Fixed-eight-term clustering and post-entry pathways; aggregate exports only."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler


def analyze(cohort_terms: pd.DataFrame, output_dir: Path) -> dict:
    ordered = cohort_terms.sort_values(["student_key", "position"])
    states = ordered.pivot(index="student_key", columns="position",
                           values="english_yes").sort_index()
    courses = ordered.pivot(index="student_key", columns="position",
                            values="english_courses").sort_index()
    if list(states.columns) != list(range(1, 9)) or states.isna().any().any():
        raise ValueError("Eight-term cohort must have one state in each position 1–8")
    binary = states.to_numpy(dtype=bool)
    course_counts = courses.to_numpy(dtype=int)
    features = []
    post_rows = []
    for student_key, active, course_row in zip(states.index, binary, course_counts):
        first = int(np.argmax(active) + 1) if active.any() else 9
        streak = longest = reentries = 0
        previously_active = gap_after_start = False
        for current in active:
            if current:
                streak += 1
                longest = max(longest, streak)
                reentries += int(previously_active and gap_after_start)
                previously_active, gap_after_start = True, False
            else:
                streak = 0
                if previously_active:
                    gap_after_start = True
        early, late = bool(active[:4].any()), bool(active[4:].any())
        path = ("前後四學期皆有" if early and late else
                "僅前四學期" if early else
                "僅後四學期" if late else "前八學期未修")
        features.append({
            "student_key": student_key,
            "first_start_position": first,
            "english_course_count": int(course_row.sum()),
            "participating_terms": int(active.sum()),
            "longest_continuous_terms": longest,
            "reentry_count": reentries,
            "late_participation_share": (float(active[4:].sum()) / active.sum()
                                         if active.any() else 0.0),
            "four_path_type": path,
        })
        if first <= 7:
            next_active = bool(active[first])
            later_after_stop = bool(active[first + 1:].any()) if first <= 6 else False
            post_rows.append({
                "first_start_position": first,
                "first_start_year": (first + 1) // 2,
                "next_term_continued": int(next_active),
                "next_term_stopped": int(not next_active),
                "eligible_reentry_followup": int(not next_active and first <= 6),
                "reentered_after_immediate_stop": int(
                    not next_active and first <= 6 and later_after_stop),
            })
    feature_frame = pd.DataFrame(features)
    post = pd.DataFrame(post_rows)
    by_year = post.groupby("first_start_year", observed=True).agg(
        first_starts_with_next_term=("next_term_continued", "size"),
        continued_next_term=("next_term_continued", "sum"),
        stopped_next_term=("next_term_stopped", "sum"),
        eligible_reentry_followup=("eligible_reentry_followup", "sum"),
        reentered_after_immediate_stop=("reentered_after_immediate_stop", "sum"),
    ).reset_index()
    by_year["continued_next_pct"] = (
        100 * by_year.continued_next_term /
        by_year.first_starts_with_next_term).round(2)
    by_year["reentered_after_stop_pct"] = (
        100 * by_year.reentered_after_immediate_stop /
        by_year.eligible_reentry_followup.replace(0, np.nan)).round(2)
    by_year.to_csv(output_dir / "post_start_by_first_year.csv", index=False,
                   encoding="utf-8-sig")

    names = ["first_start_position", "english_course_count",
             "participating_terms", "longest_continuous_terms",
             "reentry_count", "late_participation_share"]
    scaled = StandardScaler().fit_transform(feature_frame[names].to_numpy(dtype=float))
    candidates = []
    fitted = {}
    for k in range(2, 7):
        estimator = KMeans(n_clusters=k, n_init=20, random_state=42)
        labels = estimator.fit_predict(scaled)
        sizes = np.bincount(labels, minlength=k)
        silhouette = silhouette_score(scaled, labels, sample_size=min(3000, len(scaled)),
                                      random_state=42)
        candidates.append({"k": k, "silhouette": round(float(silhouette), 4),
                           "smallest_cluster_pct": round(100 * sizes.min() / len(labels), 2)})
        fitted[k] = labels
    acceptable = [row for row in candidates if row["smallest_cluster_pct"] >= 5]
    chosen = max(acceptable or candidates, key=lambda row: row["silhouette"])["k"]
    labels = fitted[chosen]
    feature_frame["cluster"] = labels
    profiles = feature_frame.groupby("cluster", observed=True).agg(
        students=("student_key", "size"),
        first_start_position=("first_start_position", "mean"),
        english_course_count=("english_course_count", "mean"),
        participating_terms=("participating_terms", "mean"),
        longest_continuous_terms=("longest_continuous_terms", "mean"),
        reentry_count=("reentry_count", "mean"),
        late_participation_share=("late_participation_share", "mean"),
    ).reset_index()
    for name in names:
        profiles[name] = profiles[name].round(3)
    profiles["share_pct"] = (100 * profiles.students / len(feature_frame)).round(2)
    profiles.to_csv(output_dir / "eight_term_cluster_profiles.csv",
                    index=False, encoding="utf-8-sig")
    cross = feature_frame.groupby(["cluster", "four_path_type"], observed=True).size(
    ).rename("students").reset_index()
    cross.to_csv(output_dir / "cluster_vs_four_paths.csv", index=False,
                 encoding="utf-8-sig")
    rng = np.random.default_rng(42)
    stability = []
    for i in range(5):
        selected = rng.choice(len(scaled), size=int(0.8 * len(scaled)), replace=False)
        sample_labels = KMeans(n_clusters=chosen, n_init=10,
                               random_state=100 + i).fit_predict(scaled[selected])
        stability.append(float(adjusted_rand_score(labels[selected], sample_labels)))
    result = {
        "status": "ok", "cohort_students": len(feature_frame),
        "candidate_cluster_counts": candidates,
        "chosen_k": chosen,
        "subsample_80pct_adjusted_rand_mean": round(float(np.mean(stability)), 3),
        "subsample_80pct_adjusted_rand_range": [
            round(float(min(stability)), 3), round(float(max(stability)), 3)],
        "post_start": {
            "first_starts_with_next_observed_term": len(post),
            "continued_next_term": int(post.next_term_continued.sum()),
            "continued_next_pct": round(100 * post.next_term_continued.mean(), 2),
            "stopped_next_term": int(post.next_term_stopped.sum()),
            "stoppers_with_further_followup": int(post.eligible_reentry_followup.sum()),
            "reentered_after_immediate_stop": int(
                post.reentered_after_immediate_stop.sum()),
        },
        "limitations": ["term 8 first starters have no next term in the fixed window",
                        "clusters describe observed patterns, not student types or causes",
                        "course counts do not use incomplete 1151 grade/credit fields"],
        "student_identifiers_exported": False,
    }
    (output_dir / "eight_term_path_pattern_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
