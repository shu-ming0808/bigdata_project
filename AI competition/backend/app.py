import asyncio
import json
import os
import re
from tempfile import TemporaryDirectory
from pathlib import Path
from decimal import Decimal
from typing import Literal, Protocol

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class Evidence(BaseModel):
    id: str
    term: str
    course: str
    course_code: str = ""
    language: str
    emi: str


    @model_validator(mode="after")
    def read_legacy_code(self):
        if not self.course_code:
            match = re.search(r"(?<!\w)([A-Za-z]+[0-9][A-Za-z0-9_-]*)(?!\w)", self.course)
            if match:
                self.course_code = match.group(1)
        return self


FactKey = Literal["same_course", "english", "formal", "same_formal", "unknown_emi", "all_records"]
FACT_LABELS: dict[FactKey, str] = {
    "same_course": "本課授課紀錄", "english": "英語授課紀錄", "formal": "正式 EMI 紀錄",
    "all_records": "授課紀錄",
    "same_formal": "本課正式 EMI 紀錄", "unknown_emi": "EMI 註記未知的紀錄",
}


class Candidate(BaseModel):
    id: str
    name: str
    scores: dict[str, float]
    evidence: list[Evidence]
    facts: dict[FactKey, list[str]] = Field(default_factory=dict)


class CourseCase(BaseModel):
    course_code: str
    version: str
    candidates: list[Candidate]


class CourseResponse(CourseCase):
    data_source: Literal["actual", "synthetic"]


class CourseRepository(Protocol):
    def get_case(self, code: str) -> CourseCase | None: ...


class JsonCourseRepository:
    def __init__(self, path: Path):
        self.case = CourseCase.model_validate_json(path.read_text(encoding="utf-8"))

        for candidate in self.case.candidates:
            facts = {key: [] for key in FACT_LABELS}
            for e in candidate.evidence:
                facts["all_records"].append(e.id)
                same = e.course_code == self.case.course_code
                if same:
                    facts["same_course"].append(e.id)
                if e.language == "英語":
                    facts["english"].append(e.id)
                if e.emi == "是":
                    facts["formal"].append(e.id)
                    if same:
                        facts["same_formal"].append(e.id)
                elif e.emi.strip() in ("未知", ""):
                    facts["unknown_emi"].append(e.id)
            candidate.facts = facts

    def get_case(self, code: str) -> CourseCase | None:
        return self.case if code == self.case.course_code else None


class Selection(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=3)


class Reason(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    text: str
    evidence_ids: list[str]


class FactChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    fact: FactKey


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reasons: list[FactChoice]


class ScoreComparison(BaseModel):
    first: str
    second: str
    first_total: float
    second_total: float
    gap: float
    differences: dict[str, float]


def compare_scores(first: Candidate, second: Candidate) -> ScoreComparison:
    if first.scores.keys() != second.scores.keys():
        raise ValueError("候選人分項不一致")
    a = {k: Decimal(str(v)) for k, v in first.scores.items()}
    b = {k: Decimal(str(v)) for k, v in second.scores.items()}
    return ScoreComparison(first=first.name, second=second.name,
                           first_total=float(sum(a.values())), second_total=float(sum(b.values())),
                           gap=float(sum(a.values()) - sum(b.values())),
                           differences={k: float(v - b[k]) for k, v in a.items()})


class ExplanationInput(CourseCase):
    comparison: ScoreComparison | None


EXPLANATION_TASK = ("為每位教師選出最能說明其同課、英語、正式 EMI 或未知註記的事實。"
                    "每位至少選一項，僅選 facts 中有證據的鍵，優先呈現候選人間的差異。")


class Explanation(BaseModel):
    comparison: ScoreComparison | None = None
    source: Literal["local", "azure", "codex"]
    reasons: list[Reason]


class ExplanationProvider(Protocol):
    async def explain(self, case: ExplanationInput) -> Explanation: ...


def explain_facts(case: ExplanationInput, draft: Draft, source: Literal["codex", "azure", "local"]) -> Explanation:
    candidates = {c.id: c for c in case.candidates}
    reasons = []
    seen = set()
    for choice in draft.reasons:
        candidate = candidates[choice.candidate_id]
        key = choice.fact
        ids = candidate.facts[key]
        if not ids:
            raise ValueError("選取的事實缺少證據")
        if (candidate.id, key) in seen:
            continue
        seen.add((candidate.id, key))
        reasons.append(Reason(candidate_id=candidate.id, evidence_ids=ids,
                              text=f"{candidate.name}有 {len(ids)} 筆{FACT_LABELS[key]}。"))
    return Explanation(source=source, reasons=reasons)


class LocalProvider:
    async def explain(self, case: ExplanationInput) -> Explanation:
        choices = [FactChoice(candidate_id=c.id, fact=key) for c in case.candidates
                   for key, ids in c.facts.items() if ids and key != "all_records"]
        covered = {choice.candidate_id for choice in choices}
        choices.extend(FactChoice(candidate_id=c.id, fact="all_records") for c in case.candidates
                       if c.id not in covered and c.evidence)
        return explain_facts(case, Draft(reasons=choices), "local")


class CodexProvider:
    async def explain(self, case: ExplanationInput) -> Explanation:
        prompt = EXPLANATION_TASK + "\n" + case.model_dump_json()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            schema = root / "schema.json"
            output = root / "result.json"
            schema.write_text(json.dumps(Draft.model_json_schema()), encoding="utf-8")
            try:
                process = await asyncio.create_subprocess_exec(
                    "codex", "exec", "--ignore-user-config", "--ephemeral", "--sandbox", "read-only",
                    "--skip-git-repo-check", "--output-schema", str(schema),
                    "--output-last-message", str(output), "-", cwd=root,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except FileNotFoundError:
                raise HTTPException(503, "後端找不到 codex，請確認 CLI 已加入 PATH") from None
            try:
                await asyncio.wait_for(process.communicate(prompt.encode()), timeout=90)
            except TimeoutError:
                raise HTTPException(504, "Codex 回應逾時，請稍後重試") from None
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            if process.returncode or not output.is_file():
                raise HTTPException(502, "Codex 執行失敗，請在後端帳號檢查 codex login status 與網路連線")
            draft = Draft.model_validate_json(output.read_bytes())
            return explain_facts(case, draft, "codex")


class AzureProvider:
    def __init__(self):
        self.url = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/") + "/openai/v1/chat/completions"
        self.key = os.environ["AZURE_OPENAI_API_KEY"]
        self.model = os.environ["AZURE_OPENAI_DEPLOYMENT"]

    async def explain(self, case: ExplanationInput) -> Explanation:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": EXPLANATION_TASK},
                {"role": "user", "content": case.model_dump_json()},
            ],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "candidate_explanation", "strict": True, "schema": Draft.model_json_schema(),
            }},
        }
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(self.url, headers={"api-key": self.key}, json=payload)
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return explain_facts(case, Draft.model_validate_json(content), "azure")


