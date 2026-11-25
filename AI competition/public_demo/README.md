# EMI 師資證據助理：可下載的合成展示

**所有教師、課號、授課事件均由程式獨立虛構；不是對真實校務資料改名或加亂數。不得引用此處數字作研究結論或真實教師評價。**

## 如何下載與開啟

**最方便：下載 [EMI_Public.pbix](EMI_Public.pbix)，在 GitHub 檔案頁按 Download raw file，再用 Power BI Desktop 開啟。**合成資料已匯入，無須下載整個倉庫；不需要你的 SQL Server、Azure 或模型金鑰。兩頁報表已在 Desktop 載入、檢查降序橫條與點教師連動證據後另存。

要修改報表原始定義，才使用 PBIP 專案方式：

1. 在 GitHub 倉庫按 **Code → Download ZIP**，解壓縮；或使用 `git clone`。
2. 保留本目錄及兩個相鄰的 `.Report`、`.SemanticModel` 資料夾，使用新版 **Power BI Desktop** 開啟 [EMI_Public.pbip](EMI_Public.pbip)。只下載單一 PBIP 文字檔不足以開啟報表。
3. 按 **重新整理** 載入模型內嵌的合成資料。無須 Python、SQL Server、Azure、帳號密碼或原始校務檔案；Desktop 本身需已安裝。
4. 第一頁選 `DEMO101`，查看三名示例教師及五構面分數；按「查看推薦」進第二頁。
5. 第二頁教師橫條由高到低排序；點選一位教師，摘要與證據表跟著篩選。點空白解除；`DEMO401` 展示只有一名有證據候選的情境。

Desktop 編輯模式的導覽按鈕使用 Ctrl＋點擊，也可直接按下方頁籤切頁。公開 PBIX 與 PBIP 都是這批合成資料；真實本機報表不能直接公開。

## 公開了什麼

- `fictional_offerings.json`：25 筆手工設計的虛構授課紀錄、6 位示例教師；沒有讀取或對照真人資料。
- `cases/`：4 門虛構必修課的前三名快照，共 10 筆候選與課程組合；不足三位保留不足。
- `data/`：Courses、Candidates、Evidence 三表的可閱讀 JSON，含 43 筆候選與證據連結。同一事件可支持不同目標課，連結數不能當獨立班數。
- `EMI_Public.SemanticModel/model.bim`：同一批合成資料內嵌在 Power Query `#table`，不含資料庫連線與本機絕對路徑。
- `EMI_Public.Report/`：兩頁報表定義、同步篩選器、0–100 分橫條及證據互動。不使用原人資範例資料或背景圖片。
- `EMI_Public.pbix`：Desktop 匯入合成資料後儲存的單檔下載版；重建產生器不會自動更新此二進位檔，改資料或版面後需在 Desktop 載入新版 PBIP、重新整理並另存 PBIX。
- `manifest.json`：合成資料來源、筆數、評分入口及限制。

## 保留的是規則，不是真實數值

合成資料呼叫 **同一個** `src/recommend_teachers.py::rank_teachers` 計分：同課經驗 30、正式 EMI 30、英語授課 15、相關課程 15、新近性 10。課名以字元 TF-IDF（2–4 gram）比較，相關課門檻為 0.25。新近性依 1051–1151 的固定學期索引換算；此處學期只是虛構事件的示例時間。

總分沿用正式程式先加未四捨五入構面、再取兩位小數的結果；表面分項各自四捨五入，加總偶爾可能差 0.01。分數代表歷史證據強度，不是適任機率、教學品質或正式 EMI 資格。聘任、意願、負荷與時段均未知。

**不保證合成結果與真實推薦相同，也沒有把真實排序或統計搬到公開版。**這個版本用於展示系統行為、驗證鍵值與重現計分流程。

## 重建（維護者）

在 `AI competition` 目錄執行：

```powershell
uv sync --locked
uv run --locked python src/build_public_demo.py
uv run --locked python -m unittest discover -s src -p test_public_demo.py -v
```

產生器只覆寫本公開目錄的合成定義；保留本機 `outputs/` 報表與校務資料庫。開啟 Desktop 手調前請另存工作副本，避免重建覆寫版面。

## Agent 與 API

本報表本身不會呼叫 LLM。完整規劃、前後端與 Azure SQL 的關係、工具呼叫、embedding、防注入及 OpenAI 額度說明見 [Agent 與 API 架構](../AGENT_API_ARCHITECTURE.md)。這份文件明確區分已完成與待實作，不代表已部署雲端 Agent。

Power BI 格式參考：[Microsoft PBIP 文件](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview)。
