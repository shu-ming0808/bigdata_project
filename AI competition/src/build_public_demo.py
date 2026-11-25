"""Generate a public, fully fictional Power BI demo without reading school data.

The only scoring entry point is the existing rank_teachers function. Public data
are invented here, never copied or perturbed from outputs/, CSVs or a database.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import uuid

import pandas as pd

from recommend_teachers import TERMS, rank_teachers

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public_demo"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/"
VERSION = "synthetic-public-v1"
SCORE_COLUMNS = {
    "同課經驗": "same_course_points", "正式 EMI": "formal_emi_points",
    "英語授課": "english_teaching_points", "相關課程": "related_course_points",
    "新近性": "overall_recency_points",
}


def fictional_offerings() -> list[dict]:
    names = {
        "DEMO101": "資料結構基礎", "DEMO111": "資料結構實作",
        "DEMO201": "系統架構概論", "DEMO211": "系統架構實作",
        "DEMO301": "網路通訊基礎", "DEMO311": "網路通訊實作",
        "DEMO401": "量子運算入門",
    }
    # Explicit invented scenarios, independent of every real instructor/course.
    plans = [
        ("A", "DEMO101", ["1091", "1111", "1141"], "英語", "yes"),
        ("A", "DEMO111", ["1122", "1142"], "英語", "yes"),
        ("B", "DEMO101", ["1061", "1081", "1101"], "國語", "no"),
        ("B", "DEMO111", ["1112"], "英語", "unknown"),
        ("C", "DEMO101", ["1131"], "英語", "yes"),
        ("C", "DEMO201", ["1121", "1141"], "英語", "yes"),
        ("D", "DEMO201", ["1082", "1102", "1132"], "國語", "no"),
        ("D", "DEMO211", ["1142"], "英語", "yes"),
        ("E", "DEMO201", ["1111"], "國語", "unknown"),
        ("E", "DEMO301", ["1122", "1142"], "英語", "yes"),
        ("B", "DEMO301", ["1092", "1112"], "國語", "no"),
        ("D", "DEMO311", ["1131", "1151"], "英語", "yes"),
        ("F", "DEMO401", ["1132", "1151"], "國語", "unknown"),
    ]
    rows = []
    for teacher, code, terms, language, emi in plans:
        for term in terms:
            rows.append({
                "offering_id": f"PUBLIC-O{len(rows)+1:04d}", "term_code": term,
                "course_code": code, "course_name": names[code],
                "department_name": "資訊工程學系",  # Generic fictitious department.
                "course_attribute": "必修" if code.endswith("01") else "選修",
                "degree_level": "學士班", "teaching_language_raw": language,
                "formal_emi_status": emi, "instructor_name": f"示例教師 {teacher}",
            })
    return rows


def build_cases(rows: list[dict]) -> list[dict]:
    frame = pd.DataFrame(rows)
    with TemporaryDirectory(prefix="fictional-teacher-demo-") as temp:
        options = argparse.Namespace(required_only=True, course_code=None, output_dir=Path(temp))
        with contextlib.redirect_stdout(io.StringIO()):
            ranked = rank_teachers(options, frame.copy())
    cases = []
    for code in sorted({r["course_code"] for r in ranked}):
        selected = sorted((r for r in ranked if r["course_code"] == code), key=lambda r: r["rank"])
        candidates = []
        for result in selected:
            teacher = result["instructor_name"]
            history = [r for r in rows if r["instructor_name"] == teacher]
            evidence = [{
                "id": r["offering_id"], "term": r["term_code"],
                "course_code": r["course_code"], "course": r["course_name"],
                "language": r["teaching_language_raw"],
                "emi": {"yes": "是", "no": "否", "unknown": "未知"}[r["formal_emi_status"]],
            } for r in sorted(history, key=lambda r: (r["term_code"], r["offering_id"]))]
            candidates.append({
                "id": "PUBLIC-T" + teacher[-1], "name": teacher,
                "scores": {name: result[col] for name, col in SCORE_COLUMNS.items()},
                "total_score": result["score_0_to_100"], "evidence": evidence,
            })
        cases.append({"course_code": code, "version": VERSION, "candidates": candidates})
    return cases


def powerbi_tables(cases: list[dict]) -> dict[str, list[dict]]:
    courses, candidates, evidence = [], [], []
    for case in cases:
        code = case["course_code"]
        courses.append({"CourseCode": code, "CandidateCount": len(case["candidates"]),
                        "Coverage": "合成示例：足三人" if len(case["candidates"]) >= 3 else "合成示例：不足三人"})
        for rank, candidate in enumerate(case["candidates"], 1):
            key = code + "|" + candidate["id"]
            history = candidate["evidence"]
            same = sum(e["course_code"] == code for e in history)
            english = sum(e["language"] == "英語" for e in history)
            formal = sum(e["emi"] == "是" for e in history)
            scores = candidate["scores"]
            candidates.append({
                "CandidateKey": key, "CourseCode": code, "Rank": rank,
                "Teacher": candidate["name"], "TotalScore": candidate["total_score"],
                "SameCourseScore": scores["同課經驗"], "EMIScore": scores["正式 EMI"],
                "EnglishScore": scores["英語授課"], "RelatedScore": scores["相關課程"],
                "RecencyScore": scores["新近性"],
                "Summary": f"完全虛構。此課 {same} 班；英語 {english} 班；正式 EMI {formal} 班。分數由五構面規則計算。",
                "Review": "合成展示，非真實推薦。聘任、意願、負荷與時段均未知；不得解讀為教學品質。",
            })
            for item in history:
                evidence.append({
                    "CandidateKey": key, "EvidenceID": item["id"], "Term": item["term"],
                    "CourseCode": item["course_code"], "Course": item["course"],
                    "Language": item["language"], "FormalEMI": item["emi"], "Teacher": candidate["name"],
                })
    return {"Courses": courses, "Candidates": candidates, "Evidence": evidence}


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def m_literal(value):
    # JSON strings and M strings have different escaping conventions.
    if isinstance(value, str):
        return '"' + value.replace('"', '""').replace("\r", "#(cr)").replace("\n", "#(lf)") + '"'
    if isinstance(value, (int, float)):
        return str(value)
    raise TypeError(type(value))


def build_model(destination: Path, tables: dict):
    semantic = destination / "EMI_Public.SemanticModel"
    save(semantic / "definition.pbism", {"version": "1.0", "settings": {}})
    definitions = []
    for name, rows in tables.items():
        columns = list(rows[0])
        types = {col: "int64" if isinstance(rows[0][col], int) else
                 "double" if isinstance(rows[0][col], float) else "string" for col in columns}
        m_types = {"int64": "Int64.Type", "double": "type number", "string": "type text"}
        data = ",\n        ".join("{" + ", ".join(m_literal(row[col]) for col in columns) + "}" for row in rows)
        transforms = ", ".join("{" + m_literal(col) + ", " + m_types[types[col]] + "}" for col in columns)
        expression = ["let", "    Source = #table({" + ", ".join(m_literal(col) for col in columns) + "}, {",
                      "        " + data, "    }),", "    Typed = Table.TransformColumnTypes(Source, {" + transforms + "})",
                      "in", "    Typed"]
        table = {"name": name, "columns": [{"name": col, "dataType": types[col], "sourceColumn": col,
                 "summarizeBy": "none"} for col in columns], "partitions": [{"name": name, "mode": "import",
                 "source": {"type": "m", "expression": expression}}]}
        if name == "Candidates":
            table["measures"] = [{"name": "SelectedCourseScore", "formatString": "0.00",
                "expression": "IF(HASONEVALUE(Courses[CourseCode]), MAX(Candidates[TotalScore]), BLANK())"}]
        definitions.append(table)
    relationships = []
    for child, key, parent in [("Candidates", "CourseCode", "Courses"), ("Evidence", "CandidateKey", "Candidates")]:
        relationships.append({"name": str(uuid.uuid5(uuid.NAMESPACE_URL, f"fictional:{child}:{parent}")),
            "fromTable": child, "fromColumn": key, "toTable": parent, "toColumn": key,
            "crossFilteringBehavior": "oneDirection"})
    save(semantic / "model.bim", {"compatibilityLevel": 1567, "model": {"culture": "zh-TW",
        "defaultPowerBIDataSourceVersion": "powerBI_V3", "tables": definitions, "relationships": relationships}})


def lit(value):
    return {"expr": {"Literal": {"Value": value}}}


def color(value):
    return {"solid": {"color": lit("'" + value + "'")}}


def column(table, name):
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def build_report(destination: Path):
    save(destination / "EMI_Public.pbip", {"version": "1.0", "artifacts": [{"report": {"path": "EMI_Public.Report"}}],
        "settings": {"enableAutoRecovery": True}})
    report = destination / "EMI_Public.Report"
    save(report / "definition.pbir", {"version": "4.0", "datasetReference": {"byPath": {"path": "../EMI_Public.SemanticModel"}}})
    definition = report / "definition"
    save(definition / "version.json", {"$schema": SCHEMA + "report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    save(definition / "report.json", {"$schema": SCHEMA + "report/definition/report/3.0.0/schema.json", "themeCollection": {}})
    save(definition / "pages/pages.json", {"$schema": SCHEMA + "report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": ["CourseSelection", "CandidateDetail"], "activePageName": "CourseSelection"})
    for page, title in [("CourseSelection", "01 課程與候選比較"), ("CandidateDetail", "02 教師得分與授課證據")]:
        config = {"$schema": SCHEMA + "report/definition/page/2.0.0/schema.json", "name": page,
            "displayName": title, "width": 1280, "height": 720, "displayOption": "FitToPage",
            "objects": {"background": [{"properties": {"color": color("#F0F3F5"), "transparency": lit("0D")}}]}}
        if page == "CandidateDetail":
            config["visualInteractions"] = [{"source": "TeacherScores", "target": target, "type": "DataFilter"}
                for target in ("Reasons", "Evidence")] + [{"source": "TeacherScores", "target": "Selector", "type": "NoFilter"}]
        save(definition / f"pages/{page}/page.json", config)
        heading = {"$schema": SCHEMA + "report/definition/visualContainer/2.1.0/schema.json", "name": "Heading",
            "position": {"x": 24, "y": 12, "width": 990, "height": 50, "z": 0, "tabOrder": 0},
            "visual": {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [
                {"value": title + "｜完全合成展示，非真實教師資料", "textStyle": {"fontFamily": "Microsoft JhengHei",
                 "fontSize": "19pt", "color": "#243746"}}]}]}}]}}}
        save(definition / f"pages/{page}/visuals/Heading/visual.json", heading)

    def visual(page, name, kind, table, columns, rectangle, title, sort=None):
        query = {"queryState": {"Values": {"projections": [{"field": column(table, col),
            "queryRef": table + "." + col, "displayName": label} for col, label in columns]}}}
        if sort:
            query["sortDefinition"] = {"sort": [{"field": column(table, sort), "direction": "Ascending"}]}
        value = {"$schema": SCHEMA + "report/definition/visualContainer/2.1.0/schema.json", "name": name,
            "position": dict(zip(["x", "y", "width", "height"], rectangle), z=1, tabOrder=1),
            "visual": {"visualType": kind, "query": query, "visualContainerObjects": {
                "title": [{"properties": {"show": lit("true"), "text": lit("'" + title + "'"),
                    "fontSize": lit("12D"), "fontColor": color("#243746"), "titleWrap": lit("true")}}],
                "background": [{"properties": {"color": color("#FFFFFF"), "transparency": lit("0D")}}]}}}
        if kind == "slicer":
            value["visual"]["syncGroup"] = {"groupName": "PublicCourse", "fieldChanges": True, "filterChanges": True}
            value["visual"]["objects"] = {
                "selection": [{"properties": {"singleSelect": lit("true"), "selectAllCheckboxEnabled": lit("false")}}],
                "general": [{"properties": {"filter": {"filter": {"Version": 2,
                    "From": [{"Name": "c", "Entity": "Courses", "Type": 0}], "Where": [{"Condition": {"In": {
                        "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "c"}}, "Property": "CourseCode"}}],
                        "Values": [[{"Literal": {"Value": "'DEMO101'"}}]]}}}]}}}}]}
        if kind == "tableEx":
            value["visual"]["objects"] = {"columnHeaders": [{"properties": {"fontSize": lit("10D"), "fontColor": color("#243746")}}],
                "values": [{"properties": {"fontSize": lit("10D"), "wordWrap": lit("true"),
                    "fontColorPrimary": color("#243746"), "fontColorSecondary": color("#243746")}}]}
        save(definition / f"pages/{page}/visuals/{name}/visual.json", value)

    for page in ("CourseSelection", "CandidateDetail"):
        visual(page, "Selector", "slicer", "Courses", [("CourseCode", "示例課號")], [24, 76, 260, 210], "先選單一課程｜跨頁同步")
    visual("CourseSelection", "Coverage", "tableEx", "Courses", [("CourseCode", "課號"), ("CandidateCount", "候選人數"),
        ("Coverage", "合成情境")], [308, 76, 948, 210], "四門虛構課程｜含候選不足三人情境")
    visual("CourseSelection", "Ranking", "tableEx", "Candidates", [("Rank", "排名"), ("Teacher", "示例教師"),
        ("TotalScore", "證據總分"), ("SameCourseScore", "同課"), ("EMIScore", "正式EMI"), ("EnglishScore", "英語"),
        ("RelatedScore", "相關課"), ("RecencyScore", "新近性")], [24, 310, 1232, 380], "與正式程式相同的五構面計分｜不是教學品質", "Rank")
    visual("CandidateDetail", "Reasons", "tableEx", "Candidates", [("Teacher", "示例教師"), ("Summary", "合成事實摘要"),
        ("Review", "待確認事項")], [24, 310, 1232, 145], "點橫條連動摘要")
    visual("CandidateDetail", "Evidence", "tableEx", "Evidence", [("Teacher", "示例教師"), ("EvidenceID", "合成證據ID"),
        ("Term", "示例學期"), ("Course", "虛構授課課程"), ("Language", "授課語言"), ("FormalEMI", "正式EMI")],
        [24, 479, 1232, 211], "點橫條連動證據｜紀錄完全虛構", "Term")
    measure = {"Measure": {"Expression": {"SourceRef": {"Entity": "Candidates"}}, "Property": "SelectedCourseScore"}}
    save(definition / "pages/CandidateDetail/visuals/TeacherScores/visual.json", {
        "$schema": SCHEMA + "report/definition/visualContainer/2.1.0/schema.json", "name": "TeacherScores",
        "position": {"x": 308, "y": 76, "width": 948, "height": 210, "z": 1, "tabOrder": 2},
        "visual": {"visualType": "clusteredBarChart", "query": {"queryState": {
            "Category": {"projections": [{"field": column("Candidates", "Teacher"), "queryRef": "Candidates.Teacher"}]},
            "Y": {"projections": [{"field": measure, "queryRef": "Candidates.SelectedCourseScore"}]}},
            "sortDefinition": {"sort": [{"field": measure, "direction": "Descending"}]}}, "objects": {
            "labels": [{"properties": {"show": lit("true"), "labelPrecision": lit("2D")}}],
            "valueAxis": [{"properties": {"start": lit("0D"), "end": lit("100D")}}],
            "dataPoint": [{"properties": {"defaultColor": color("#008C95")}}]}, "visualContainerObjects": {
            "title": [{"properties": {"show": lit("true"), "fontColor": color("#243746"),
                "text": lit("'示例教師分數（高 → 低）｜請先選單一課程'")}}],
            "background": [{"properties": {"color": color("#FFFFFF"), "transparency": lit("0D")}}]}}})
    for page, target, text in [("CourseSelection", "CandidateDetail", "查看推薦 →"), ("CandidateDetail", "CourseSelection", "← 返回選課")]:
        save(definition / f"pages/{page}/visuals/Navigation/visual.json", {
            "$schema": SCHEMA + "report/definition/visualContainer/2.1.0/schema.json", "name": "Navigation",
            "position": {"x": 1050, "y": 15, "width": 206, "height": 40, "z": 5, "tabOrder": 3},
            "visual": {"visualType": "actionButton", "objects": {"text": [{"properties": {"show": lit("true")}},
                {"selector": {"id": "default"}, "properties": {"text": lit("'" + text + "'"), "fontSize": lit("15D")}}]},
                "visualContainerObjects": {"visualLink": [{"properties": {"show": lit("true"),
                    "type": lit("'PageNavigation'"), "navigationSection": lit("'" + target + "'")}}]}}})


def build(destination: Path = PUBLIC):
    rows = fictional_offerings()
    cases = build_cases(rows)
    tables = powerbi_tables(cases)
    save(destination / "fictional_offerings.json", rows)
    for case in cases:
        save(destination / f"cases/{case['course_code']}.json", case)
    for name, records in tables.items():
        save(destination / f"data/{name}.json", records)
    build_model(destination, tables)
    build_report(destination)
    audit = {"data_source": VERSION, "source": "hand-authored fictional scenarios; no real data read",
        "scoring": "src/recommend_teachers.py::rank_teachers (same five-component rules)",
        "term_order": TERMS, "source_offerings": len(rows), "courses": len(cases),
        "candidate_course_rows": len(tables["Candidates"]), "evidence_links": len(tables["Evidence"]),
        "not_real_results": True, "external_connections": 0}
    save(destination / "manifest.json", audit)
    return audit


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
