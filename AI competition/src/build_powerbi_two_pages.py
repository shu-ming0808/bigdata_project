"""Two-page Power BI flow, preserving the SQL model from the local project."""
import copy
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"outputs/powerbi"
OUT=ROOT/"outputs/powerbi_two_pages"
SCHEMA="https://developer.microsoft.com/json-schemas/fabric/item/"

def load(path):return json.loads(path.read_text(encoding="utf-8"))
def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
def lit(s):return {"expr":{"Literal":{"Value":s}}}
def col(c):return {"solid":{"color":lit("'"+c+"'")}}

def main():
    semantic=OUT/"EMI.SemanticModel"
    semantic.mkdir(parents=True,exist_ok=True)
    for name in ("definition.pbism","model.bim"):
        shutil.copy2(SOURCE/"EMI.SemanticModel"/name,semantic/name)
    model=load(semantic/"model.bim")
    assert all("Sql.Database" in "\n".join(t["partitions"][0]["source"]["expression"])
               for t in model["model"]["tables"]), "Run load_powerbi_sqlserver.py first"
    report=OUT/"EMI.Report"
    save(OUT/"EMI.pbip",{"version":"1.0","artifacts":[{"report":{"path":"EMI.Report"}}],
                      "settings":{"enableAutoRecovery":True}})
    save(report/"definition.pbir",{"$schema":SCHEMA+"report/definitionProperties/2.0.0/schema.json",
        "version":"4.0","datasetReference":{"byPath":{"path":"../EMI.SemanticModel"}}})
    shutil.copytree(SOURCE/"EMI.Report/StaticResources",report/"StaticResources",dirs_exist_ok=True)
    definition=report/"definition"
    for name in ("report.json","version.json"):
        save(definition/name,load(SOURCE/"EMI.Report/definition"/name))
    save(definition/"pages/pages.json",{"$schema":SCHEMA+"report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder":["CourseSelection","CandidateDetail"],"activePageName":"CourseSelection"})
    original=SOURCE/"EMI.Report/definition/pages/Recommendation"
    base=load(original/"page.json")
    for name,label in (("CourseSelection","01 選擇課程"),("CandidateDetail","02 教師推薦與證據")):
        page=copy.deepcopy(base)
        page.update(name=name,displayName=label,width=1600,height=1100)
        save(definition/f"pages/{name}/page.json",page)
    def copy_visual(source,name,page,pos,title=None):
        v=load(original/f"visuals/{source}/visual.json")
        v["name"]=name
        v["position"].update(dict(zip(["x","y","width","height"],pos)))
        if title:
            v["visual"]["visualContainerObjects"]["title"][0]["properties"]["text"]=lit("'"+title+"'")
        save(definition/f"pages/{page}/visuals/{name}/visual.json",v)
        return v
    for page in ("CourseSelection","CandidateDetail"):
        v=copy_visual("CourseSelector","SelectCourse"+page,page,[32,32,430,190],
                      "選擇一門課程｜跨頁保留選取")
        v["visual"]["syncGroup"]={"groupName":"EMICourseSelection","fieldChanges":True,"filterChanges":True}
        v["visual"].setdefault("objects",{})["selection"]=[{"properties":{
            "singleSelect":lit("true"),"selectAllCheckboxEnabled":lit("false")}}]
        save(definition/f"pages/{page}/visuals/SelectCourse{page}/visual.json",v)
    copy_visual("Coverage","Overview","CourseSelection",[32,252,1536,700],
                "課程與候選覆蓋｜請用左上課程篩選器選課，再按查看推薦")
    copy_visual("Coverage","CurrentCourse","CandidateDetail",[490,32,760,190],"目前課程與候選人數")
    copy_visual("Ranking","RankDetail","CandidateDetail",[32,248,1536,240],"候選排序｜點選教師列以篩選下方說明及證據")
    copy_visual("Reasons","ReasonDetail","CandidateDetail",[32,512,1536,200],"推薦說明與待核對事項")
    copy_visual("Evidence","EvidenceDetail","CandidateDetail",[32,736,1536,332],"授課證據｜姓名、課程、學期與語言")
    def button(page,name,dest,text,pos):
        save(definition/f"pages/{page}/visuals/{name}/visual.json",{
            "$schema":SCHEMA+"report/definition/visualContainer/2.1.0/schema.json",
            "name":name,"position":dict(zip(["x","y","width","height"],pos),z=10,tabOrder=10),
            "visual":{"visualType":"actionButton","objects":{
                "text":[{"properties":{"show":lit("true")}},
                        {"selector":{"id":"default"},"properties":{"text":lit("'"+text+"'"),
                          "fontColor":col("#FFFFFF"),"fontSize":lit("17D"),
                          "horizontalAlignment":lit("'center'"),"verticalAlignment":lit("'middle'")}}],
                "fill":[{"properties":{"show":lit("true")}},
                        {"selector":{"id":"default"},"properties":{"fillColor":col("#405C58"),"transparency":lit("0D")}}]},
                "visualContainerObjects":{"visualLink":[{"properties":{"show":lit("true"),
                    "type":lit("'PageNavigation'"),"navigationSection":lit("'"+dest+"'")}}],
                    "title":[{"properties":{"show":lit("false")}}]}}})
    button("CourseSelection","OpenRecommendation","CandidateDetail","查看推薦 →",[500,65,320,90])
    button("CandidateDetail","ReturnCourses","CourseSelection","← 返回選課",[1280,65,288,90])
    # Explicit filter interactions prevent ambiguous cross-highlighting of text tables.
    pp=definition/"pages/CandidateDetail/page.json"
    p=load(pp)
    p["visualInteractions"]=[{"source":"RankDetail","target":target,"type":"DataFilter"}
                             for target in ("ReasonDetail","EvidenceDetail")]
    save(pp,p)
    (OUT/"操作說明.md").write_text(
        "# 兩頁式推薦報表\n\n1. Power BI Desktop 開啟 EMI.pbip 並重新整理 SQL Server 資料。\n"
        "2. 第一頁用左上篩選器選單一課程。下方是課程覆蓋清單，點清單列不等於同步篩選器。\n"
        "3. 按「查看推薦」進第二頁，課程由同步篩選器保留。\n"
        "4. 第二頁查看前三名、分項、說明與證據；按返回可重新選課。\n"
        "5. Desktop 編輯模式下，導覽按鈕通常須 Ctrl＋點擊；閱讀模式一般點擊。\n\n"
        "這是兩個報表頁，不是兩份獨立報表。未實測 Desktop 互動；原先資料載入問題未因此自動解決。"
        "模型連線仍為 .\\SQLEXPRESS / EMI_Demo，Import 模式需完成 Windows 驗證與重新整理。\n",
        encoding="utf-8")
    print("Two-page project:",OUT/"EMI.pbip")

if __name__=="__main__":main()
