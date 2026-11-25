# Azure 合成展示設定與驗收

合成案例預設使用 Azure。實際校務快照始終使用本機規則摘要，不送給 Azure 或 Codex。缺 Azure 設定時候選仍可查詢，產生說明會清楚提示 503，不偽裝成 Azure 成功。

## 設定

複製 .env.example 為 .env，填入自己的資源根網址、支援 structured outputs 的部署名稱與 API key。不要將 .env 提交或把 key 放在前端。Docker Compose 自動讀取本目錄 .env。

    Copy-Item .env.example .env
    docker compose up --build --wait

直接用 uv 啟動時，.env 不會自動載入；請在後端 PowerShell 設定對應環境變數再執行 uvicorn。API key 僅存後端環境。

    $env:EXPLANATION_MODE = 'azure'
    $env:AZURE_OPENAI_ENDPOINT = 'https://YOUR-RESOURCE.openai.azure.com'
    $env:AZURE_OPENAI_DEPLOYMENT = 'YOUR-DEPLOYMENT'
    # 以你的憑證管理方式設定 AZURE_OPENAI_API_KEY，避免寫入命令歷史。
    uv run --locked uvicorn backend.app:app --host 127.0.0.1 --port 8000

## 展示驗收

1. 勾選合成案例，查 CE2005，現在有三位示例教師。分數來源可展開查看。
2. 選候選後產生說明，成功時來源顯示 Azure AI；點引用核對課號、語言、正式 EMI 註記。
3. 點「查看證據不足案例」查 DEMO-LOW：只有一位候選，不補足三人；沒有正式 EMI 證據不得生成該項主張。
4. 缺設定、部署不支援或網路失敗時，摘要報錯，證據仍可閱讀；不自動回退後宣稱 Azure 成功。

模型只回傳候選 ID 與事實類別，不產生分數或任意理由文字。後端依證據產生筆數、文字、引用並驗證歸屬。合成示例採簡化、可回查的四項計分，上限90／滿分尺度100，新近性未計分；與正式歷史推薦的五項規則不同，不能拿兩種分數直接比較。實際快照仍是既有推薦程式計算。

## 已驗證與待驗證

後端測試使用模擬 Azure HTTP 回應，驗證請求格式、引用、缺設定、證據不足與實際資料不外送。這不等於 Azure 資源實際連線成功；仍須提供部署與憑證後完成真實呼叫。

官方規格：[Azure structured outputs](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs)。使用 v1 chat/completions 與嚴格 JSON Schema。
