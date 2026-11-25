"""Apply an editorial warm-neutral theme to the generated local PBIR report."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"outputs/powerbi"
REPORT=OUT/"EMI.Report"

def read(p):return json.loads(p.read_text(encoding="utf-8"))
def write(p,d):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
def literal(x):return {"expr":{"Literal":{"Value":x}}}
def color(hex):return {"solid":{"color":literal("'"+hex+"'")}}

def main():
    theme={
        "name":"EMI Editorial Warm",
        "dataColors":["#405C58","#A27659","#717B82","#A69A86","#647566","#B2A498"],
        "background":"#F5F2EB","foreground":"#292D2B","tableAccent":"#405C58",
        "textClasses":{"label":{"fontFace":"Microsoft JhengHei","fontSize":12,"color":"#292D2B"},
                       "title":{"fontFace":"Microsoft JhengHei","fontSize":16,"color":"#292D2B"},
                       "header":{"fontFace":"Microsoft JhengHei","fontSize":14,"color":"#405C58"}},
        "visualStyles":{
            "*":{"*":{
                "title":[{"show":True,"fontFamily":"Microsoft JhengHei","fontSize":14,
                          "fontColor":{"solid":{"color":"#292D2B"}}}],
                "background":[{"color":{"solid":{"color":"#FCFAF6"}},"transparency":0}],
                "border":[{"show":False}],
                "dropShadow":[{"show":False}]}},
            "tableEx":{"*":{
                "grid":[{"gridVertical":False,"gridHorizontal":True,"rowPadding":8,
                         "gridHorizontalColor":{"solid":{"color":"#E4DFD5"}}}],
                "columnHeaders":[{"fontFamily":"Microsoft JhengHei","fontSize":12,
                                  "fontColor":{"solid":{"color":"#405C58"}},
                                  "backColor":{"solid":{"color":"#ECE9E0"}}}],
                "values":[{"fontFamily":"Microsoft JhengHei","fontSize":12,
                           "fontColorPrimary":{"solid":{"color":"#292D2B"}},
                           "backColorPrimary":{"solid":{"color":"#FCFAF6"}},
                           "backColorSecondary":{"solid":{"color":"#F5F2EB"}},
                           "wordWrap":True}],
                "total":[{"totals":False}]}}}}
    write(OUT/"文青暖白主題.json",theme)
    write(REPORT/"StaticResources/RegisteredResources/EMIEditorial.json",theme)
    rp=REPORT/"definition/report.json"
    r=read(rp)
    r["themeCollection"]={"customTheme":{"name":"EMIEditorial",
        "reportVersionAtImport":{"visual":"2.1.0","page":"2.0.0","report":"3.0.0"},
        "type":"RegisteredResources"}}
    r["resourcePackages"]=[{"name":"RegisteredResources","type":"RegisteredResources",
        "items":[{"name":"EMIEditorial","path":"EMIEditorial.json","type":"CustomTheme"}]}]
    write(rp,r)
    page=REPORT/"definition/pages/Recommendation"
    p=read(page/"page.json")
    p["objects"]={"background":[{"properties":{"color":color("#F5F2EB"),"transparency":literal("0D")}}]}
    write(page/"page.json",p)
    layouts={
        "CourseSelector":([28,24,310,150],"01  選擇課程"),
        "Coverage":([366,24,1206,150],"EMI 師資證據助理｜真實開課紀錄・候選覆蓋"),
        "Ranking":([28,198,1544,252],"02  候選比較｜依歷史證據分數排序"),
        "Reasons":([28,474,1544,238],"03  推薦說明與待核對事項"),
        "Evidence":([28,736,1544,336],"04  授課證據｜選取候選教師後查看明細")}
    for name,(rect,title) in layouts.items():
        path=page/f"visuals/{name}/visual.json"
        v=read(path)
        v["position"].update(dict(zip(["x","y","width","height"],rect)))
        objects=v["visual"].setdefault("objects",{})
        if name!="CourseSelector":
            objects["columnHeaders"]=[{"properties":{"fontColor":color("#405C58"),
                "backColor":color("#ECE9E0"),"fontSize":literal("12D")}}]
            objects["values"]=[{"properties":{"fontColorPrimary":color("#292D2B"),
                "fontColorSecondary":color("#292D2B"),"backColorPrimary":color("#FCFAF6"),
                "backColorSecondary":color("#F5F2EB"),"fontSize":literal("12D"),"wordWrap":literal("true")}}]
        else:
            objects["items"]=[{"properties":{"fontColor":color("#292D2B"),
                "background":color("#FCFAF6"),"textSize":literal("14D")}}]
        props=v["visual"].setdefault("visualContainerObjects",{})
        props["title"]=[{"properties":{"show":literal("true"),"text":literal("'"+title+"'"),
            "fontSize":literal("14D"),"fontColor":color("#292D2B"),"titleWrap":literal("true")}}]
        props["background"]=[{"properties":{"color":color("#FCFAF6"),"transparency":literal("0D")}}]
        write(path,v)
    print("Editorial theme and four workflow panels applied; SQL model unchanged.")

if __name__=="__main__":main()
