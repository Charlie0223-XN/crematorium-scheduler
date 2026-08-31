# 新廠四週排班

以 28 天日期模板和 13 名人員休假為輸入，自動分配 A／B／C 崗位的 Flask 網站。

## 啟動

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

開啟 `http://127.0.0.1:5000/`。

## 使用流程

1. 選擇起始日期，建立連續 28 天模板。
2. 標記一般日、大日、停爐或其他自訂需求。
3. 依畫面指定順序，為每位人員選擇至少 8 天休假。
4. 產生班表；需要其他合法組合時可按「重新安排一次」。
5. 檢視角色比例、連續 B 與均衡分數，再下載 Excel。

完整資料與行為定義請見 `docs/DAY_CONTRACT.md`。

## 測試

```powershell
python -m unittest -v test_scheduler.py test_app.py
```
