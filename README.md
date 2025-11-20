# tw_stock_pipeline.py – 小壞蛋台股終極策略

> 全市場掃描 + 進出場訊號 + 法人資訊 + 簡易回測 + Telegram 推播  
> 單一腳本即可完成「資料抓取 → 盤後選股 → 出場偵測 → 回測統計」

---

## 1. 專案簡介

`tw_stock_pipeline.py` 是一支 **針對台股的終極盤後策略腳本**，用來：

- 自動抓取 **TWSE / TPEx 全市場股票清單**
- 透過 **Yahoo Finance / TWSE API** 下載日 K 價量資料並快取
- 計算 EMA、KD、ADX、MACD、ATR 等技術指標
- 套用 **五大進場條件** + 可選的法人資訊（「A+B」概念）
- 針對符合條件標的輸出 CSV 報表，並可選擇：
  - 只輸出「符合進場條件」的股票清單
  - 輸出「全市場所有股票」當日指標
- 只針對「持股清單」偵測 **出場訊號**，並透過 Telegram 推播
- 對指定股票進行 **簡易單檔回測**（T+1 開盤價進出場），輸出：
  - 總報酬率 / 年化報酬率 / 勝率
  - 每一筆交易進出場明細

整體設計成 **單一檔案，可攜、易改、易丟進排程（cron）**。

---

## 2. 功能總覽

### 2.1 選股核心功能

- 自動建立 / 更新 `valid_tw_codes.txt`  
  - 透過 TWSE / TPEx open data 取得全市場股票代碼  
  - 代碼格式：`2330.TW`、`5483.TWO`
- 價格下載與快取
  - `cache/` 資料夾中以 `<代碼>.csv` 快取日 K
  - 優先從快取讀取，僅補齊缺少的日期
  - 下載失敗的代碼會被寫入 `error_codes.txt` 黑名單，下次自動略過
- 技術指標計算
  - EMA（趨勢線）
  - KD 隨機指標
  - ADX 趨勢強度指標
  - MACD + Signal + Histogram
  - ATR（波動度，用於停損）
- 進場條件（五大技術條件）
  1. **股價高於 EMA**：`Close >= EMA(ema_period)`
  2. **成交量放大**：`MA(vol_fast) >= MA(vol_slow)`
  3. **KD 合理區間**：`K, D` 落在 `[kmin, kmax]` 和 `[dmin, dmax]`
  4. **趨勢強勁**：`ADX > adx_min`
  5. **MACD 多頭**：可設定是否要求 MACD > 0 且 MACD > Signal
- 法人資訊（A+B 概念）
  - A：`inst_lookback` 內的 **三大法人買賣超合計張數**
  - B：轉換為 0~1 的 **法人強度分數**，可配置 `score_w_inst` 權重參與綜合評分  
  - **不作為硬條件**，只影響排序及資訊展示

### 2.2 出場偵測

只對「持股清單」中的股票偵測出場訊號，條件包括：

- 連續 `exit_ema_break_bars` 日收盤價跌破 EMA
- 量縮且跌破 MA5（`exit_volume_fade`）
- MACD 由多翻空（`exit_macd_flip`）
- ADX 低於門檻或連續走弱（`exit_adx_weaken`）
- KD 高檔 (>80) 死亡交叉（`exit_kd_death_high`）

偵測到出場訊號時，會：

- 在 CSV 報表中寫入「出場原因代碼 / 中文解釋」
- 如啟用 Telegram，會發送 **出場卡片訊息**

### 2.3 回測功能（可選）

- 針對指定股票進行單檔回測
- 模擬邏輯：
  - 當日收盤後根據指標判斷
  - **隔日開盤價 (T+1) 進/出場**
  - 以 `backtest_risk_per_trade` 決定每筆持倉資金配置
  - 考慮手續費 / 滑價
- 輸出：
  - `backtest_results.csv`：每檔股票的總報酬率 / 年化報酬率 / 勝率
  - `backtest_trades_detail.csv`：每一筆交易明細

---

## 3. 環境需求

