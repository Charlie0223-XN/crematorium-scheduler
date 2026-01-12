Day 母版資料契約 v1（定稿）

本文件為排班系統的唯一資料契約（Single Source of Truth）。
任何前端、後端、排班邏輯的修改，不得違反本文件定義之語意與行為。

一、設計目標

本輪修改不是為了提升排班演算法品質，
而是為了：

穩定「使用者意圖 → 系統行為」的對應關係

消除前端 / 後端 / 排班邏輯之間的語意誤解

明確區分 AUTO / MANUAL / OFF 三種狀態

防止系統自行推測、補齊、或更改使用者意圖

二、Day 母版資料結構（唯一合法格式）

每一天最終都必須能被正規化為以下結構：

Day {
  date: string               // YYYY-MM-DD，必填
  weekday: number             // 0~6，Monday=0（可由後端補齊）
  employees_mode: "WORK" | "OFF"
  mode: "AUTO" | "MANUAL"
  employees: string[]
  manual_assignment: { [name]: "A"|"B"|"C"|"D"|"E" } | null
}

預設值規則

缺 employees_mode → 視為 "WORK"

缺 mode → 視為 "AUTO"

缺 employees → 視為 []

缺 manual_assignment → 視為 null

缺 weekday → 由後端依 date 計算補齊

三、Day 的三種狀態（語意定義）
1️⃣ AUTO（自動排班）

系統依既有 scheduler.py 自動排班

使用 ABCCD、疲勞模型、固定 C / 固定 E 等既有邏輯

使用者不指定角色

僅在 employees_mode="WORK" 時有意義

2️⃣ MANUAL（手動排班）

使用者自行指定 A/B/C/D/E

系統 不介入、不補、不平均、不修正

不套用任何自動規則（大日、週一、疲勞模型等）

僅作「顯示與統計」

MANUAL 日的正式定義（定稿）：

當天實際上班人員 = manual_assignment 中出現的人
未被指定的人，視為不在該日排班世界中

3️⃣ OFF（停爐日）

當天不燒、不排主班

employees 允許為空陣列

系統仍需正常產出（assignment = {}）

不得因空資料而報錯

四、行為真相表（不可推翻）

系統只能依以下規則行為，不得自行推論：

employees_mode	mode	語意	系統行為	是否進 scheduler
OFF	AUTO	停爐日	直接產出空 assignment	否
OFF	MANUAL	停爐日	直接產出空 assignment	否
WORK	AUTO	自動排班	交由 scheduler 排班	是
WORK	MANUAL	手動排班	完全照 manual_assignment	否
關鍵鎖定規則

employees_mode="OFF" 的優先級 最高

mode="MANUAL" 時 絕對不進 scheduler

mode="AUTO" 時 必須忽略 manual_assignment

五、被正式取消的概念（本輪不再存在）

以下概念不得再出現在自動流程中：

❌ 大日 / 特殊日 / 週一特殊邏輯

❌ 大日 A/D 自動平均

❌ 任何「半手動」「混合模式」

❌ 需要使用者理解排班內部規則的中間概念

所有「特殊情況」一律使用 MANUAL 表達。

六、責任切割（實作共識）
前端（index.html）

僅負責讓使用者選擇：

AUTO / MANUAL / OFF
-（MANUAL 時）角色指派

不解釋、不推論排班後果

後端（app.py）

將輸入正規化為 Day 母版

依行為真相表做唯一分流

嚴禁猜測使用者意圖

排班引擎（scheduler.py）

僅處理 WORK + AUTO

不需理解 MANUAL / OFF

七、範例（MANUAL 日）

1/3 號
六個人上班

甲 A、乙 B、丙 C、丁 C、戊 D、己 E
其他未指定者不列入排班

對應 Day：

{
  "date": "2026-01-03",
  "weekday": 5,
  "employees_mode": "WORK",
  "mode": "MANUAL",
  "employees": [],
  "manual_assignment": {
    "甲": "A",
    "乙": "B",
    "丙": "C",
    "丁": "C",
    "戊": "D",
    "己": "E"
  }
}


本文件為 v1 定稿。
後續擴充需以「新增欄位或新版本」進行，不得破壞既有語意。
