# Python 環境與套件版本（uv）

`pyproject.toml` 列出直接依賴，`uv.lock` 鎖定完整依賴版本，`.python-version` 指定預設 Python 3.13。三者應一同納入 Git；`.venv/` 只留在本機。程式碼版本與協作仍使用 Git，uv 管理 Python、虛擬環境和套件版本。

## 初次安裝

在專案根目錄使用 PowerShell：

```powershell
uv sync --locked
uv run --locked python .\src\analyze_undergraduate_eight_plus.py
```

產出 PDF 報告或使用本機 notebook 時，按需要安裝額外依賴：

```powershell
uv sync --locked --extra reports
uv sync --locked --extra notebook
uv sync --locked --all-extras
```

報告腳本需要本機資料與中文字型；分析腳本仍需既有 MySQL 與 `codex-local` login path。上述指令不會下載或匯入受保密協議保護的校務資料。

## 更新依賴

```powershell
uv add "pandas>=2.2,<3"
uv add --optional reports "reportlab>=4,<5"
uv lock
uv sync --locked
```

套件版本修改後，將 `pyproject.toml` 和 `uv.lock` 一起提交。`requirements.txt` 保留給舊執行流程參考；新增或更新依賴以 `pyproject.toml` 為準，避免兩份清單分岔。
