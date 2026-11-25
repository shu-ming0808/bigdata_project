"""Mask local generated display exports without rebuilding manually edited reports."""
import csv
import json
from pathlib import Path
from powerbi_privacy import mask_teacher_name

ROOT=Path(__file__).resolve().parents[1]
REPORT_DIRS=["powerbi","powerbi_two_pages","powerbi_hiring_style"]

def main():
    mapping={}
    for p in (ROOT/"outputs/demo").glob("*.json"):
        case=json.loads(p.read_text(encoding="utf-8"))
        if str(case.get("version","")).startswith("synthetic"):
            continue
        for c in case.get("candidates",[]):
            raw=c.get("name","").strip()
            if raw:
                mapping[raw]=mask_teacher_name(raw)
    data=ROOT/"outputs/powerbi/data"
    count=0
    collisions=0
    for table in ["Candidates","Evidence"]:
        p=data/f"{table}.csv"
        with p.open(encoding="utf-8-sig",newline="") as f:
            reader=csv.DictReader(f)
            cols=reader.fieldnames
            rows=list(reader)
        seen={}
        for row in rows:
            name=row.get("Teacher","")
            row["Teacher"]=mask_teacher_name(name)
            count+=1
            if table=="Candidates":
                k=(row["CourseCode"],row["Teacher"])
                if k in seen and seen[k]!=row["CandidateKey"]:
                    collisions+=1
                seen[k]=row["CandidateKey"]
        if collisions:
            raise ValueError("Masked-name collision within course; use candidate-key labels before migration")
        with p.open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(rows)
    scrubbed=0
    caches=0
    for name in REPORT_DIRS:
        folder=(ROOT/"outputs"/name).resolve()
        assert folder.is_relative_to((ROOT/"outputs").resolve())
        for p in folder.rglob("*"):
            if not p.is_file():
                continue
            if p.name=="cache.abf" and p.parent.name==".pbi":
                # Invalidate imported unmasked data. Desktop reimports from masked SQL.
                p.unlink()
                caches+=1
                continue
            if p.suffix.lower() not in [".json",".tmdl",".md",".sql"]:
                continue
            original=p.read_text(encoding="utf-8-sig")
            masked=original
            for raw,replacement in sorted(mapping.items(),key=lambda x:-len(x[0])):
                masked=masked.replace(raw,replacement)
            if masked!=original:
                p.write_text(masked,encoding="utf-8")
                scrubbed+=1
    print(json.dumps({"masked_export_rows":count,"masked_name_collisions":collisions,
        "scrubbed_local_text_files":scrubbed,"invalidated_import_caches":caches}))

if __name__=="__main__":
    main()
