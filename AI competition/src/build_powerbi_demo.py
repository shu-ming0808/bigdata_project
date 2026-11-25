"""Build a local-only Power BI project from real candidate snapshots.

No cloud publishing, database writes or model calls. Run again to refresh exports.
"""
import csv
import json
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/powerbi"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def build():
    courses, candidates, evidence = [], [], []
    for p in sorted((ROOT/"outputs/demo").glob("*.json")):
        case = json.loads(p.read_text(encoding="utf-8"))
        if case["version"].startswith("synthetic"):
            continue
        code = case["course_code"]
        ordered = sorted(case["candidates"], key=lambda c: -sum(c["scores"].values()))
        courses.append({"CourseCode":code, "CandidateCount":len(ordered),
                        "Coverage":"候選足三人" if len(ordered)>=3 else "證據不足三人"})
        for rank, c in enumerate(ordered,1):
            if rank>3:
                raise ValueError("Snapshot contains more than three candidates")
            key=code+"|"+c["id"]
            ev=c["evidence"]
            same=[e for e in ev if e["course_code"]==code]
            english=[e for e in ev if e["language"]=="英語"]
            formal=[e for e in ev if e["emi"]=="是"]
            summary=(f"本課 {len(same)} 筆；英語授課 {len(english)} 筆；"
                     f"正式 EMI {len(formal)} 筆。依歷史證據排序，非教學品質評分。")
            row={"CandidateKey":key,"CourseCode":code,"Rank":rank,"Teacher":c["name"],
                 "TotalScore":round(sum(c["scores"].values()),2),
                 "SameCourseScore":c["scores"]["同課經驗"],"EMIScore":c["scores"]["正式 EMI"],
                 "EnglishScore":c["scores"]["英語授課"],"RelatedScore":c["scores"]["相關課程"],
                 "RecencyScore":c["scores"]["新近性"],"Summary":summary,
                 "Review":"教師人事ID、當期聘任、意願、負荷及時段均待核對；來源姓名尚未核對同名。"}
            candidates.append(row)
            seen=set()
            for e in ev:
                if e["id"] in seen:
                    raise ValueError("Repeated evidence within candidate")
                seen.add(e["id"])
                evidence.append({"CandidateKey":key,"EvidenceID":e["id"],"Term":e["term"],
                    "CourseCode":e["course_code"],"Course":e["course"],"Language":e["language"],
                    "FormalEMI":e["emi"],"Teacher":c["name"]})
    if not courses:
        raise ValueError("Build real outputs/demo snapshots first")
    data=OUT/"data"
    data.mkdir(parents=True,exist_ok=True)
    tables={"Courses":courses,"Candidates":candidates,"Evidence":evidence}
    types={}
    for name, rows in tables.items():
        cols=list(rows[0])
        types[name]={col:("int64" if isinstance(rows[0][col],int) else
                         "double" if isinstance(rows[0][col],float) else "string") for col in cols}
        with (data/f"{name}.csv").open("w",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=cols)
            w.writeheader();w.writerows(rows)
    semantic=OUT/"EMI.SemanticModel"
    report=OUT/"EMI.Report"
    write_json(OUT/"EMI.pbip",{"version":"1.0","artifacts":[{"report":{"path":"EMI.Report"}}],
               "settings":{"enableAutoRecovery":True}})
    write_json(semantic/"definition.pbism",{"version":"1.0","settings":{}})
    model_tables=[]
    for name, rows in tables.items():
        type_map={"string":"type text","int64":"Int64.Type","double":"type number"}
        transforms=", ".join('{"'+col+'", '+type_map[t]+'}' for col,t in types[name].items())
        expr=["let",f'    Source = Csv.Document(File.Contents("{(data/(name+".csv")).as_posix()}"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
              '    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),',
              "    Typed = Table.TransformColumnTypes(Headers, {"+transforms+"})","in","    Typed"]
        model_tables.append({"name":name,"columns":[{"name":col,"dataType":t,"sourceColumn":col,
             "summarizeBy":"none"} for col,t in types[name].items()],
             "partitions":[{"name":name,"mode":"import","source":{"type":"m","expression":expr}}]})
    model={"compatibilityLevel":1567,"model":{"culture":"zh-TW","defaultPowerBIDataSourceVersion":"powerBI_V3",
        "tables":model_tables,"relationships":[
            {"name":str(uuid.uuid4()),"fromTable":"Candidates","fromColumn":"CourseCode",
             "toTable":"Courses","toColumn":"CourseCode","crossFilteringBehavior":"oneDirection"},
            {"name":str(uuid.uuid4()),"fromTable":"Evidence","fromColumn":"CandidateKey",
             "toTable":"Candidates","toColumn":"CandidateKey","crossFilteringBehavior":"oneDirection"}]}}
    write_json(semantic/"model.bim",model)
    write_json(report/"definition.pbir",{"version":"4.0","datasetReference":{"byPath":{"path":"../EMI.SemanticModel"}}})
    definition=report/"definition"
    write_json(definition/"version.json",{"$schema":SCHEMA+"report/definition/versionMetadata/1.0.0/schema.json",
        "version":"2.0.0"})
    write_json(definition/"report.json",{"$schema":SCHEMA+"report/definition/report/3.0.0/schema.json","themeCollection":{}})
    write_json(definition/"pages/pages.json",{"$schema":SCHEMA+"report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder":["Recommendation"],"activePageName":"Recommendation"})
    page=definition/"pages/Recommendation"
    write_json(page/"page.json",{"$schema":SCHEMA+"report/definition/page/2.0.0/schema.json","name":"Recommendation",
        "displayName":"EMI 師資推薦與證據","displayOption":"FitToPage","width":1600,"height":1100})
    def field(table,col):
        return {"Column":{"Expression":{"SourceRef":{"Entity":table}},"Property":col}}
    def visual(name,kind,table,cols,pos,title,sort=None):
        projections=[{"field":field(table,col),"queryRef":table+"."+col,"displayName":label}
                     for col,label in cols]
        role="Values" if kind=="tableEx" else "Values"
        query={"queryState":{role:{"projections":projections}}}
        if sort:
            query["sortDefinition"]={"sort":[{"field":field(table,sort),"direction":"Ascending"}]}
        write_json(page/f"visuals/{name}/visual.json",{
            "$schema":SCHEMA+"report/definition/visualContainer/2.1.0/schema.json",
            "name":name,"position":dict(zip(["x","y","width","height"],pos),z=0,tabOrder=len(list(page.glob("visuals/*")))),
            "visual":{"visualType":kind,"query":query,
                "visualContainerObjects":{"title":[{"properties":{"show":{"expr":{"Literal":{"Value":"true"}}},
                 "text":{"expr":{"Literal":{"Value":"'"+title+"'"}}}}}]}}})
    visual("CourseSelector","slicer","Courses",[("CourseCode","課程")],[20,20,340,130],"① 選擇課程（請選一門）")
    visual("Coverage","tableEx","Courses",[("CourseCode","課號"),("CandidateCount","候選人數"),("Coverage","覆蓋狀態")],
           [390,20,1190,130],"真實開課紀錄 1051–1151｜本機規則摘要，非即時 AI")
    visual("Ranking","tableEx","Candidates",[("Rank","排名"),("Teacher","教師"),("TotalScore","證據總分"),
        ("SameCourseScore","同課"),("EMIScore","正式EMI"),("EnglishScore","英語"),
        ("RelatedScore","相關課"),("RecencyScore","新近性")],
        [20,170,1560,250],"② 候選排序｜點選教師後，下方證據與說明連動；分數非適任機率","Rank")
    visual("Reasons","tableEx","Candidates",[("Teacher","教師"),("Summary","紀錄摘要"),("Review","待人工核對")],
           [20,440,1560,220],"③ 推薦說明與行政限制（本機依事實產生）")
    visual("Evidence","tableEx","Evidence",[("Teacher","教師"),("EvidenceID","證據ID"),("Term","學期"),
           ("Course","授課課程"),("Language","授課語言"),("FormalEMI","正式EMI")],
           [20,680,1560,390],"④ 授課證據｜班次可重複支持不同目標課候選；勿當獨立開課數","Term")
    audit={"courses":len(courses),"candidates":len(candidates),"evidence_links":len(evidence),
           "insufficient_courses":sum(c["CandidateCount"]<3 for c in courses),
           "semantic_relationships":2,"desktop_open_verified":False,
           "note":"Imported local snapshots; names sensitive. No publish. Report JSON/schema checks do not prove Desktop render."}
    write_json(OUT/"build_audit.json",audit)
    (OUT/"開啟與展示.md").write_text(
        "# Power BI 本機展示\n\n需要 Power BI Desktop，閱讀版 Power BI App 不能編輯此專案。"
        "\n\n1. 用新版 Desktop 開啟 EMI.pbip（必要時啟用 Power BI Projects / PBIR 預覽）。"
        "\n2. 按重新整理，載入此目錄 data/ 的三份本機 CSV；本機路徑已寫入模型。"
        "\n3. 選 CE2005 → 看候選排名 → 點教師列 → 看摘要及授課證據。"
        "\n4. 選 CE1003 可展示不足三人；選多門會列出各門的前三名，不是跨課總排名。"
        "\n\n若移動專案，重跑 src/build_powerbi_demo.py 以更新資料路徑。"
        "\n\n此為真實來源姓名與證據，保留於 outputs/ 並被 Git 排除，未發布雲端。"
        "\n\n目前尚未在 Desktop 開啟驗證：篩選互動、字型、欄寬與截斷需在 Desktop 確認，"
        "如需調整，候選表對摘要與證據表的互動應設為篩選。不要將檔案視為已驗收 PBIX。\n",
        encoding="utf-8")
    print(json.dumps(audit,ensure_ascii=False))

if __name__=="__main__":
    build()
