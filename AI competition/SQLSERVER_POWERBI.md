# SQL Server → Power BI 本機展示

## 目前已建立

- SQL Server：`.\SQLEXPRESS`，Windows 驗證。
- 資料庫：`EMI_Demo`；SSMS 是管理此資料庫的工具。
- 資料表：`pbi.Courses`（19）、`pbi.Candidates`（49）、`pbi.Evidence`（1,622）。
- 主鍵與外鍵：課程 → 課程候選 → 候選證據。
- Power BI：`outputs/powerbi/EMI.pbip`，模型已改用 `Sql.Database`，採 Import 模式。重新整理才取得 SQL Server 最新內容。

此步只匯入推薦展示所需資料，沒有遷移所有學生資料、刪除 MySQL 或變更現有網頁後端的 JSON 快照來源。資料全留本機。

## 開啟

1. SSMS 連線伺服器 `.\SQLEXPRESS`，選 Windows 驗證，展開 EMI_Demo → Tables → pbi。
2. 在 Power BI Desktop 開啟 `outputs/powerbi/EMI.pbip`，按重新整理。
3. 若提示資料來源驗證，選 Windows／目前使用者；伺服器 `.\SQLEXPRESS`，資料庫 `EMI_Demo`。
4. 本機 Express 可能使用自簽憑證；若出現憑證問題，不要直接改成公開網路無加密。需針對本機受信任伺服器配置驗證，或安裝受信任憑證。
5. 選 CE2005、點選教師排名列，檢查說明與證據是否連動；篩選互動與欄寬仍待 Desktop 畫面驗收。

SSMS 範例查詢放在本機 `outputs/powerbi/SSMS_檢查.sql`。本機服務與 Power BI Desktop 已找到並啟動，但目前電腦操作工具啟動失敗，尚未代按重新整理或確認登入提示，不能宣稱 Desktop 已成功載入。

## 更新資料

先重建真實快照，再依序執行：

    uv run --locked python src/build_powerbi_demo.py
    uv run --locked python src/load_powerbi_sqlserver.py

最後在 Power BI 按重新整理。產生器第一步會建立 CSV 版模型，第二步才切成 SQL Server 模型，兩步須依序執行。

若要套用目前文青暖白版面，最後再執行 `uv run --locked python src/style_powerbi_demo.py`。主題與版面修改後，請在 Desktop 重新開啟 EMI.pbip；不要把舊視窗另存覆蓋專案，否則可能覆蓋外部修改。主題另存於本機 outputs/powerbi/文青暖白主題.json，可從 Desktop 的檢視 → 佈景主題 → 瀏覽佈景主題匯入。此為自製原生主題，非宣稱套用第三方付費模板；尚未完成 Desktop 視覺驗收。

匯入器只在 EMI_Demo 的 pbi schema 中，以交易重建三張專用展示表；不要在這三張表中存其他業務資料。Windows 驗證不需在程式內保存密碼。生成的具名 SQL、CSV、PBIP 與報表仍在被 Git 忽略的 outputs/。

官方連線說明：https://learn.microsoft.com/en-us/power-query/connectors/sql-server
