# EMI 師資選擇 agent ：以歷年授課紀錄輔助教師候選推薦

## 公開下載：合成展示版

其他人可直接下載 **[EMI_Public.pbix](public_demo/EMI_Public.pbix)**，在 GitHub 檔案頁按 Download raw file，用 Power BI Desktop 開啟即可操作，不需你的資料庫或金鑰。兩頁已在 Desktop 驗證載入、得分排序與點選教師連動證據。[下載與操作說明](public_demo/README.md)。

要修改報表原始定義，可下載整個倉庫，以 Desktop 開啟 **[EMI_Public.pbip](public_demo/EMI_Public.pbip)** 並重新整理；保留相鄰 Report 與 SemanticModel 資料夾，不能只下載單一 PBIP。

本版獨立虛構 4 門課、6 位示例教師及 25 筆授課紀錄，呼叫同一個正式五構面評分程式，保留兩頁查詢、分數降序橫條及證據連動。**不是把真實教師改名或加亂數，不保留真實數值或排序；不能當研究結論。**沒有資料庫連線、帳密或校務原始資料。

```powershell
uv run --locked python src/build_public_demo.py
uv run --locked python -m unittest discover -s src -p test_public_demo.py -v
```

目前 Power BI 是查詢報表，完整工具型 Agent 尚待實作。前後端 API、Azure SQL 的關係、OpenAI 串接、embedding、防注入與額度規劃見 **[Agent 與 API 架構](AGENT_API_ARCHITECTURE.md)**。Azure SQL 雲端部署目前未由程式驗證；下方的 SQL Server 與 outputs/ 入口是保留於本機的真實資料版本，與公開版分開。

## 為何做這個主題

> 隱私更新：Power BI 中的教師姓名已改為中間字 O 遮罩，例如「王小明 → 王O明」。候選排名、橫條、摘要與證據表使用相同遮罩；候選仍以 CandidateKey 關聯。原始資料不改，遮罩後仍不得把具授課紀錄的報表當作完全匿名資料公開。

既有 EMI 報表請關閉後，在本目錄依序執行下列指令，再於 Power BI Desktop 重新整理並儲存：

    uv run --locked python src/mask_existing_powerbi.py
    uv run --locked python src/load_powerbi_sqlserver.py

第一步遮罩本機產生的展示資料、清除舊的匯入快取，保留手調版面及來源快照；後續重建與 SQL 匯入也會自動遮罩。三字以上姓名保留首尾，中間全部換成 O；兩字只保留首字，單字全部遮罩。同課若遮罩後重名，須改用候選代碼辨識，避免圖表合併。

學校推動 EMI 課程時，可能面臨師資難尋或教師承接意願不足，增加基層承辦人的協調負擔。本作品以資工系必修課為起點，整合歷年授課、英語教學與新近性證據，透過候選排序、Power BI 查詢及 AI 說明，協助快速找到可洽詢教師並回查推薦依據；資格、意願與排課仍由各系所確認。

## 為何選擇 Azure 與 Power BI

本作品要協助校務承辦人，從歷年開課紀錄找到可追溯的教師候選。工具選擇同時考慮校務資料的保密需求，以及承辦人實際查詢、比較與查證的操作負擔。

### Azure：以校方可管理的 AI 服務作為規劃方向

校務資料包含教師姓名、授課紀錄及可能涉及個人的資訊，使用範圍受資料授權與保密約定限制。因此規劃採用 Azure OpenAI，由組織管理資源、存取權限與後端憑證，並在獲准部署時評估角色權限、私人端點及網路限制。模型僅根據必要的結構化證據協助整理理由，分數仍由可回查的程式規則計算。

目前真實校務快照只使用本機摘要；Azure 流程僅供合成案例測試，Power BI 尚未直接串接 Azure。尚未完成真實 Azure 部署呼叫或私人端點設定驗證。未取得校方資料外送授權前，原始資料與具名證據維持本機，不因參賽而上傳模型服務。

