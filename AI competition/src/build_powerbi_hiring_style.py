"""Graft the user-selected PBIX backgrounds onto a separate two-page EMI PBIP.

Preserves the source PBIX and the SQL Import model; no database writes/publish.
"""
import copy
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/powerbi_two_pages"
TEMPLATE = ROOT / "outputs/Employee Hiring and History.pbix"
OUT = ROOT / "outputs/powerbi_hiring_style"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/"

def save(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def load(p):
    return json.loads(p.read_text(encoding="utf-8"))

def lit(value):
    return {"expr": {"Literal": {"Value": value}}}

def color(value):
    return {"solid": {"color": lit("'" + value + "'")}}

def column(table, name):
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}

def main():
    model = load(SOURCE / "EMI.SemanticModel/model.bim")
    candidates = next(t for t in model["model"]["tables"] if t["name"] == "Candidates")
    measures = {m["name"]: m for m in candidates.get("measures", [])}
    measures["SelectedCourseScore"] = {
        "name": "SelectedCourseScore", "formatString": "0.00",
        "expression": "IF(HASONEVALUE(Courses[CourseCode]), MAX(Candidates[TotalScore]), BLANK())"}
    candidates["measures"] = list(measures.values())
    # Snapshot contains at most three nominees per course, not all department teachers.
    candidates["measures"].extend([
        {"name": "AllTargetCourses", "expression": "CALCULATE(DISTINCTCOUNT(Courses[CourseCode]), REMOVEFILTERS(Courses))", "formatString": "0"},
        {"name": "CoveredCourses", "expression": "CALCULATE(COUNTROWS(FILTER(Courses, Courses[CandidateCount] >= 3)), REMOVEFILTERS(Courses))", "formatString": "0"}])
    save(OUT / "EMI.SemanticModel/model.bim", model)
    save(OUT / "EMI.SemanticModel/definition.pbism", load(SOURCE / "EMI.SemanticModel/definition.pbism"))
    save(OUT / "EMI.pbip", {"version": "1.0", "artifacts": [{"report": {"path": "EMI.Report"}}],
                          "settings": {"enableAutoRecovery": True}})
    report = OUT / "EMI.Report"
    save(report / "definition.pbir", {
        "$schema": SCHEMA + "report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": "../EMI.SemanticModel"}}})
    definition = report / "definition"
    save(definition / "version.json", load(SOURCE / "EMI.Report/definition/version.json"))
    resources = report / "StaticResources/RegisteredResources"
    resources.mkdir(parents=True, exist_ok=True)
    images = {}
    with zipfile.ZipFile(TEMPLATE) as z:
        template_layout = json.loads(z.read("Report/Layout").decode("utf-16-le"))
        for page, title in [("CourseSelection", "New Hires"), ("CandidateDetail", "Bad Hires")]:
            section = next(s for s in template_layout["sections"] if s["displayName"] == title)
            bg = json.loads(section["config"])["objects"]["background"][0]["properties"]["image"]
            filename = bg["image"]["url"]["expr"]["ResourcePackageItem"]["ItemName"]
            (resources / filename).write_bytes(z.read("Report/StaticResources/RegisteredResources/" + filename))
            images[page] = filename
    theme = {"name": "EMI Hiring Style", "dataColors": ["#00A6A6", "#486D9B", "#F2AE45", "#8267A5", "#607D8B"],
             "background": "#FFFFFF", "foreground": "#252A34", "tableAccent": "#008B8B",
             "textClasses": {"label": {"fontFace": "Microsoft JhengHei", "fontSize": 11},
                            "title": {"fontFace": "Microsoft JhengHei", "fontSize": 13}}}
    save(resources / "EMIHiringTheme.json", theme)
    save(definition / "report.json", {
        "$schema": SCHEMA + "report/definition/report/3.0.0/schema.json",
        "themeCollection": {"customTheme": {"name": "EMIHiringTheme", "type": "RegisteredResources",
            "reportVersionAtImport": {"visual": "2.1.0", "page": "2.0.0", "report": "3.0.0"}}},
        "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources", "items":
            [{"name": n, "path": n, "type": "Image"} for n in images.values()] +
            [{"name": "EMIHiringTheme", "path": "EMIHiringTheme.json", "type": "CustomTheme"}]}]})
    save(definition / "pages/pages.json", {
        "$schema": SCHEMA + "report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": ["CourseSelection", "CandidateDetail"], "activePageName": "CourseSelection"})

    def write_visual(page, v, rect, title):
        v = copy.deepcopy(v)
        v["position"].update(dict(zip(["x", "y", "width", "height"], rect)))
        containers = v["visual"].setdefault("visualContainerObjects", {})
        containers["title"] = [{"properties": {"show": lit("true"), "text": lit("'" + title + "'"),
            "fontSize": lit("12D"), "fontColor": color("#252A34"), "titleWrap": lit("true")}}]
        containers["background"] = [{"properties": {"color": color("#FFFFFF"), "transparency": lit("100D")}}]
        objects = v["visual"].setdefault("objects", {})
        if v["visual"]["visualType"] == "tableEx":
            objects["columnHeaders"] = [{"properties": {"fontSize": lit("10D"),
                "fontColor": color("#252A34"), "backColor": color("#E7F3F3")}}]
            objects["values"] = [{"properties": {"fontSize": lit("10D"), "wordWrap": lit("true"),
                "fontColorPrimary": color("#252A34"), "fontColorSecondary": color("#252A34"),
                "backColorPrimary": color("#FFFFFF"), "backColorSecondary": color("#F2F7F7")}}]
        save(definition / f"pages/{page}/visuals/{v['name']}/visual.json", v)

    def copy_visual(page, source_page, name, rect, title):
        v = load(SOURCE / f"EMI.Report/definition/pages/{source_page}/visuals/{name}/visual.json")
        write_visual(page, v, rect, title)

    for page, name in [("CourseSelection", "01 課程與候選比較"), ("CandidateDetail", "02 教師得分與授課證據")]:
        bg = {"image": {"name": lit("'" + images[page] + "'"), "url": {"expr": {"ResourcePackageItem": {
            "PackageName": "RegisteredResources", "PackageType": 1, "ItemName": images[page]}}},
            "scaling": lit("'Fit'")}}
        p = {"$schema": SCHEMA + "report/definition/page/2.0.0/schema.json",
             "name": page, "displayName": name, "width": 1280, "height": 720, "displayOption": "FitToPage",
             "objects": {"background": [{"properties": {"color": color("#424242"),
                "transparency": lit("0D"), "image": bg}}]}}
        if page == "CandidateDetail":
            p["visualInteractions"] = [
                {"source": "TeacherScores", "target": target, "type": "DataFilter"}
                for target in ["ReasonDetail", "EvidenceDetail"]] + [
                {"source": "TeacherScores", "target": "SelectCourseCandidateDetail", "type": "NoFilter"}]
        save(definition / f"pages/{page}/page.json", p)
        title = {"$schema": SCHEMA + "report/definition/visualContainer/2.1.0/schema.json",
            "name": "PageHeading", "position": {"x": 32, "y": 12, "width": 1000, "height": 40, "z": 5, "tabOrder": 0},
            "visual": {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": [
                {"textRuns": [{"value": name + "｜EMI 師資證據助理",
                "textStyle": {"fontFamily": "Microsoft JhengHei", "fontSize": "20pt", "color": "#FFFFFF"}}]}]}}]}}}
        save(definition / f"pages/{page}/visuals/PageHeading/visual.json", title)

    copy_visual("CourseSelection", "CourseSelection", "SelectCourseCourseSelection", [965, 82, 270, 195], "選擇一門課程（跨頁同步）")
    copy_visual("CourseSelection", "CourseSelection", "Overview", [45, 82, 865, 195], "課程候選覆蓋｜候選為歷史證據名單")
    copy_visual("CourseSelection", "CandidateDetail", "RankDetail", [45, 350, 1190, 314], "候選比較｜五構面歷史證據分數，非教學品質")
    copy_visual("CandidateDetail", "CandidateDetail", "SelectCourseCandidateDetail", [44, 83, 265, 205], "目前課程｜請選單一課號")
    copy_visual("CandidateDetail", "CandidateDetail", "ReasonDetail", [44, 348, 265, 326], "推薦摘要與待核對事項")
    copy_visual("CandidateDetail", "CandidateDetail", "EvidenceDetail", [370, 348, 860, 326], "授課證據｜點上方教師橫條篩選")

    measure = {"Measure": {"Expression": {"SourceRef": {"Entity": "Candidates"}}, "Property": "SelectedCourseScore"}}
    bar = {"$schema": SCHEMA + "report/definition/visualContainer/2.1.0/schema.json",
        "name": "TeacherScores", "position": {"x": 370, "y": 83, "width": 860, "height": 205, "z": 1, "tabOrder": 3},
        "visual": {"visualType": "clusteredBarChart", "query": {"queryState": {
            "Category": {"projections": [{"field": column("Candidates", "Teacher"), "queryRef": "Candidates.Teacher", "displayName": "候選教師"}]},
            "Y": {"projections": [{"field": measure, "queryRef": "Candidates.SelectedCourseScore", "displayName": "證據總分"}]}},
            "sortDefinition": {"sort": [{"field": measure, "direction": "Descending"}]}},
            "objects": {"labels": [{"properties": {"show": lit("true"), "labelPrecision": lit("2D")}}],
                "valueAxis": [{"properties": {"start": lit("0D"), "end": lit("100D")}}],
                "dataPoint": [{"properties": {"defaultColor": color("#008F95")}}]}}}
    write_visual("CandidateDetail", bar, [370, 83, 860, 205], "候選教師證據總分（高 → 低）｜目前快照最多三位")

    for page, source, button, rect in [
        ("CourseSelection", "CourseSelection", "OpenRecommendation", [1050, 12, 190, 38]),
        ("CandidateDetail", "CandidateDetail", "ReturnCourses", [1050, 12, 190, 38])]:
        v = load(SOURCE / f"EMI.Report/definition/pages/{source}/visuals/{button}/visual.json")
        v["position"].update(dict(zip(["x", "y", "width", "height"], rect)))
        save(definition / f"pages/{page}/visuals/{button}/visual.json", v)
    (OUT / "操作說明.md").write_text(
        "# 範例設計嫁接版：兩頁式 EMI 報表\n\n"
        "以 Power BI Desktop 開啟本目錄 EMI.pbip，完成原 SQL Server Windows 驗證與重新整理。\n"
        "第一頁選單一課號，再按查看推薦；第二頁橫條依總分降序，點教師會篩選摘要與證據；點空白解除。\n"
        "Desktop 編輯模式的導覽按鈕通常需 Ctrl+點擊。\n\n"
        "版型背景直接取自使用者提供 Employee Hiring and History.pbix，兩頁皆為1280×720。"
        "未複製原人資模型、書籤、資料或語意；原始範例及既有報表未覆寫。\n"
        "教師圖只呈現現有快照候選（最多三位），不是所有教授；多課未單選時圖表留白，避免跨課混算。\n"
        "分數是歷史證據強度。模型仍連原本 .\\SQLEXPRESS / EMI_Demo，沒有寫入SQL或發布雲端。\n"
        "此產生器重跑會覆寫本輸出目錄同名定義；Desktop手動微調後請另存工作副本。\n"
        "尚需Desktop驗收：字型、欄寬、重新整理與點選互動。PBIP可由Desktop另存PBIX。\n", encoding="utf-8")
    print(OUT / "EMI.pbip")

if __name__ == "__main__":
    main()
