"""Build a local CE2005 snapshot from the 115-0012 course offerings export."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from recommend_teachers import HERE, TERMS, rank_teachers

COLUMNS = {
    "學年學期": "term_code", "課程流水號": "serial", "課程代碼": "course_code",
    "課程名稱": "course_name", "開課系所名稱": "department_name", "課程屬性": "course_attribute",
    "所屬學制名稱": "degree_level", "授課語言": "teaching_language_raw",
    "是否為EMI課程": "emi", "授課教師": "instructor_name", "授課教師人數": "count",
    "開課狀態": "status",
}
SCORES = {"同課經驗": "same_course_points", "正式 EMI": "formal_emi_points",
          "英語授課": "english_teaching_points", "相關課程": "related_course_points",
          "新近性": "overall_recency_points"}


def build(path):
    rows = pd.read_csv(path, usecols=list(COLUMNS), dtype=str, keep_default_na=False).rename(columns=COLUMNS)
    rows = rows.apply(lambda col: col.str.strip())
    rows = rows.loc[rows.term_code.isin(TERMS) & rows.serial.ne("")]
    rows = rows.loc[~rows.duplicated(["term_code", "serial"], keep=False)]
    rows = rows.loc[rows.status.eq("正常") & rows["count"].eq("1") & rows.instructor_name.ne("")].copy()
    rows["formal_emi_status"] = rows.emi.map({"是": "yes", "否": "no"}).fillna("unknown")
    rows["offering_id"] = rows.term_code + "-" + rows.serial
    with TemporaryDirectory() as tmp:
        args = argparse.Namespace(required_only=True, course_code="CE2005", output_dir=Path(tmp))
        top = rank_teachers(args, rows)
    candidates = []
    for c in top:
        history = rows.loc[rows.department_name.eq("資訊工程學系") & rows.instructor_name.eq(c["instructor_name"])]
        history = history.assign(same=history.course_code.eq(args.course_code)).sort_values(
            ["same", "term_code", "serial"], ascending=[False, False, True])
        evidence = [{"id": r.offering_id, "term": r.term_code, "course_code": r.course_code, "course": f"{r.course_code} {r.course_name}",
                     "language": r.teaching_language_raw or "未知", "emi": r.emi if r.emi in ("是", "否") else "未知"}
                    for r in history.itertuples()]
        candidates.append({"id": f"R{c['rank']}", "name": f"候選教師 {c['rank']}",
                           "scores": {k: c[v] for k,v in SCORES.items()}, "evidence": evidence})
    if not candidates:
        raise ValueError("CE2005 缺少候選資料")
    return {"course_code": args.course_code, "version": "115-0012-csv", "candidates": candidates}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("offerings", type=Path)
    case = build(parser.parse_args().offerings)
    dest = HERE / "outputs/demo/CE2005.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.with_suffix(".tmp").write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
    dest.with_suffix(".tmp").replace(dest)
    print(f"已產生 {len(case['candidates'])} 名代碼化候選人：{dest.name}")