- 作業系統：Linux / macOS / Windows 皆可
- Python：建議 **3.9 以上**
- 基本依賴：
  - `numpy`
  - `pandas`
  - `requests`
  - `yfinance`
  - `pyyaml`（若使用 YAML 設定檔）

> 腳本內有 `_ensure_pkgs()`，在第一次執行時會自動安裝  
> `requests / yfinance / pyyaml`，但建議仍預先建立虛擬環境管理套件。

---

## 4. 安裝與準備

### 4.1 下載程式碼

```bash
git clone git@github.com:WalterSyue/Stock-momentum_pulse_117.git
cd Stock-momentum_pulse_117
```

或直接把 `tw_stock_pipeline.py` 放到任一資料夾執行也可以。

### 4.2 建立虛擬環境（建議）

```bash
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install --upgrade pip
```

首次執行腳本時若缺少套件，會自動安裝。

### 4.3 重要檔案說明

執行過程中會用到 / 產生以下檔案與資料夾：

- `tw_stock_pipeline.py`：主程式
- `config.yaml`：策略設定檔（可選，沒有就用內建預設值）
- `held_stocks.txt`：**持股清單**，出場偵測與 Telegram 出場通知只針對此清單
- `valid_tw_codes.txt`：全市場股票代碼快取
- `error_codes.txt`：下載失敗的代碼黑名單
- `cache/`：每檔股票的日 K 價量資料快取 (`<代碼>.csv`)
- `inst_flow.csv`：三大法人日買賣超資料（由 T86 API 產出）
- `tw_screen_results.csv`：符合進場條件的股票清單（預設輸出）
- `tw_all_results.csv`：全市場指標報表（啟用 `--report_all` 時產出）
- `backtest_results.csv`：回測摘要（啟用回測時產出）
- `backtest_trades_detail.csv`：回測每一筆交易明細

---

## 5. 設定檔 `config.yaml` 說明

程式內建一組 `DEFAULT_CFG`，你可以在同目錄放一個 `config.yaml` 去覆寫其中任意參數。

### 5.1 範例 `config.yaml`

```yaml
# 進場指標參數
ema_period: 117
vol_fast: 5
vol_slow: 10

kd_n: 9
kd_k: 3
kd_d: 3
kmin: 20.0
kmax: 80.0
dmin: 20.0
dmax: 80.0

adx_period: 14
adx_min: 33.0

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
exit_adx_weak_threshold: 25.0
exit_adx_weak_bars: 3
exit_kd_death_high: true

# 停損 / 追蹤停損
stop_atr_period: 14
stop_atr_mult: 2.0
trail_use_ema: true
trail_ema_period: 50

# 技術面評分權重（總和不限於 1，但建議約 1 左右）
score_w_trend: 0.3
score_w_vol: 0.2
score_w_adx: 0.3
score_w_macd: 0.2

# 法人評分權重（B）：0 = 只當資訊，不影響 score
score_w_inst: 0.0
inst_lookback: 20
inst_flow_file: "inst_flow.csv"
inst_norm: 5000.0

# Telegram 推播
telegram_token: "YOUR_BOT_TOKEN"
telegram_chat_id: "YOUR_CHAT_ID"
notify_on_entry: true
notify_on_exit: true

# 回測設定
enable_backtest: false
backtest_initial_capital: 1000000.0
backtest_risk_per_trade: 0.1
backtest_commission_pct: 0.001
backtest_slippage_pct: 0.001
backtest_max_positions: 1
backtest_min_holding_days: 3
```

> 若沒有 `config.yaml`，程式會完全使用內建 `DEFAULT_CFG`。

---

## 6. 其他輔助檔案

### 6.1 `held_stocks.txt` – 持股清單

- 一行一檔，可寫：
  - `2330`
  - `2330.TW`
  - `2603.TW 高點留意`
- 解析時只會抓「數字根碼」，例如 `2330`
- 用途：
  - 若該標的出現 **出場訊號**，則：
    - 在結果 CSV 中寫出出場原因
    - 如開啟 Telegram，會發送 **出場卡片**
  - 若該標的同時也符合進場條件，程式會判斷為「已持有」而 **不發進場通知**（避免雙重提醒）

### 6.2 `valid_tw_codes.txt` / `error_codes.txt`

