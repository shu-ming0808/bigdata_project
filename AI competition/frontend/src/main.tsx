import ResearchContext from "./ResearchContext";
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Evidence = { id: string; term: string; course: string; language: string; emi: string };
type Candidate = { id: string; name: string; facts: Record<FactKey, string[]>; scores: Record<string, number>; evidence: Evidence[] };
type Course = { data_source: "actual" | "synthetic"; version: string; course_code: string; candidates: Candidate[] };
type Comparison = { first: string; second: string; first_total: number; second_total: number; gap: number; differences: Record<string, number> };
type Result = { comparison: Comparison | null; source: "local" | "azure" | "codex"; reasons: { candidate_id: string; text: string; evidence_ids: string[] }[] };

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(typeof error?.detail === "string" ? error.detail : "請確認 API 服務已啟動，再試一次。");
  }
  return response.json();
}

function ScoreBreakdown({ comparison: c }: { comparison: Comparison }) {
  return <details><summary>歷史分數如何計算</summary>
    <p>{c.first} {c.first_total.toFixed(2)} 分，{c.second} {c.second_total.toFixed(2)} 分。</p>
    <p>各分項相加得到總分。以下採「{c.first} 減 {c.second}」計算，總分差為 {c.gap.toFixed(2)} 分。</p>
    <ul>{Object.entries(c.differences).map(([label, delta]) =>
      <li key={label}>{label} {delta > 0 ? "+" : ""}{delta.toFixed(2)}</li>)}</ul>
  </details>;
}

function EvidenceCount({ records, label }: { records: Evidence[]; label: string }) {
  if (!records.length) return <span>0 筆</span>;
  return <details><summary aria-label={`${label}，${records.length} 筆`}>{records.length} 筆</summary>
    {records.map(e => <p key={e.id}>{e.id} · {e.term} · {e.course} · 授課語言 {e.language} · 正式 EMI {e.emi}</p>)}
  </details>;
}

const evidenceCriteria = [
  ["same_course", "本課授課紀錄"], ["english", "英語授課（所有課程）"],
  ["formal", "正式 EMI（所有課程）"], ["same_formal", "本課正式 EMI"],
  ["unknown_emi", "EMI 註記未知"],
] as const;
type FactKey = typeof evidenceCriteria[number][0];

