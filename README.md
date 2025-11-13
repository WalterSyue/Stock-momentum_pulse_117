# 台股選股一條龍（參數化版本）

主程式：`tw_stock_screen.py`  
此版本支援 **CLI 參數** 與 **YAML/JSON 設定檔 (`--config`)**，可自訂所有技術指標的「週期」與「門檻」。

---

## 🚀 功能總覽

- 自動下載 TWSE / TPEx 全部股票清單  
- 自動下載 Yahoo Finance 歷史資料  
- 以五大條件進行選股（可全參數化）  
- 中文化輸出（符合 / 不符合、出場原因）  
- 完整報表 `tw_screen_report_all.csv`  
- 可自由調校：EMA、MACD、KD、ADX、成交量均線

---

## 📦 安裝（必要套件）

```bash
pip install pandas numpy requests yfinance
```

---

## 🏃‍♂️ 快速開始

### 1. 完全自動 — 抓清單 ➜ 抓股價 ➜ 篩選
```bash
python tw_stock_screen.py --start 2022-01-01 --end 2025-12-31 --report_all
```

### 2. 使用你自己的清單
```bash
python tw_stock_screen.py --from_csv twse.csv tpex.csv --start 2022-01-01 --end 2025-12-31 --report_all
```

### 3. 指定特定股票
```bash
python tw_stock_screen.py --codes 2330,2317,8046 --report_all
```

---

## ⚙️ 所有 CLI 參數（完整版）

### 🎯 清單來源

| 參數 | 說明 |
|------|------|
| `--skip_fetch` | 不抓 TWSE / TPEx 清單 |
| `--from_csv` | 指定 CSV 清單來源 |
| `--tickers` | 一行一個代碼 |
| `--codes` | 直接輸入股票代碼 |
| `--market` | TW / TWO |

---

## 📅 資料期間

| 參數 | 說明 |
|------|------|
| `--start` | 開始日期 |
| `--end` | 結束日期（預設今日） |

**建議抓 2.5 ～ 3 年資料**  
讓 EMA117 / ADX / MACD 有足夠「暖機」資料。

---

## 📊 技術指標參數（完全可調）

### 📈 EMA（均線）
| 參數 | 預設 | 說明 |
|------|------|------|
| `--ema` | 117 | EMA 期數（中期趨勢線） |

---

### 🔊 成交量均線（量增判斷）
| 參數 | 預設 | 說明 |
|------|------|------|
| `--vol_fast` | 5 | 快線均量 |
| `--vol_slow` | 10 | 慢線均量 |

---

### 🎚️ KD 指標
| 參數 | 預設 | 說明 |
|------|------|------|
| `--kd_n` | 9 | KD 回看區間 |
| `--kd_k` | 3 | K 平滑 |
| `--kd_d` | 3 | D 平滑 |
| `--kmin` | 20 | K 最低 |
| `--kmax` | 80 | K 最高 |
| `--dmin` | 20 | D 最低 |
| `--dmax` | 80 | D 最高 |

---

### 📉 ADX 趨勢強度
| 參數 | 預設 | 說明 |
|------|------|------|
| `--adx_period` | 14 | ADX 計算期數 |
| `--adx` | 33 | 趨勢強度門檻 |

---

### 📉 MACD 多頭動能
| 參數 | 預設 | 說明 |
|------|------|------|
| `--macd_fast` | 12 | 快線 EMA |
| `--macd_slow` | 26 | 慢線 EMA |
| `--macd_signal` | 9 | 訊號線 |
| `--macd_pos` | true | 是否要求 MACD > 0 |
| `--macd_cross` | true | MACD 線 > 訊號線（黃金交叉） |

---

## 📝 YAML 設定檔（含中文註解）

```yaml
ema_period: 117            # 中期均線；越大越平滑
vol_fast: 5                 # 快速成交量均線
vol_slow: 10                # 慢速成交量均線

kd_n: 9                     # KD 計算視窗
kd_k: 3                     # K 平滑
kd_d: 3                     # D 平滑
kmin: 20                    # K 最低區間
kmax: 80                    # K 最高區間
dmin: 20                    # D 最低區間
dmax: 80                    # D 最高區間

adx_period: 14              # ADX 計算視窗
adx_min: 33.0               # 趨勢強度需 > 33

macd_fast: 12               # MACD 快線 EMA
macd_slow: 26               # MACD 慢線 EMA
macd_signal: 9              # MACD 訊號線
macd_require_positive: true # MACD 是否必須 > 0
macd_require_cross: true    # MACD 線需大於訊號線（黃金交叉）
```

---

## 📤 輸出說明

| 檔案 | 說明 |
|------|------|
| `tw_screen_results.csv` | 符合條件的股票 |
| `tw_screen_report_all.csv` | 全部股票＋各條件通過與指標值 |

---

## ❓ 為什麼使用這五大條件？

1. **EMA117：** 判斷大趨勢  
2. **量增：** 買盤在推動，而不是假突破  
3. **KD 區間：** 避免追高（>80）與撿刀（<20）  
4. **ADX>33：** 確定是強趨勢而不是盤整  
5. **MACD 多頭：** 動能翻多，確實有人正在買  

➡ 五項同時成立 = **短波高勝率進場點**