def create_app(repo: CourseRepository, provider: ExplanationProvider, actual: CourseRepository | None = None) -> FastAPI:
    app = FastAPI(title="EMI 師資證據助理")

    @app.get("/api/courses/{code}/candidates")
    async def get_case(code: str, synthetic: bool = False) -> CourseResponse:
        repository = repo if synthetic else actual
        if repository is None:
            raise HTTPException(503, "實際資料尚未載入，可改用合成展示案例")
        case = repository.get_case(code)
        if case is None:
            raise HTTPException(404, "找不到課程")
        return CourseResponse(**case.model_dump(), data_source="synthetic" if synthetic else "actual")

    @app.post("/api/courses/{code}/explanation")
    async def explain(code: str, selection: Selection, synthetic: bool = False) -> Explanation:
        case = await get_case(code, synthetic)
        ids = selection.candidate_ids
        selected = [c for c in case.candidates if c.id in ids]
        if len(selected) != len(ids):
            raise HTTPException(422, "候選人重複或不屬於這門課")
        allowed = {c.id: {e.id for e in c.evidence} for c in selected}
        try:
            comparison = compare_scores(*selected) if len(selected) == 2 else None
            payload = ExplanationInput(course_code=case.course_code, version=case.version,
                                       candidates=selected, comparison=comparison)
            engine = provider if synthetic else LocalProvider()
            result = await engine.explain(payload)
            result.comparison = comparison
        except (httpx.HTTPError, ValidationError, ValueError, KeyError, IndexError, TypeError):
            raise HTTPException(502, "無法取得有效說明，仍可查看原始證據") from None
        if ({r.candidate_id for r in result.reasons} != set(ids)
                or any(not r.text.strip() or not r.evidence_ids
                       or not set(r.evidence_ids) <= allowed[r.candidate_id] for r in result.reasons)):
            raise HTTPException(502, "說明缺少候選人或含無效引用")
        return result

    return app


mode = os.getenv("EXPLANATION_MODE", "codex")
providers = {"local": LocalProvider, "azure": AzureProvider, "codex": CodexProvider}
if mode not in providers:
    raise ValueError("EXPLANATION_MODE must be local, azure or codex")
actual_path = Path(__file__).resolve().parents[1] / "outputs/demo/CE2005.json"
app = create_app(JsonCourseRepository(Path(__file__).with_name("case.json")), providers[mode](),
                 JsonCourseRepository(actual_path) if actual_path.is_file() else None)