- `valid_tw_codes.txt`
  - 若不存在，程式會自動呼叫 TWSE / TPEx API 建立
  - 之後每次執行直接讀檔，加快速度
- `error_codes.txt`
  - 紀錄下載一直失敗的股票代碼
  - 下次執行會直接略過，避免浪費時間
  - 若想重新嘗試，可手動刪除此檔或清空內容

---

## 7. 法人資料 `inst_flow.csv`

### 7.1 自動建檔流程

當 `config.inst_flow_file` 指定的檔案不存在時，程式會：

1. 使用 `--start`、`--end` 指定的區間
2. 逐日呼叫 TWSE T86 API：

   ```text
   https://www.twse.com.tw/rwd/zh/fund/T86?date=YYYYMMDD&selectType=ALL
   ```

3. 解析出：
   - `date`
   - `code`
   - `net_inst`（三大法人合計買賣超 **股數** → 轉成「張」）
4. 將所有紀錄輸出為 `inst_flow.csv`，格式：

   ```csv
   date,code,net_inst
   2023-01-02,2330,1234
   2023-01-02,2603,-500
   ...
   ```

### 7.2 策略中如何使用

- `get_inst_series_for_code()` 會根據股票代碼抓出對應的每日 `net_inst` time series
- 在 `screen_and_exit()` 中：
  - 計算最近 `inst_lookback` 日的法人買賣超合計張數 `inst_4w_sum`
  - 判斷：
    - `法人4週買超通過`：是否 > 0
    - `法人強度分數`：透過 `tanh(inst_4w_sum / inst_norm)` 壓縮在 [0, 1) 區間
- 法人資訊寫入最終 CSV 欄位：

  - `法人4週買超`
  - `法人強度分數`
  - `法人4週買超通過`（True / False）

---

## 8. 執行方式與常用指令

所有參數皆透過 CLI 傳入（皆有預設值，可視需求調整）。

### 8.1 基本參數說明

```bash
python3 tw_stock_pipeline.py \
    --start 2023-01-01 \
    --end   2025-12-31 \
    --config config.yaml \
    --out tw_screen_results.csv \
    --report_all \
    --codes 2330.TW,2603.TW,5483.TWO \
    --backtest_codes 2330.TW,2603.TW \
    --backtest_out backtest_results.csv
```

- `--start`：資料起始日期（含）
- `--end`：資料結束日期（預設為今日）
- `--config`：設定檔路徑（可為 YAML 或 JSON；不存在則用預設）
- `--out`：符合進場條件清單輸出檔案（預設 `tw_screen_results.csv`）
- `--report_all`：若加上此 flag，會額外輸出 `tw_all_results.csv`
- `--codes`：
  - 若指定，**只處理這些股票**
  - 可接受格式：`2330` / `2330.TW` / `5483.TWO`
  - 未指定時 → 走全市場 `valid_tw_codes.txt`
- `--backtest_codes`：要回測的股票清單，逗號分隔
- `--backtest_out`：回測摘要輸出檔案（預設 `backtest_results.csv`）

### 8.2 常見使用情境

#### 情境 1：全市場掃描 + FOCUS 進場清單

```bash
python3 tw_stock_pipeline.py \
    --start 2023-01-01 \
    --end   2025-12-31 \
    --config config.yaml
```

輸出：

- `tw_screen_results.csv`：符合五大進場條件（+ 評分）的股票清單
- 若有 `held_stocks.txt`：同時偵測出場，但不會為已持有標的發進場通知

#### 情境 2：全市場指標大表（給你玩資料）

```bash
python3 tw_stock_pipeline.py \
    --start 2024-01-01 \
    --end   2024-12-31 \
    --report_all
```

輸出：

- `tw_screen_results.csv`：符合進場條件清單（若有）
- `tw_all_results.csv`：所有股票當日指標與條件狀態（可丟進 Excel / Power BI）

#### 情境 3：只掃某幾檔 + 回測

```bash
python3 tw_stock_pipeline.py \
    --start 2020-01-01 \
    --end   2024-12-31 \
    --config config.yaml \
    --codes 2330.TW,2603.TW \
    --backtest_codes 2330.TW,2603.TW \
    --backtest_out backtest_results.csv
```

