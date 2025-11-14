
# 📈 小壞蛋台股終極策略

小壞蛋幫你打造的 **台股終極自動化策略系統**  
整合：

- ✔️ 全市場掃描（上市 TWSE + 上櫃 TPEx）
- ✔️ 五大進場訊號（EMA / KD / ADX / MACD / 量能）
- ✔️ 出場訊號（只對「你持有的股票」推播）
- ✔️ Telegram 美化卡片推播（中文）
- ✔️ Cache + 黑名單自動化
- ✔️ 回測：總報酬 / 勝率 / 年化報酬率
- ✔️ 交易明細（進場日、進場價、退場日、退場價、獲利）
- ✔️ config.yaml 參數化全部策略
- ✔️ held_stocks.txt 管理你目前持有的股票

---

---

# 📁 專案結構

```
tw_stock_pipeline/
│
├── tw_stock_pipeline.py       ← 主程式
├── config.yaml                ← 所有策略參數
├── held_stocks.txt            ← 你目前持有的股票
├── valid_tw_codes.txt         ← 自動產生，全市場股票代碼
├── error_codes.txt            ← 自動產生，不可下載的股票
├── cache/                     ← 自動產生，股票日K快取
│     └── 2330.TW.csv
│     └── 2603.TW.csv
│     └── ...
└── README.md                  ← 本文件
```

---

# 🚀 如何快速開始？

## 1️⃣ 安裝 Python + pip 套件
```bash
pip install requests yfinance pyyaml pandas numpy
```

（程式會自動檢查，沒有就自動安裝）

---

## 2️⃣ 編輯 config.yaml（全部參數化）

以下是範例（實際檔案已另存，也可依需求調整）：

```yaml
ema_period: 117
vol_fast: 5
vol_slow: 10

kd_n: 9
kd_k: 3
kd_d: 3
kmin: 20
kmax: 80
dmin: 20
dmax: 80

adx_period: 14
adx_min: 33

macd_fast: 12
macd_slow: 26
macd_signal: 9
macd_require_positive: true
macd_require_cross: true

# 出場條件
exit_ema_break_bars: 2
exit_volume_fade: true
exit_macd_flip: true
exit_adx_weaken: true
exit_adx_weak_threshold: 25
exit_adx_weak_bars: 3
exit_kd_death_high: true

# 推播
telegram_token: "你的TOKEN"
telegram_chat_id: "你的CHAT_ID"
notify_on_entry: true
notify_on_exit: true

# 回測
enable_backtest: true
backtest_initial_capital: 1000000
backtest_risk_per_trade: 0.1
backtest_commission_pct: 0.001
backtest_slippage_pct: 0.001
backtest_min_holding_days: 3
```

---

## 3️⃣ 填寫持股清單 held_stocks.txt

內容：

```
2330
2603
5483
```

代表：

- **進場訊號**：全市場都會推播
- **出場訊號**：只有「你有持有的股票」才會推播（避免被洗版）

---

# 🧠 策略包含哪些進場條件？

五大進場條件：

| 條件 | 說明 |
|------|------|
| cond1 | 收盤價高於 EMA117 |
| cond2 | 量能放大：5日均量 > 10日均量 |
| cond3 | KD 落在合理區間（20~80） |
| cond4 | ADX > 33，趨勢強 |
| cond5 | MACD 多頭：>0 且 MACD > SIGNAL |

全為 True 才會被視為「進場訊號」。

---

# 📤 出場條件（中文超白話）

| 條件代碼 | 說明 |
|---------|------|
| trend_break_EMA | 股價連續數天跌破 EMA，趨勢轉弱 |
| volume_fade | 量縮＋跌破 MA5，買盤力道下降 |
| macd_flip_down | MACD 多翻空 |
| adx_below_threshold | ADX < 25，趨勢疲弱 |
| adx_weaken | ADX 連續走弱（N 天） |
| kd_death_cross_>80 | KD 高檔死亡交叉，短線反轉 |

---

# 📲 Telegram 推播示範

## 進場通知（emoji 美化）：

```
🚀 進場訊號：2330.TW
📅 日期：2024-11-01
💰 收盤：591.00
📊 EMA117：560.33
🔍 KD：K=45.2 / D=48.1
📈 ADX：36.8
📤 MACD：上升中
⭐ 綜合評分：0.812
```

---

## 出場通知（只對你持有的股票）：

```
⚠️ 出場訊號：2330.TW
📅 日期：2024-11-01
💰 收盤：580.00

📌 出場原因：
• MACD 由多轉空
• ADX 趨勢力道變弱
```

---

# 🔄 如何執行？

## 全市場掃描
```bash
python tw_stock_pipeline.py   --start 2023-01-01   --end   2025-12-31   --config config.yaml   --report_all   --out tw_screen_results.csv
```

---

## 指定掃描特定股票
```bash
python tw_stock_pipeline.py --codes 2330.TW,2603.TW
```

---

# 🧪 回測（單檔）

```bash
python tw_stock_pipeline.py   --start 2020-01-01   --end   2025-12-31   --config config.yaml   --backtest_codes 2330.TW   --backtest_out backtest_2330.csv
```

輸出：

- 總報酬率
- 年化報酬率 CAGR
- 勝率
- 每一筆交易進場/出場價格
- 交易理由
- 交易明細 CSV

---

