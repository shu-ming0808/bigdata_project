"""Load generated report tables into a dedicated local SQL Server database.

Windows authentication; replaces only the owned pbi schema in EMI_Demo in one transaction.
SQL containing source names is generated under ignored outputs, never committed.
"""
import csv
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"outputs/powerbi"
SERVER=r".\SQLEXPRESS"
DB="EMI_Demo"

def execute(path, db="master"):
    subprocess.run(["sqlcmd","-S",SERVER,"-E","-C","-b","-l","15",
        "-d",db,"-f","65001","-i",str(path)],check=True)

def main():
    tables={}
    for name in ("Courses","Candidates","Evidence"):
        with (OUT/f"data/{name}.csv").open(encoding="utf-8-sig") as f:
            tables[name]=list(csv.DictReader(f))
    init=OUT/"create_database.sql"
    init.write_text("IF DB_ID(N'EMI_Demo') IS NULL CREATE DATABASE [EMI_Demo];\n",encoding="utf-8-sig")
    execute(init)
    parts=["SET XACT_ABORT ON; BEGIN TRANSACTION;",
        "IF SCHEMA_ID(N'pbi') IS NULL EXEC(N'CREATE SCHEMA pbi');",
        "IF OBJECT_ID(N'pbi.Evidence',N'U') IS NOT NULL DROP TABLE pbi.Evidence;",
        "IF OBJECT_ID(N'pbi.Candidates',N'U') IS NOT NULL DROP TABLE pbi.Candidates;",
        "IF OBJECT_ID(N'pbi.Courses',N'U') IS NOT NULL DROP TABLE pbi.Courses;"]
    numeric={"CandidateCount":"int","Rank":"int","TotalScore":"decimal(10,2)",
             "SameCourseScore":"decimal(10,2)","EMIScore":"decimal(10,2)",
             "EnglishScore":"decimal(10,2)","RelatedScore":"decimal(10,2)","RecencyScore":"decimal(10,2)"}
    for name,rows in tables.items():
        cols=list(rows[0])
        defs=[f"[{c}] {numeric.get(c,'nvarchar(1000)' if c in ('Summary','Review','Course') else 'nvarchar(200)')} NOT NULL" for c in cols]
        pk={"Courses":"CourseCode","Candidates":"CandidateKey","Evidence":None}[name]
        if pk:defs.append(f"CONSTRAINT [PK_{name}] PRIMARY KEY ([{pk}])")
        if name=="Evidence":defs.append("CONSTRAINT PK_Evidence PRIMARY KEY (CandidateKey,EvidenceID)")
        parts.append(f"CREATE TABLE pbi.[{name}] ("+",".join(defs)+");")
        for i in range(0,len(rows),200):
            values=[]
            for row in rows[i:i+200]:
                values.append("("+",".join(row[c] if c in numeric else "N'"+row[c].replace("'","''")+"'" for c in cols)+")")
            parts.append(f"INSERT INTO pbi.[{name}] ("+",".join("["+c+"]" for c in cols)+") VALUES "+",".join(values)+";")
    parts.extend([
        "ALTER TABLE pbi.Candidates ADD CONSTRAINT FK_CandidateCourse FOREIGN KEY(CourseCode) REFERENCES pbi.Courses(CourseCode);",
        "ALTER TABLE pbi.Evidence ADD CONSTRAINT FK_EvidenceCandidate FOREIGN KEY(CandidateKey) REFERENCES pbi.Candidates(CandidateKey);",
        "COMMIT; SELECT 'Courses' TableName,COUNT(*) [RowCount] FROM pbi.Courses UNION ALL SELECT 'Candidates',COUNT(*) FROM pbi.Candidates UNION ALL SELECT 'Evidence',COUNT(*) FROM pbi.Evidence;"])
    script=OUT/"load_demo.sql"
    script.write_text("\n".join(parts),encoding="utf-8-sig")
    execute(script,DB)
    model_path=OUT/"EMI.SemanticModel/model.bim"
    model=json.loads(model_path.read_text(encoding="utf-8"))
    for table in model["model"]["tables"]:
        name=table["name"]
        table["partitions"][0]["source"]["expression"]=[
            "let",f'    Source = Sql.Database("{SERVER}", "{DB}"),',
            f'    Data = Source{{[Schema="pbi", Item="{name}"]}}[Data]',"in","    Data"]
    model_path.write_text(json.dumps(model,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"SSMS_檢查.sql").write_text(
        "USE EMI_Demo;\nSELECT * FROM pbi.Courses;\n"
        "SELECT * FROM pbi.Candidates WHERE CourseCode=N'CE2005' ORDER BY Rank;\n"
        "SELECT e.* FROM pbi.Evidence e JOIN pbi.Candidates c ON e.CandidateKey=c.CandidateKey "
        "WHERE c.CourseCode=N'CE2005' ORDER BY c.Rank,e.Term DESC;\n",encoding="utf-8-sig")
    print("Power BI model now imports SQL Server .\\SQLEXPRESS / EMI_Demo / pbi schema.")

if __name__=="__main__":main()