function App() {
  const [code, setCode] = useState("CE2005");
  const [course, setCourse] = useState<Course | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [result, setResult] = useState<Result | null>(null);
  useEffect(() => {
    if (result) document.getElementById("result-heading")?.focus();
  }, [result]);
  const [citation, setCitation] = useState<{ evidence: Evidence; teacher: string; trigger: HTMLButtonElement } | null>(null);
  useEffect(() => { if (citation) document.getElementById("citation-heading")?.focus(); }, [citation]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [synthetic, setSynthetic] = useState(true);
  async function load(value: string, sample = synthetic) {
    setBusy(true);
    setError("");
    setCitation(null);
    setResult(null);
    setCourse(null);
    try {
      const data = await request<Course>("/api/courses/" + encodeURIComponent(value.trim().toUpperCase()) + "/candidates?synthetic=" + sample);
      setCourse(data);
      setSelected(data.candidates.slice(0, 2).map(c => c.id));
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  useEffect(() => { void load("CE2005"); }, []);

  function openDemo() {
    setCode("CE2005");
    setSynthetic(true);
    void load("CE2005", true);
  }

  async function explain() {
    if (!course) return;
    setBusy(true);
    setError("");
    setCitation(null);
    setResult(null);
    try {
      setResult(await request<Result>("/api/courses/" + encodeURIComponent(course.course_code) + "/explanation?synthetic=" + synthetic, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidate_ids: selected }),
      }));
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }

  return <main><h1>EMI 師資證據助理</h1>
    <div className="toolbar">
    <form onSubmit={e => { e.preventDefault(); void load(code); }}>
      <label>課號 <input required value={code} onChange={e => setCode(e.target.value)} /></label>
      <button disabled={busy || !code.trim()}>查詢</button>
    </form>

    <label><input type="checkbox" disabled={busy} checked={synthetic} onChange={e => {
      setSynthetic(e.target.checked);
      void load(code, e.target.checked);
    }} /> 使用合成展示案例</label>
    </div>
    {course && <p className="metadata">{course.data_source === "actual"
      ? "實際資料 · 115-0012 開課紀錄（1051–1151）。教師以代碼呈現，摘要在本機產生。"
      : "合成展示案例 · 教師、授課證據與分數為示例。"} 聘任資格、意願、負荷與時段均待人工核對。</p>}
    {error && <p role="alert">{error} {!course && <button onClick={openDemo}>開啟 CE2005 合成案例</button>}</p>}
    {busy && <p role="status">{course ? "正在整理所選教師的摘要與引用…" : "正在讀取候選人的授課紀錄…"}</p>}
    {course && <section><h2>{course.course_code} 候選人</h2>
      {synthetic && course.course_code === "CE2005" && <p className="metadata">若要將這門必修改為英語授課，哪位教師教過同一門課？哪位有正式 EMI 紀錄？</p>}
      {course.candidates.length ? <table className="comparison">
        <thead><tr><th scope="col">比較項目</th>{course.candidates.map(c =>
          <th key={c.id} scope="col"><label><input type="checkbox" disabled={busy} checked={selected.includes(c.id)} onChange={e => {
            setCitation(null);
            setResult(null);
            setSelected(e.target.checked ? [...selected, c.id] : selected.filter(id => id !== c.id));
          }} /> {c.name}</label></th>)}</tr></thead>
        <tbody>{evidenceCriteria.map(([key, label]) =>
          <tr key={label}><th scope="row">{label}</th>{course.candidates.map(c =>
            <td key={c.id}><EvidenceCount label={c.name + " " + label}
              records={c.evidence.filter(e => c.facts[key].includes(e.id))} /></td>)}</tr>)}
          <tr><th scope="row">歷史證據分數</th>{course.candidates.map(c => <td key={c.id}>
            {Object.values(c.scores).reduce((a,b) => a+b, 0).toFixed(2)} / 100
            <details><summary>分項得分</summary><ul>{Object.entries(c.scores).map(([k,v]) => <li key={k}>{k} {v}</li>)}</ul></details>
          </td>)}</tr>
          <tr><th scope="row">全部授課紀錄</th>{course.candidates.map(c =>
            <td key={c.id}><EvidenceCount label={c.name + " 全部授課紀錄"} records={c.evidence} /></td>)}</tr>
        </tbody>
      </table> : <p>此課號目前沒有候選紀錄。 <button onClick={openDemo}>開啟 CE2005 合成案例</button></p>}
      <span className="selection">{selected.length ? `已選 ${selected.length} 位` : "勾選教師即可產生摘要"}</span>
      <button disabled={busy || !selected.length} onClick={explain}>{selected.length >= 2 ? "比較授課經驗" : "說明所選候選人的經驗"}</button>
    </section>}
    {result && <section aria-labelledby="result-heading"><h2 id="result-heading" tabIndex={-1}>授課經驗摘要</h2>
      <p className="metadata">{({codex: "Codex CLI 說明", azure: "Azure AI 說明", local: "本機規則摘要"})[result.source]}</p>
      <div className="review"><ul>{result.reasons.map((r,i) => <li key={i}>{r.text} {r.evidence_ids.map(id =>
        <button key={id} onClick={event => {
          const candidate = course?.candidates.find(c => c.id === r.candidate_id);
          const evidence = candidate?.evidence.find(e => e.id === id);
          if (candidate && evidence) setCitation({ evidence, teacher: candidate.name, trigger: event.currentTarget });
        }}>查看授課紀錄 {id}</button>)}</li>)}</ul>
      {citation && <aside><h3 id="citation-heading" tabIndex={-1}>授課紀錄 {citation.evidence.id} · {citation.teacher}</h3>
        <p>{citation.evidence.term} · {citation.evidence.course}</p>
        <p>授課語言 {citation.evidence.language} · 正式 EMI {citation.evidence.emi}</p>
        <button onClick={() => { citation.trigger.focus(); setCitation(null); }}>收合紀錄</button>
      </aside>}</div>
      {result.comparison && <ScoreBreakdown comparison={result.comparison} />}
      <p>安排授課前，仍需確認聘任資格、教師意願、授課負荷與時段。</p>
    </section>}
    <details className="research"><summary>開課規劃與研究背景</summary><ResearchContext /></details>
  </main>;
}
createRoot(document.getElementById("root")!).render(<App />);