輸出：

- `tw_screen_results.csv`：這幾檔近期是否符合進場
- `backtest_results.csv`：每檔總報酬率 / 年化報酬率 / 勝率
- `backtest_trades_detail.csv`：每筆交易進出場明細

---

## 9. Telegram 推播設定

### 9.1 建立 Bot 與取得 Token

1. 在 Telegram 找 `@BotFather`
2. 使用 `/newbot` 建立 Bot
3. 取得 `Bot Token`，填入 `config.yaml`：

   ```yaml
   telegram_token: "1234567890:XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
   ```

### 9.2 取得 Chat ID

最簡單方式之一：

1. 在 Telegram 搜尋 `@userinfobot`
2. 傳一個訊息給它
3. 它會回傳你的 `chat_id`
4. 寫入 `config.yaml`：

   ```yaml
   telegram_chat_id: "123456789"
   ```

### 9.3 控制通知項目

```yaml
notify_on_entry: true   # 符合進場條件時推播（非持股）
notify_on_exit:  true   # 持股出現出場訊號時推播
```

> 持股清單中的股票即使當日也符合進場條件，為避免重複通知，程式只會對其做「出場推播」。

---

## 10. 輸出欄位簡介（`tw_screen_results.csv`）

主要欄位包括（部分節錄）：

- 基本資訊
  - `代碼`
  - `日期`
  - `收盤`
- 技術指標
  - `EMA`
  - `K值` / `D值`
  - `ADX` / `ADX14`
  - `MACD` / `MACD訊號` / `MACD柱`
  - `初始停損價(ATR)`
  - `建議移動停損(EMA50)`
- 條件狀態
  - `股價高於EMA`
  - `成交量放大`
  - `KD合理區間`
  - `趨勢強勁`
  - `MACD多頭`
  - `法人4週買超通過`
  - `是否符合`（符合 / 不符合）
- 評分與法人
  - `綜合評分(score)`
  - `法人4週買超`
  - `法人強度分數`
- 出場資訊
  - `出場原因代碼`
  - `出場原因中文`（使用 `EXIT_REASON_MAP` 翻譯）

---

## 11. 常見問題與排錯（FAQ）

### Q1. 一執行就說「找不到 inst_flow.csv」

**說明：**

- 這是正常行為，程式偵測不到法人檔時會自動呼叫 T86 API 建檔
- 若公司網路或 TWSE API 無法連線，可能會出錯

**建議排查：**

1. 確認可以連上 `https://www.twse.com.tw`
2. 若頻寬 / VPN 有限制，可先縮短 `--start` / `--end` 區間
3. 也可以先手動停用法人功能，在 `config.yaml` 設：

   ```yaml
   score_w_inst: 0.0
   ```

---

### Q2. 某些股票一直下載失敗怎麼辦？

- 這些代碼會被寫入 `error_codes.txt`
- 若你想重新嘗試，可：
  - 刪除此檔案，或
  - 刪除其中的特定代碼

---

### Q3. Yahoo Finance 有時回傳空資料？

程式的流程：

1. 先試 `yahoo_download()`（支援 `start` / `end` 篩選）
2. 若失敗，再試：
   - `period="5y"` → `2y` → `max`
3. 若仍失敗，會再試 TWSE / TPEx fallback（目前只支援 TWSE 日 K）

如果連 Yahoo + TWSE 都拿不到資料，該代碼會被寫入黑名單。

---

## 12. 授權與免責聲明

- 此腳本僅作為 **技術分享與研究用途**，不構成任何投資建議
- 股市有風險，投資前請自行評估風險承受度
- 使用者需自行承擔使用本程式所帶來的一切風險與損失

---

## 13. 後續規劃（可自行擴充）

- 加入更多技術指標（如布林通道、RSI 等）
- 支援多檔持股 / 組合層級回測
- 將 CSV 結果串接到 Dashboard（如 Streamlit / FastAPI 前端）
- 自動排程（Linux `cron` / Windows Task Scheduler）  
  - 例如：每天收盤後自動執行，推播今天的進場 / 出場訊號

