
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
ema_period: 117        # EMA 週期，越大越偏中長期
vol_fast: 5            # 短均量天數（放量判斷）
vol_slow: 10           # 長均量天數

kd_n: 9                # KD 計算區間
kd_k: 3                # K 線平滑
kd_d: 3                # D 線平滑
kmin: 20               # K 下界（避免撿飛刀）
kmax: 80               # K 上界（避免追太高）
dmin: 20               # D 下界
dmax: 80               # D 上界

adx_period: 14         # ADX 計算週期
adx_min: 33.0          # ADX 趨勢強度門檻（>33 通常是有趨勢）

macd_fast: 12          # MACD 快線
macd_slow: 26          # MACD 慢線
macd_signal: 9         # MACD 訊號線
macd_require_positive: true   # 是否要求 MACD > 0
macd_require_cross: true      # 是否要求 MACD 線 > 訊號線

# ------------------------------------------------------------
# 出場條件設定（訊號只會對持股清單推播）
# ------------------------------------------------------------
exit_ema_break_bars: 2        # 連續 N 天收盤都在 EMA 下面 → 趨勢轉弱
exit_volume_fade: true        # 量縮 + 跌破 MA5 → 量能轉弱
exit_macd_flip: true          # MACD 翻空（MACD < 訊號線 且 < 0）
exit_adx_weaken: true         # ADX 持續走弱
exit_adx_weak_threshold: 25   # ADX 低於此值 → 趨勢不足
exit_adx_weak_bars: 3         # ADX 連續 N 根往下
exit_kd_death_high: true      # KD > 80 高檔死亡交叉

# ------------------------------------------------------------
# 停損 / 追蹤停損設定
# ------------------------------------------------------------
stop_atr_period: 14           # ATR 計算 period
stop_atr_mult: 2.0            # 初始停損 = 收盤 - ATR * 倍數
trail_use_ema: true           # 是否啟用 EMA 當追蹤停損
trail_ema_period: 50          # 追蹤停損用的 EMA 週期

# ------------------------------------------------------------
# 評分權重（用來排序用）
# ------------------------------------------------------------
score_w_trend: 0.3            # 趨勢強度（收盤 / EMA）
score_w_vol: 0.2              # 量能放大（短均量 / 長均量）
score_w_adx: 0.3              # 趨勢穩定度（ADX / adx_min）
score_w_macd: 0.2             # MACD 動能

# ------------------------------------------------------------
# Telegram 推播設定
# ------------------------------------------------------------
telegram_token: "telegram_token"   # 這裡換成你的 Bot Token
telegram_chat_id: "telegram_chat_id"            # 這裡換成你的 Chat ID
notify_on_entry: true                       # 是否推播進場訊號
notify_on_exit: true                        # 是否推播出場訊號（只對持股）

# ------------------------------------------------------------
# 回測設定（選用）
# ------------------------------------------------------------
enable_backtest: true              # true = 執行完掃描後會做回測
backtest_initial_capital: 1000000   # 初始資金
backtest_risk_per_trade: 0.1        # 單筆部位最大資金比例（0.1 = 10%）
backtest_commission_pct: 0.001      # 單邊手續費（0.1%）
backtest_slippage_pct: 0.001        # 假設滑價（0.1%）
backtest_max_positions: 1           # 保留參數（目前簡化: 單檔輪動）
backtest_min_holding_days: 3        # 保留參數（目前程式未強制使用）
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

