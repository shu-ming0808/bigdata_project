// Source: Big Data Analytics Program/專題_修業階段供給與首次修讀.md §3.1.
// Counts refer to at-risk student terms, not distinct students.
const stages = [
  { year: "一年級", terms: 3122, first: 7, zeroSupply: "100.00%" },
  { year: "二年級", terms: 3165, first: 621, zeroSupply: "73.87%" },
];

export default function ResearchContext() {
  return <section aria-labelledby="planning">
    <h2 id="planning">開課規劃：資電學院何時開始修讀英語專業課？</h2>
    <p>校務研究彙總 · 1051–1151 學期。資訊電機學院推定一年級的 3,122 個風險學生學期中，有 7 次首次修讀；到了推定二年級，首次修讀率升至 19.62%。規劃必修課轉為英語授課時，可先核對這兩個階段的課程配置。</p>
    <details><summary>查看分母、供給與研究來源</summary>
      <table><caption>資訊電機學院，排除首八學期曾屬英美語文學系者</caption>
        <thead><tr>{["推定年級", "風險學生學期", "首次修讀", "首次修讀率", "同院同階段零供給比例"].map(h => <th key={h} scope="col">{h}</th>)}</tr></thead>
        <tbody>{stages.map(s => <tr key={s.year}><th scope="row">{s.year}</th><td>{s.terms.toLocaleString("en-US")}</td><td>{s.first}</td><td>{(100*s.first/s.terms).toFixed(2)}%</td><td>{s.zeroSupply}</td></tr>)}</tbody>
      </table>
      <p>主樣本有 9,086 位首八學期連續可見的大學部學生。每人在首次修讀前及當期都計入風險集。推定年級依可見學期排序；供給只計同學院開設、課號層級不高於推定年級的學士班英語專業課。</p>
      <p>學生也可跨院修課。全樣本 6,799 位首次修讀者中，有 1,402 人當期的同院同階段供給為零。班次數無法反映個人資格或剩餘名額，這些觀察也無法預測 CE2005 改制後的效果。</p>
      <small>來源：《修業階段課程供給與首次修讀》§2、§3.1、§3.3。</small>
    </details>
    <details><summary>轉換授課語言後，可以追蹤什麼？</summary>
      <p>研究以每門課首次可見的選入紀錄為起點，分開統計達 60 分、未達門檻、停修及資料未知或衝突，再追蹤四學期內是否再次選入。比較時要保留缺值分母，並確認學生在追蹤窗末仍有可見紀錄。</p>
      <small>來源：《授課語言轉換與學生修課路徑及學習表現之關聯研究》。此處呈現評估方法，CE2005 的課程成效仍待核對。</small>
    </details>
  </section>;
}
