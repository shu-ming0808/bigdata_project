# AI competition

## 競賽與目標

Microsoft × NCU AI 創新應用主題挑戰賽：AI for Better Campus & Life。

作品暫定：**EMI 師資證據助理**。擬定使用情境是系所或承辦人輸入一門預計改為 EMI 的資工系學士班必修課，取得最多三位教師候選，以及同課／相關課經驗、既往英語與正式 EMI、時間新近性和待核對行政限制。正式服務單位與工作流程尚待訪談確認，不與研究專題所屬單位混用。

目前提供單課合成案例的 React 與 FastAPI 展示。預設由 Codex CLI 產生摘要，也可設定 Azure OpenAI 產生有引用的說明。

## 使用 Docker Compose

在 `AI competition` 目錄執行以下指令，Compose 會建置所需映像、啟動前後端，並等到網頁服務可連到 API：

```bash
docker compose up --build --wait
```

開啟 http://127.0.0.1:8080 。預設提供合成案例與本機規則摘要，首次建置需連網。結束展示時，在同一目錄執行：

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

開啟 Vite 顯示的本機網址。查詢 CE2005、勾選候選人並產生摘要，點選引用可展開對應紀錄。資料與分數為合成展示案例，展示時不連線校務資料庫。

預設 `EXPLANATION_MODE=codex`。在啟動後端的帳號下執行 `codex login status` 確認已登入；首次使用可執行 `codex login`。後端透過 PATH 呼叫 `codex exec`，將所選合成案例送至 CLI 使用的模型服務。在合成案例的 Codex 模式中，每次產生說明會呼叫一次 CLI。模型從後端算好的事實中選取重點，顯示文字、筆數與引用由後端依同一組授課紀錄產生。若要離線展示，可設定 `EXPLANATION_MODE=local` 逐筆整理證據。若要使用 Azure，請在後端啟動前設定 `EXPLANATION_MODE=azure`、`AZURE_OPENAI_ENDPOINT`（資源根網址）、`AZURE_OPENAI_DEPLOYMENT`（支援 structured outputs 的部署名稱）與 `AZURE_OPENAI_API_KEY`。憑證僅置於後端環境。Azure 失敗時畫面顯示錯誤，候選與證據仍可操作。

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

## 下一步與 Demo

1. 確認一個實際使用者痛點：把查歷史紀錄的時間縮短，並讓候選理由可逐條回查；請承辦／系所審核少量案例。
2. 先做單課流程：輸入 CE2005 → 候選與分項得分 → 展開證據 → 行政待核對。不足三人就顯示實際人數。
3. 加入受限 AI 說明：只根據檢索回來的結構化證據摘要，每項理由附證據 ID，缺資料須回答未知；不讓模型自行編造教師資格或分數。
4. 視授權與可用環境選擇 Microsoft 模型／工具串接；原始校務資料不得因參賽而自動送往雲端。公開 Demo 優先使用明示的合成示例或核准去識別證據。
5. 評估證據引用正確率、無證據陳述率、查找耗時及承辦人候選合理性；尚無標註前不宣稱推薦準確率。

## 報名規劃

依使用者提供公告：2026-12-04 23:59 繳件、12-11 初審公告、12-30 決賽；每組發表 3 分鐘、問答 2 分鐘。初審需 PowerPoint。評分細項與作品規範仍需正式競賽辦法核對。

目前優先完成一個可操作案例與驗證，再製作「問題／AI／解決方案／影響」簡報。[報名表](https://forms.gle/WDCaGbJKmF7t2ovA6)。

## Note：權重

現行權重是暫定規則。後續可請使用單位以 AHP 成對比較構面重要性並檢查一致性；尚未取得專家判斷，不宣稱已用 AHP 算出權重。

## Demo 中的研究背景

開課規劃區呈現[修業階段課程供給與首次修讀](../Big%20Data%20Analytics%20Program/專題_修業階段供給與首次修讀.md)第 3.1 節的資訊電機學院彙總與第 3.3 節的代理指標限制，並依[授課語言轉換研究計畫](../Big%20Data%20Analytics%20Program/RESEARCH_PLAN.md)說明後續追蹤方法。研究數據是文件記載的歷史彙總；下方 CE2005 教師查詢使用合成案例。教師排序及模型摘要只取用該案例的授課證據。

## CE2005 實際開課案例

在本目錄執行 `uv run --locked python src/build_demo_case.py "<開課資料 CSV 路徑>"`，再執行 `docker compose up --build --wait --force-recreate`。轉換器使用 1051–1151 的開課檔、排除無班次鍵與鍵值重複的列，按既有正常開課、單一教師與資工系必修推薦規則計分。證據編號為學期與課程流水號。教師按來源姓名歸組並以排名代碼展示，尚未核對人事識別碼。實際案例保存在 Git 忽略的 outputs/demo，唯讀掛載到後端；缺少快照時，實際資料查詢會提示尚未載入，使用者可自行開啟合成案例。實際資料使用本機摘要，可在頁面切換至合成案例測試 Codex。
