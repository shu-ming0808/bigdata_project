"""1051–1151 大學部英語授課參與、流向與同課比較（唯讀 MySQL）。

輸出只有彙總資料，沒有學生識別碼。詳細定義見同資料夾的 README.md。
需要 pandas、numpy，以及已設定的 MySQL login-path；不需要資料庫寫入權限。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parents[1]
DEFAULT_MYSQL = Path(r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe")
TERMS = [f"{year}{semester}" for year in range(105, 115) for semester in (1, 2)] + ["1151"]
OUTCOME_COMPLETE_TERMS = TERMS[:-1]  # 此批次 1151 的學分與成績幾乎全空
LEVELS = ["beginner", "intermediate", "advanced", "unknown"]
LEVEL_ZH = {"beginner": "初級", "intermediate": "中級", "advanced": "高級", "unknown": "未知"}
SELECTED = {
    "中選(初選)", "加退選中選", "密碼中選", "人工加選", "停修", "校際選課中選",
    "暑修選課中選", "預修中選", "寒暑修選課中選", "校際暑修中選", "校際寒暑修中選",
}
WITHDRAWN = {"人工退選", "衝堂退選", "刪除本筆紀錄", "課程停開(落選)"}
WAIVER = {"免修", "抵免"}
NUMERIC = re.compile(r"^(?:\d+(?:\.\d+)?|\.\d+)$")


def frame(mysql: Path, login_path: str, database: str, sql: str) -> pd.DataFrame:
    command = [str(mysql), f"--login-path={login_path}", "--default-character-set=utf8mb4",
               "--batch", "--raw", "--quick", database]
    result = subprocess.run(command, input=(sql.rstrip("; \n") + ";\n").encode("utf-8"),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace"))
    return pd.read_csv(io.BytesIO(result.stdout), sep="\t", dtype="string",
                       keep_default_na=False).replace("NULL", pd.NA)


def controls(mysql: Path, login_path: str, database: str) -> dict[str, int]:
    term_values = ",".join(f"'{term}'" for term in TERMS)
    query = f"""SELECT
      (SELECT COUNT(*) FROM student_course_grade_raw) AS grade_rows,
      (SELECT COUNT(*) FROM enrollment_records WHERE term_code IN ({term_values})) AS enrollment_rows,
      (SELECT COUNT(*) FROM student_terms WHERE term_code IN ({term_values})) AS student_term_rows,
      (SELECT COUNT(*) FROM course_offerings WHERE term_code IN ({term_values})) AS offering_rows,
      (SELECT COUNT(*) FROM offering_english_level l JOIN course_offerings o
         ON o.offering_id=l.offering_id WHERE o.term_code IN ({term_values})) AS level_rows"""
    return {key: int(value) for key, value in frame(mysql, login_path, database, query).iloc[0].items()}


def read_sources(args: argparse.Namespace):
    rules = json.loads(args.department_rules.read_text(encoding="utf-8"))["rules"]
    mapping = {(r["code"].strip(), r["name"].strip()): r["classification"] for r in rules}
    if len(mapping) != len(rules):
        raise ValueError("系所分類規則出現重複鍵")
    term_values = ",".join(f"'{term}'" for term in TERMS)
    emi_column_count = frame(args.mysql, args.login_path, args.database, """
        SELECT COUNT(*) AS n FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'course_offerings'
          AND column_name = 'emi_raw'
    """)
    emi_expression = "o.emi_raw" if int(emi_column_count.iloc[0]["n"]) else "NULL"
    student_terms = frame(args.mysql, args.login_path, args.database, f"""
        SELECT student_key, term_code, department_code, department_name
        FROM student_terms
        WHERE term_code IN ({term_values})
    """)
    offerings = frame(args.mysql, args.login_path, args.database, f"""
        SELECT o.offering_id, o.term_code, o.course_code, o.course_name,
               o.teaching_language_raw AS teaching_language,
               o.offering_status_raw AS offering_status,
               {emi_expression} AS emi_raw,
               l.english_level
        FROM course_offerings o
        LEFT JOIN offering_english_level l ON l.offering_id = o.offering_id
        WHERE o.term_code IN ({term_values})
    """)
    records = frame(args.mysql, args.login_path, args.database, f"""
        SELECT er.source_grade_row_id AS grade_row_id, er.student_key, er.term_code,
               er.offering_id, r.course_code AS record_course_code,
               r.credits AS credits_raw, r.grade AS grade_raw,
               r.registration_attribute_name AS registration_label,
               r.allocation_result AS allocation_label
        FROM enrollment_records er
        JOIN student_course_grade_raw r ON r.grade_row_id = er.source_grade_row_id
        WHERE er.term_code IN ({term_values})
    """)
    return mapping, student_terms, offerings, records


def prepare(mapping, student_terms, offerings, records):
    for table, cols in [(student_terms, ["student_key"]),
                        (offerings, ["offering_id"]),
                        (records, ["grade_row_id", "student_key", "offering_id"])]:
        for col in cols:
            table[col] = pd.to_numeric(table[col], errors="coerce").astype("Int64")
    for table in [student_terms, offerings, records]:
        table["term_code"] = table["term_code"].fillna("").str.strip()
    for col in ["department_code", "department_name"]:
        student_terms[col] = student_terms[col].fillna("").str.strip()
    student_terms["classification"] = [mapping.get(pair, "unknown") for pair in
        zip(student_terms.department_code, student_terms.department_name)]
    if student_terms.duplicated(["student_key", "term_code"]).any():
        raise ValueError("student_terms 的學生＋學期不是唯一")
    cohort = student_terms.loc[
        (student_terms.classification == "undergraduate") &
        (student_terms.department_code != "1002") &
        (student_terms.term_code.isin(TERMS)),
        ["student_key", "term_code", "department_code"],
    ].copy()
    for col in ["course_code", "course_name", "teaching_language", "offering_status", "english_level", "emi_raw"]:
        offerings[col] = offerings[col].fillna("").str.strip()
    if offerings.offering_id.duplicated().any():
        raise ValueError("course_offerings 的 offering_id 不是唯一")
    for col in ["record_course_code", "credits_raw", "grade_raw", "registration_label", "allocation_label"]:
        records[col] = records[col].fillna("").str.strip()
    if records.grade_row_id.duplicated().any():
        raise ValueError("enrollment_records 的來源列鍵重複")
    records = records.merge(cohort, how="inner", on=["student_key", "term_code"], validate="many_to_one")
    records = records.merge(offerings, how="left", on="offering_id", validate="many_to_one",
                            suffixes=("", "_offering"))
    records["course_code"] = records["course_code"].fillna("").str.strip()
    records["course_name"] = records["course_name"].fillna("").str.strip()
    records["teaching_language"] = records["teaching_language"].fillna("").str.strip()
    records["offering_status"] = records["offering_status"].fillna("").str.strip()
    records["english_level"] = records["english_level"].fillna("").str.strip()
    records["emi_raw"] = records["emi_raw"].fillna("").str.strip()
    records["grade_num"] = pd.to_numeric(records.grade_raw.where(records.grade_raw.str.fullmatch(NUMERIC)),
                                          errors="coerce")
    records["credits_num"] = pd.to_numeric(records.credits_raw.where(records.credits_raw.str.fullmatch(NUMERIC)),
                                            errors="coerce")
    records["selected"] = (
        records.allocation_label.isin(SELECTED) &
        ~records.registration_label.isin(WAIVER) &
        (records.offering_status == "正常") & records.offering_id.notna()
    )
    records["score_ok"] = (
        records.selected & (records.registration_label == "成績已輸入") &
        records.grade_num.between(0, 100) & records.credits_num.between(0, 50)
    )
    linked = records.loc[records.offering_id.notna()].copy()
    group = linked.groupby(["student_key", "term_code", "offering_id"], observed=True,
                           sort=False, dropna=False)
    linked["source_rows_for_attempt"] = group.grade_row_id.transform("size")
    linked["score_variants"] = group.grade_num.transform("nunique")
    linked["special_status"] = (
        linked.registration_label.isin(WAIVER) | linked.allocation_label.isin(WITHDRAWN)
    )
    linked["any_special"] = group.special_status.transform("max")
    linked["ambiguous_attempt"] = (
        (linked.source_rows_for_attempt > 1) &
        ((linked.score_variants > 1) | linked.any_special)
    )
    linked = linked.sort_values(["score_ok", "grade_row_id"], ascending=[False, True])
    attempts = linked.drop_duplicates(["student_key", "term_code", "offering_id"]).copy()
    attempts.loc[attempts.ambiguous_attempt, "selected"] = False
    attempts.loc[attempts.ambiguous_attempt, "score_ok"] = False
    attempts["selected"] = attempts.selected.astype(bool)
    attempts["score_ok"] = attempts.score_ok.astype(bool)
    attempts["target"] = (
        ~attempts.course_code.str.startswith("LN") &
        ~attempts.course_name.str.contains("大一英文|進修英文|TOEIC|英文能力鑑定|英語能力鑑定", regex=True) &
        ~attempts.english_level.isin(LEVELS[:-1]) &
        attempts.teaching_language.isin(["英語", "國語", "部份英語"])
    )
    return cohort, records, attempts


def assign_prior_levels(cohort, attempts):
    seen = attempts.loc[
        attempts.selected & attempts.english_level.isin(LEVELS[:-1]),
        ["student_key", "term_code", "english_level"],
    ].drop_duplicates()
    current = seen.groupby(["student_key", "term_code"], observed=True).english_level.agg(
        lambda x: x.iloc[0] if x.nunique() == 1 else "unknown"
    ).to_dict()
    prior = []
    for student_key, rows in cohort.sort_values(["student_key", "term_code"]).groupby("student_key", sort=False):
        latest = "unknown"
        for row in rows.itertuples(index=False):
            prior.append((student_key, row.term_code, latest))
            today = current.get((student_key, row.term_code))
            if today is not None:
                latest = today
    prior = pd.DataFrame(prior, columns=["student_key", "term_code", "prior_level"])
    return cohort.merge(prior, on=["student_key", "term_code"], validate="one_to_one")


def assign_prior_grades(cohort, attempts):
    scored = attempts.loc[attempts.score_ok & attempts.credits_num.gt(0),
                          ["student_key", "term_code", "grade_num", "credits_num"]].copy()
    scored["grade_credit"] = scored.grade_num * scored.credits_num
    by_term = scored.groupby(["student_key", "term_code"], observed=True, as_index=False)[
        ["grade_credit", "credits_num"]].sum()
    by_term = cohort[["student_key", "term_code"]].merge(by_term, how="left",
        on=["student_key", "term_code"], validate="one_to_one")
    by_term[["grade_credit", "credits_num"]] = by_term[["grade_credit", "credits_num"]].fillna(0)
    by_term = by_term.sort_values(["student_key", "term_code"])
    by_term["prior_grade_credit"] = by_term.groupby("student_key").grade_credit.cumsum() - by_term.grade_credit
    by_term["prior_credits"] = by_term.groupby("student_key").credits_num.cumsum() - by_term.credits_num
    by_term["prior_average"] = np.where(by_term.prior_credits.gt(0),
        by_term.prior_grade_credit / by_term.prior_credits, np.nan)
    return cohort.merge(by_term[["student_key", "term_code", "prior_credits", "prior_average"]],
                        on=["student_key", "term_code"], validate="one_to_one")


def rate(num, den):
    return round(100 * num / den, 2) if den else None


def stage_one(cohort, attempts):
    selected = attempts.loc[attempts.selected & attempts.target].copy()
    selected["english"] = selected.teaching_language.eq("英語")
    selected["partial"] = selected.teaching_language.eq("部份英語")
    by_term = selected.groupby(["student_key", "term_code"], observed=True).agg(
        english_courses=("english", "sum"), partial_courses=("partial", "sum")
    ).reset_index()
    english_credits = selected.loc[selected.english].groupby(["student_key", "term_code"],
        observed=True).credits_num.sum(min_count=1).rename("english_credits")
    by_term = by_term.join(english_credits, on=["student_key", "term_code"])
    roster = cohort.merge(by_term, how="left", on=["student_key", "term_code"], validate="one_to_one")
    roster[["english_courses", "partial_courses", "english_credits"]] = roster[
        ["english_courses", "partial_courses", "english_credits"]].fillna(0)
    roster["english_yes"] = roster.english_courses.gt(0)
    result = []
    for level in LEVELS:
        part = roster.loc[roster.prior_level.eq(level)]
        credit_part = part.loc[part.term_code.isin(OUTCOME_COMPLETE_TERMS)]
        n = len(part)
        yes = int(part.english_yes.sum())
        result.append({"修課前可見英文級別": LEVEL_ZH[level], "學生學期數": n,
                       "曾選入英語授課的學生學期數": yes, "參與率_%": rate(yes, n),
                       "英語授課班次數_每學生學期平均": round(float(part.english_courses.mean()), 3) if n else None,
                       "英語授課學分_每學生學期平均": round(float(credit_part.english_credits.mean()), 3) if len(credit_part) else None,
                       "曾選入部分英語授課的學生學期數": int(part.partial_courses.gt(0).sum())})
    return roster, result


def stage_two(roster):
    ordered = roster[["student_key", "term_code", "prior_level", "english_yes"]].copy()
    ordered["term_order"] = ordered.term_code.map({term: i for i, term in enumerate(TERMS)})
    ordered = ordered.sort_values(["student_key", "term_order"])
    ordered["next_order"] = ordered.groupby("student_key").term_order.shift(-1)
    ordered["next_english"] = ordered.groupby("student_key").english_yes.shift(-1)
    pairs = ordered.loc[ordered.next_order.eq(ordered.term_order + 1)].copy()
    result = []
    for level in LEVELS:
        part = pairs.loc[pairs.prior_level.eq(level)]
        for current, following, label in [(False, False, "未觀察到→未觀察到"),
                                          (False, True, "未觀察到→有修讀"),
                                          (True, False, "有修讀→未觀察到"),
                                          (True, True, "有修讀→有修讀")]:
            n = int((part.english_yes.eq(current) & part.next_english.eq(following)).sum())
            denominator = int(part.english_yes.eq(current).sum())
            result.append({"本學期前可見英文級別": LEVEL_ZH[level], "相鄰學期流向": label,
                           "人次": n, "同一起點人次": denominator, "同一起點比例_%": rate(n, denominator)})
    return pairs, result


def within_model(data, adjusted):
    if len(data) == 0:
        return None
    y = data.grade_num.to_numpy(dtype=float)
    x = pd.DataFrame({"english": data.teaching_language.eq("英語").astype(float).to_numpy()}, index=data.index)
    if adjusted:
        gpa = pd.to_numeric(data.prior_average, errors="coerce")
        x["prior_average"] = gpa.fillna(gpa.median() if gpa.notna().any() else 80).to_numpy(dtype=float)
        x["prior_average_missing"] = gpa.isna().astype(float).to_numpy()
        for level in ["intermediate", "advanced", "unknown"]:
            x["level_" + level] = data.prior_level.eq(level).astype(float).to_numpy()
        departments = pd.get_dummies(data.department_code.astype(str), prefix="department", dtype=float)
        x = pd.concat([x, departments.iloc[:, 1:].set_axis(x.index)], axis=1)
    group = data["comparison_group"]
    x = x.astype(float) - x.astype(float).groupby(group, sort=False).transform("mean")
    y = y - pd.Series(y, index=data.index).groupby(group, sort=False).transform("mean").to_numpy()
    matrix = x.to_numpy(dtype=float)
    beta, _, rank, _ = np.linalg.lstsq(matrix, y, rcond=None)
    if np.linalg.norm(matrix[:, 0]) < 1e-8:
        return None
    fitted = matrix @ beta
    residual = y - fitted
    inv = np.linalg.pinv(matrix.T @ matrix)
    meat = np.zeros((matrix.shape[1], matrix.shape[1]))
    clusters = data.course_code.astype(str).to_numpy()
    unique = np.unique(clusters)
    for code in unique:
        score = matrix[clusters == code].T @ residual[clusters == code]
        meat += np.outer(score, score)
    groups = len(unique)
    n, k = len(data), int(rank)
    correction = groups / (groups - 1) * (n - 1) / (n - k) if groups > 1 and n > k else np.nan
    variance = inv @ meat @ inv * correction
    se = float(np.sqrt(max(float(variance[0, 0]), 0))) if np.isfinite(correction) else None
    estimate = float(beta[0])
    return {"英文班減國語班_調整後分數差": round(estimate, 3),
            "按課號叢集標準誤": round(se, 3) if se is not None else None,
            "95%信賴區間_近似": [round(estimate - 1.96 * se, 3), round(estimate + 1.96 * se, 3)]
                if se is not None and groups >= 10 else None,
            "學生課程紀錄數": n, "課號叢集數": groups, "模型秩": k}


def stage_three(cohort, attempts):
    candidate = attempts.loc[
        attempts.term_code.isin(OUTCOME_COMPLETE_TERMS) &
        attempts.selected & attempts.target & attempts.teaching_language.isin(["英語", "國語"]) &
        attempts.course_code.ne("") & attempts.course_name.ne("") & attempts.credits_num.gt(0)
    ].copy()
    candidate["comparison_group"] = candidate.term_code.astype(str) + ":" + candidate.course_code.astype(str)
    offered = candidate.groupby(["comparison_group", "teaching_language"], observed=True).size().unstack(fill_value=0)
    offered_groups = offered.index[(offered.get("英語", 0) > 0) & (offered.get("國語", 0) > 0)]
    candidate = candidate.loc[candidate.comparison_group.isin(offered_groups)].copy()
    scored = candidate.loc[candidate.score_ok].copy()
    counts = scored.groupby(["comparison_group", "teaching_language"], observed=True).size().unstack(fill_value=0)
    eligible = counts.index[(counts.get("英語", 0) >= 5) & (counts.get("國語", 0) >= 5)]
    eligible_attempts = candidate.loc[candidate.comparison_group.isin(eligible)]
    data = scored.loc[scored.comparison_group.isin(eligible)].copy()
    if data.empty:
        return {"同課同學期候選組數": len(offered_groups), "兩種語言各至少5筆有效成績組數": 0}, None
    data = data.merge(cohort[["student_key", "term_code", "prior_level", "prior_average", "department_code"]],
        on=["student_key", "term_code"], how="left", validate="many_to_one", suffixes=("", "_cohort"))
    data["department_code"] = data["department_code_cohort"]
    data = data.drop(columns=["department_code_cohort"])
    means = data.groupby("teaching_language", observed=True).grade_num.agg(["size", "mean"])
    score_coverage = eligible_attempts.groupby("teaching_language", observed=True).score_ok.agg(["size", "sum"])
    top_courses = (data.groupby(["course_code", "course_name"], observed=True).size()
                   .sort_values(ascending=False).head(5))
    leading_code = str(top_courses.index[0][0])
    without_leading = data.loc[data.course_code.ne(leading_code)].copy()
    prior_means = data.groupby("teaching_language", observed=True).prior_average.mean()
    result = {"同課同學期候選組數": int(len(offered_groups)),
              "兩種語言各至少5筆有效成績組數": int(len(eligible)),
              "有效成績課號數": int(data.course_code.nunique()),
              "國語班有效成績筆數": int(means.loc["國語", "size"]),
              "英語班有效成績筆數": int(means.loc["英語", "size"]),
              "國語班平均成績": round(float(means.loc["國語", "mean"]), 3),
              "英語班平均成績": round(float(means.loc["英語", "mean"]), 3),
              "兩語言分數差_未調整": round(float(means.loc["英語", "mean"] - means.loc["國語", "mean"]), 3),
              "國語班數字成績60分以上比例_%": rate(int(data.loc[data.teaching_language.eq("國語"), "grade_num"].ge(60).sum()), int(means.loc["國語", "size"])),
              "英語班數字成績60分以上比例_%": rate(int(data.loc[data.teaching_language.eq("英語"), "grade_num"].ge(60).sum()), int(means.loc["英語", "size"])),
              "有修課前英文級別筆數": int(data.prior_level.ne("unknown").sum()),
              "有修課前學業均分筆數": int(data.prior_average.notna().sum()),
              "國語班已有前期學業均分者_平均分數": round(float(prior_means.loc["國語"]), 3) if pd.notna(prior_means.loc["國語"]) else None,
              "英語班已有前期學業均分者_平均分數": round(float(prior_means.loc["英語"]), 3) if pd.notna(prior_means.loc["英語"]) else None,
              "國語班有效成績覆蓋率_%": rate(int(score_coverage.loc["國語", "sum"]), int(score_coverage.loc["國語", "size"])),
              "英語班有效成績覆蓋率_%": rate(int(score_coverage.loc["英語", "sum"]), int(score_coverage.loc["英語", "size"])),
              "同課同學期差_未調整背景": within_model(data, adjusted=False),
              "同課同學期差_調整觀察背景": within_model(data, adjusted=True),
              "有效成績筆數最多的五課": [
                  {"課號": str(code), "課名": str(name), "有效成績筆數": int(n),
                   "占全體有效成績_%": rate(int(n), len(data))}
                  for (code, name), n in top_courses.items()],
              "排除最大課號後_調整觀察背景": {
                  "排除課號": leading_code,
                  "結果": within_model(without_leading, adjusted=True) if without_leading.course_code.nunique() >= 10 else None,
              }}
    known = data.loc[data.prior_level.ne("unknown")].copy()
    known_counts = known.groupby(["comparison_group", "teaching_language"], observed=True).size().unstack(fill_value=0)
    known_groups = known_counts.index[(known_counts.get("英語", 0) >= 5) & (known_counts.get("國語", 0) >= 5)]
    known = known.loc[known.comparison_group.isin(known_groups)]
    result["已知先前級別子樣本"] = {
        "同課同學期組數": int(len(known_groups)), "有效成績筆數": int(len(known)),
        "調整後分數差": within_model(known, adjusted=True) if len(known_groups) >= 3 else None,
    }
    level_rows = []
    for level in LEVELS:
        part = data.loc[data.prior_level.eq(level)]
        for lang in ["國語", "英語"]:
            scores = part.loc[part.teaching_language.eq(lang), "grade_num"]
            level_rows.append({"先前可見英文級別": LEVEL_ZH[level], "授課語言": lang,
                               "有效成績筆數": int(len(scores)),
                               "平均成績": round(float(scores.mean()), 3) if len(scores) else None})
    return result, level_rows


def markdown(report: dict) -> str:
    controls = report["資料檢核"]
    first = report["英文程度與選課"]
    flow = report["相鄰學期流向"]
    compare = report["同課同學期比較"]
    output = ["# 英語授課課程：學生能力、修課流向與表現初步分析", "",
        f"資料：{TERMS[0]}–{TERMS[-1]}；執行時間：{report['產生時間_台灣']}。所有數字為彙總，不含學生識別碼。", "",
        "## 1. 分析範圍與資料品質", "",
        f"依學生逐學期系所代碼與名稱規則辨識大學部，主分析排除英美語文學系；共 {controls['主分析大學部學生數']:,} 位來源學生碼、{controls['主分析學生學期數']:,} 個有修課紀錄的學生學期。",
        f"來源修課列 {controls['全庫修課來源列']:,} 筆；主分析大學部來源列 {controls['主分析大學部來源列']:,} 筆，其中 {controls['主分析未配對開課來源列']:,} 筆缺可用班次鍵。",
        f"有 {controls['同一學生學期班次重複鍵組數']:,} 組多筆來源列；其中 {controls['狀態或成績衝突組數']:,} 組保守排除於參與、流向及成績分析。",
        "本分析的分母為『有修課資料可觀察到的學生學期』，不是正式在學名冊；未觀察到英語課不等於確定沒有選課。", "",
        "## 2. 修課前可見英文級別與英語授課參與", "",
        "只使用目標學期之前已觀察到的大一英文班次級別。初／中／高是修讀班級的級別，不保證等於入學原始分級；免修者、英文系例外和未觀察到分級者歸未知。課程以選入且未呈退選／免抵免的班次計，部分英語另外列。1151 學分與成績缺漏嚴重，學分平均及成績比較僅使用 1051–1142。", "",
        "| 修課前級別 | 學生學期 | 曾選入英語班 | 參與率 | 每學生學期英語班數 | 每學生學期英語學分 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in first:
        output.append(f"| {row['修課前可見英文級別']} | {row['學生學期數']:,} | {row['曾選入英語授課的學生學期數']:,} | {row['參與率_%']:.2f}% | {row['英語授課班次數_每學生學期平均']:.3f} | {row['英語授課學分_每學生學期平均']:.3f} |")
    output += ["", "## 3. 相鄰學期修課流向", "",
        "僅比較學生在前後兩個相鄰學期都有大學部修課紀錄的學期對；『未觀察到』是本資料內未配到英語授課班次，並非正式沒有選課或已畢業。", "",
        "| 本學期前級別 | 起點 | 下一學期有修讀比例 | 同起點人次 |",
        "| --- | --- | ---: | ---: |"]
    for level in LEVEL_ZH.values():
        for current, label in [("未觀察到", "未觀察到→有修讀"), ("有修讀", "有修讀→有修讀")]:
            row = next(r for r in flow if r["本學期前可見英文級別"] == level and r["相鄰學期流向"] == label)
            p = f"{row['同一起點比例_%']:.2f}%" if row["同一起點比例_%"] is not None else "資料不足"
            output.append(f"| {level} | {current} | {p} | {row['同一起點人次']:,} |")
    output += ["", "## 4. 同課程同學期的國語／英語班成績", "",
        f"限定正學分課程後，有 {compare['兩種語言各至少5筆有效成績組數']:,} 組課程與學期、{compare['有效成績課號數']:,} 個課號，兩語言各至少 5 筆有效數字成績。",
        f"國語班 {compare['國語班有效成績筆數']:,} 筆，平均 {compare['國語班平均成績']:.2f} 分；英語班 {compare['英語班有效成績筆數']:,} 筆，平均 {compare['英語班平均成績']:.2f} 分。混合所有課的直接差為 {compare['兩語言分數差_未調整']:+.2f} 分。",
        "模型固定同課號、同學期，並調整學期前可見英文級別、之前學期的學分加權平均成績、前期成績缺漏標記及學生系所。標準誤按課號分群；這是觀察資料的關聯，不是教學語言的因果效果。"]
    for name, key in [("同課同學期差，尚未調整學生背景", "同課同學期差_未調整背景"),
                      ("同課同學期差，調整已觀察學生背景", "同課同學期差_調整觀察背景")]:
        model = compare[key]
        if model is None:
            output.append(f"{name}：樣本不足。")
        else:
            ci = model["95%信賴區間_近似"]
            text_ci = f"；近似 95% 信賴區間 [{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else "；叢集數不足，不列信賴區間"
            output.append(f"{name}：英語班減國語班 {model['英文班減國語班_調整後分數差']:+.2f} 分{text_ci}。")
    known = compare["已知先前級別子樣本"]
    if known["調整後分數差"] is not None:
        diff = known["調整後分數差"]["英文班減國語班_調整後分數差"]
        output.append(f"只看修課前已有可見級別的子樣本（{known['有效成績筆數']:,} 筆、{known['同課同學期組數']} 組），調整後差異為 {diff:+.2f} 分；此子樣本仍有選擇差異。")
    output += ["", f"其中有修課前英文級別的有效成績筆數：{compare['有修課前英文級別筆數']:,}／{compare['國語班有效成績筆數'] + compare['英語班有效成績筆數']:,}；有之前學期均分者 {compare['有修課前學業均分筆數']:,}。級別未知者保留為一類，不能視為初級。",
        f"有前期成績者的學期前均分：國語班 {compare['國語班已有前期學業均分者_平均分數']:.2f}、英語班 {compare['英語班已有前期學業均分者_平均分數']:.2f} 分，顯示兩組在可見背景上並非完全相同。",
        f"有效成績覆蓋率：國語班 {compare['國語班有效成績覆蓋率_%']:.2f}%，英語班 {compare['英語班有效成績覆蓋率_%']:.2f}%；若兩組差異大，完成者的平均分數比較可能有選擇偏差。", "",
        f"有效成績中，達 60 分以上的比例：國語班 {compare['國語班數字成績60分以上比例_%']:.2f}%，英語班 {compare['英語班數字成績60分以上比例_%']:.2f}%。這只是數字門檻描述，未另判讀校方各類課程的正式及格規則。", "",
        "有效成績筆數最多的五個課號：", "",
        "| 課號 | 課名 | 有效成績筆數 | 占全體 |", "| --- | --- | ---: | ---: |"]
    for row in compare["有效成績筆數最多的五課"]:
        output.append(f"| {row['課號']} | {row['課名']} | {row['有效成績筆數']:,} | {row['占全體有效成績_%']:.2f}% |")
    sensitivity = compare["排除最大課號後_調整觀察背景"]
    if sensitivity["結果"] is not None:
        difference = sensitivity["結果"]["英文班減國語班_調整後分數差"]
        output.append(f"\n排除筆數最多的課號 {sensitivity['排除課號']} 後，調整後差異為 {difference:+.2f} 分，用於檢查結果是否主要由單一課號主導。")
    output += ["",
        "## 5. 解讀邊界", "",
        "同課號同學期仍可能由不同教師授課，課綱、評量與選課資格也可能不同。調整模型只能處理現有欄位，不能消除未觀察的英文檢定成績、學生動機和教師差異。沒有共同英文前後測，本報告不能判定英文能力是否進步。", "",
        "資料來源：本機 MySQL 的 student_course_grade_raw、enrollment_records、student_terms、course_offerings、offering_english_level；系所分類規則為本資料夾 undergraduate_department_rules.json。完整彙總與分母見 analysis_results.json。", ""]
    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql", type=Path, default=DEFAULT_MYSQL)
    parser.add_argument("--login-path", default="codex-local")
    parser.add_argument("--database", default="ncu_course_flow_1150012")
    parser.add_argument("--department-rules", type=Path, default=HERE / "undergraduate_department_rules.json")
    parser.add_argument("--output-dir", type=Path, default=HERE)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_]+", args.database):
        raise ValueError("資料庫名稱只能包含英數字與底線")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.login_path):
        raise ValueError("login-path 格式不正確")
    before = controls(args.mysql, args.login_path, args.database)
    mapping, student_terms, offerings, raw = read_sources(args)
    after = controls(args.mysql, args.login_path, args.database)
    if before != after:
        raise RuntimeError("分析期間資料表筆數改變，請重跑以確保同一版本")
    if len(raw) != before["enrollment_rows"] or len(offerings) != before["offering_rows"]:
        raise RuntimeError("讀取筆數與資料庫總數不符")
    cohort, records, attempts = prepare(mapping, student_terms, offerings, raw)
    cohort = assign_prior_levels(cohort, attempts)
    cohort = assign_prior_grades(cohort, attempts)
    roster, selection = stage_one(cohort, attempts)
    pairs, flow = stage_two(roster)
    comparison, comparison_by_level = stage_three(cohort, attempts)
    diagnostics = {
        "全庫修課來源列": before["grade_rows"],
        "主分析大學部學生數": int(cohort.student_key.nunique()),
        "主分析學生學期數": int(len(cohort)),
        "主分析大學部來源列": int(len(records)),
        "主分析未配對開課來源列": int(records.offering_id.isna().sum()),
        "主分析缺授課語言來源列": int(records.teaching_language.eq("").sum()),
        "同一學生學期班次重複鍵組數": int(attempts.source_rows_for_attempt.gt(1).sum()),
        "狀態或成績衝突組數": int(attempts.ambiguous_attempt.sum()),
        "主分析去重後班次紀錄數": int(len(attempts)),
        "主分析可用數字成績班次數": int(attempts.score_ok.sum()),
        "相鄰學期且兩期均可觀察對數": int(len(pairs)),
        "資料庫表筆數_分析前後一致": before,
    }
    report = {"產生時間_台灣": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z"),
              "資料檢核": diagnostics, "英文程度與選課": selection,
              "相鄰學期流向": flow, "同課同學期比較": comparison,
              "同課比較依英文級別_描述統計": comparison_by_level}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "analysis_results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "分析結果.md").write_text(markdown(report), encoding="utf-8")
    print("Completed. Wrote analysis_results.json and the Markdown report.")


if __name__ == "__main__":
    main()