參考：[Microsoft 資料、隱私與安全說明](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/openai/data-privacy)、[組織權限架構](https://learn.microsoft.com/azure/architecture/ai-ml/architecture/baseline-openai-e2e-chat)、[私人端點與網路設定](https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/network)。

### Power BI：讓校務人員以選課、比較與查證完成工作

Power BI 作為主要展示與查詢介面，讓承辦人不用操作 Python 或 SQL，就能選擇課程、比較候選教師的分項證據分數，再點選教師查看授課歷史與證據 ID。兩頁導覽將「先看候選」與「再查依據」串起來，也把未知行政資格保留為待核對事項，支援人工決策。

- **容易閱讀：**以橫條排名、分項表格及文字摘要呈現，降低逐筆翻找資料的負擔。
- **容易查證：**課程、候選與證據連動，可追溯推薦依據；實際能節省多少時間，仍需承辦人操作測試。
- **方便維護：**連接本機 SQL Server 的專用展示表，透過 Import 重新整理取得更新資料；分數、資料與介面各自維護。
- **控制資料範圍：**目前只在本機 Desktop 使用，未發布 Power BI Service。Import 報表可能包含具名資料，PBIX、模型與輸出也需當作受保護檔案，不公開下載；未來分享須另核對校方授權、工作區及存取權限。

## Demo：兩頁式 Power BI

目前以 **[新版 EMI.pbip](outputs/powerbi_hiring_style/EMI.pbip)** 取代網頁 Demo 作為主要展示入口。[本機操作說明](outputs/powerbi_hiring_style/操作說明.md)。請用 Power BI Desktop 開啟。

此相對連結供本機使用；outputs/ 被 Git 排除，所以 GitHub 不提供報表與教師明細下載。

| 頁面 | 內容與操作 |
| --- | --- |
| 01 課程與候選比較 | 選單一課號，查看候選覆蓋、排名及五構面分數；按「查看推薦」進第二頁 |
| 02 教師得分與授課證據 | 教師總分橫條由高到低；點教師篩選推薦摘要與授課證據，可返回選課 |

### 更新新版報表

若來源改變，先重建真實候選快照，再在本目錄依序執行：

    uv run --locked python src/build_powerbi_demo.py
    uv run --locked python src/load_powerbi_sqlserver.py
    uv run --locked python src/style_powerbi_demo.py
    uv run --locked python src/build_powerbi_two_pages.py
    uv run --locked python src/build_powerbi_hiring_style.py

最後用 Desktop 開啟新版 EMI.pbip 並重新整理。產生器重跑會覆寫對應輸出定義；手動微調後請另存工作副本。報表、教師明細與資料均只留本機，未發布雲端。

## SQL Server 與 Power BI

本機已建立 EMI_Demo 資料庫與 pbi 三表；推薦報表可透過 SQL Server 匯入模式連線。更新入口為 `src/load_powerbi_sqlserver.py`，設定、更新順序與驗收限制見 [SQL Server / Power BI](SQLSERVER_POWERBI.md)。本次僅匯入推薦展示資料，網頁後端仍讀取本機快照，學生資料與原 MySQL 保留。

<details>
<summary>早期 Power BI 與網頁 Demo 操作紀錄（非目前主要入口）</summary>

## 舊版 Power BI 本機報表專案

執行 `uv run --locked python src/build_powerbi_demo.py`，從真實候選快照建立 `outputs/powerbi/EMI.pbip`。報表包含課程篩選、候選排名及分項、逐筆授課證據、本機事實摘要與待核對條件。資料模型為 Courses → Candidates → Evidence，含真實姓名的 CSV、模型與報表均在被 Git 排除的 outputs/，未發布。

需使用 Power BI Desktop 開啟 EMI.pbip 並重新整理；閱讀版 Power BI App 無法代替 Desktop。已驗證報表 JSON schema、主外鍵與筆數，尚未在 Desktop 驗證版面和點選互動，不能宣稱已完成 PBIX 視覺驗收。詳細操作見本機 outputs/powerbi/開啟與展示.md。資料更新後先重建真實快照，再執行上述產生器。

## 目前本機展示（2026-11-25）

頁面預設讀取真實開課快照，而非合成教師。查 CE2005 看三位候選，查 CE1003 看不足三人的真實情境。姓名按來源顯示，尚未核對教師人事 ID；歷史證據分數沿用正式五構面推薦規則，不使用合成案例簡化規則。實際資料摘要始終在本機產生。

重建全部資工必修快照（僅限授權本機；不會把資料提交 Git）：

    uv run --locked python src/build_demo_case.py "<開課資料 CSV 路徑>" --all-required --show-names

不加 --show-names 則以候選代碼顯示。19 門快照儲存於被 Git 排除的 outputs/demo/。來源更新後須重建並重啟後端；這是本機檔案快照，不是即時資料庫連線。對外展示姓名與紀錄仍須依資料授權處理。以下保留先前操作說明，合成模式須自行勾選。

## 競賽與目標

Microsoft × NCU AI 創新應用主題挑戰賽：AI for Better Campus & Life。

作品暫定：**EMI 師資證據助理**。擬定使用情境是系所或承辦人輸入一門預計改為 EMI 的資工系學士班必修課，取得最多三位教師候選，以及同課／相關課經驗、既往英語與正式 EMI、時間新近性和待核對行政限制。正式服務單位與工作流程尚待訪談確認，不與研究專題所屬單位混用。

目前提供單課合成案例的 React 與 FastAPI 展示。合成案例預設使用 Azure OpenAI 選擇有證據的事實，後端產生筆數、文字與引用。設定與驗收見 [Azure 展示說明](AZURE_DEMO.md)。

## 使用 Docker Compose

在 `AI competition` 目錄執行以下指令，Compose 會建置所需映像、啟動前後端，並等到網頁服務可連到 API：

```bash
docker compose up --build --wait
```

開啟 http://127.0.0.1:8080 。預設提供合成案例與 Azure 說明；先依 AZURE_DEMO.md 設定 .env。缺設定時候選與證據仍可操作，摘要會提示缺少設定。首次建置需連網。結束展示時，在同一目錄執行：

```bash
docker compose down
```

若要沿用主機已登入的 Codex CLI，首次啟動前複製 `compose.codex.yaml` 為 `compose.override.yaml`。Compose 之後每次啟停都會自動套用。此設定唯讀掛載主機的 `${CODEX_HOME:-$HOME/.codex}/auth.json`。Linux 預設 UID/GID 為 1000；其他使用者可在本目錄的 `.env` 設定 `DEMO_UID` 與 `DEMO_GID`。連接埠可用 `DEMO_PORT` 調整。

## 啟動互動 Demo

在 `AI competition` 目錄開啟兩個終端機。第一個啟動後端：

```bash
uv sync --locked
uv run --locked uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

第二個啟動前端：

```bash
cd frontend
npm ci
npm run dev
```

開啟 Vite 顯示的本機網址。查詢 CE2005、勾選候選人並產生摘要，點選引用可展開對應紀錄。資料為合成展示案例，分數由後端依明示的示例規則重算，不由模型給分；展示時不連線校務資料庫。另有 DEMO-LOW 證據不足案例。

預設 `EXPLANATION_MODE=azure`，設定方式見 AZURE_DEMO.md。Codex 為選用模式，須明確指定 EXPLANATION_MODE=codex。在啟動後端的帳號下執行 `codex login status` 確認已登入；首次使用可執行 `codex login`。後端透過 PATH 呼叫 `codex exec`，將所選合成案例送至 CLI 使用的模型服務。在合成案例的 Codex 模式中，每次產生說明會呼叫一次 CLI。模型從後端算好的事實中選取重點，顯示文字、筆數與引用由後端依同一組授課紀錄產生。若要離線展示，可設定 `EXPLANATION_MODE=local` 逐筆整理證據。若要使用 Azure，請在後端啟動前設定 `EXPLANATION_MODE=azure`、`AZURE_OPENAI_ENDPOINT`（資源根網址）、`AZURE_OPENAI_DEPLOYMENT`（支援 structured outputs 的部署名稱）與 `AZURE_OPENAI_API_KEY`。憑證僅置於後端環境。Azure 失敗時畫面顯示錯誤，候選與證據仍可操作。

</details>

## 已有能力

- 正常開課、明確單一教師證據；排除合授。
- 同課號及課名字元 TF-IDF 候選檢索。
- 五構面 0–100 歷史證據分數、前三名排序、證據開課 ID。
- 必修授課歷史、學年學期、正式 EMI 與英語授課分列；未知不當作否。
- 歷史覆蓋檢查與 CE2005 案例；數值以本機輸出及 STATUS.md 為準。

分數不是教學品質或正式資格；教師目前按姓名辨識，聘任、意願、負荷與時段未知者一律待人工核對。不使用學生分群或成績替教師評分。

## 目錄與共用邊界

- src/recommend_teachers.py：競賽專用推薦程式，由 Git 歷史恢復教師邏輯並提供獨立入口。
- outputs/：競賽本機結果，已搬入原教師輸出，不進 Git。
- local_archive/：舊競賽構想文件，供本機追溯，不進 Git。
- pyproject.toml、uv.lock：此子專案自己的環境設定。
- 共用唯讀查詢與學生整理仍位於 ../Big Data Analytics Program/src/；競賽透過明確路徑引用，不複製共用分析。
- 共用開課檢視表建置器在研究目錄 src/build_shared_analysis_layer.py；只在缺少檢視表且確認授權時執行，本次未重建或刪除資料庫物件。

## 執行

在本目錄：

    uv sync --locked
    uv run --locked python .\src\recommend_teachers.py --required-only --course-code CE2005
    uv run --locked python .\src\recommend_teachers.py --required-only

需本機 MySQL login-path codex-local、ncu_course_flow_1150012 與 shared_1150012_solo_teacher_v。原始資料不隨倉庫提供。
