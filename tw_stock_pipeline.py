#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tw_stock_pipeline.py
小壞蛋台股終極策略：
- 全市場掃描 + 五大進場條件 + 法人四週 A+B（A 只當參考資訊，不是硬條件）
- 出場訊號（只對你持有清單推播）
- Telegram 卡片推播（中文）
- valid_tw_codes 名單 + cache + error blacklist
- 簡易單檔回測：總報酬率 / 勝率 / 年化報酬率
"""

import os
import sys
import re
import io
import csv
import time
import json
import datetime as dt
from typing import List, Optional, Dict, Any

import numpy as np
import pandas as pd

# ============================================================
# 依賴套件自動確認（requests / yfinance / pyyaml）
# ============================================================

def _ensure_pkgs():
    missing = []
    try:
        import requests  # noqa
    except Exception:
        missing.append("requests")
    try:
        import yfinance  # noqa
    except Exception:
        missing.append("yfinance")
    try:
        import yaml  # noqa
    except Exception:
        missing.append("pyyaml")
    if missing:
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", *missing, "-q"]
        )

_ensure_pkgs()
import requests  # type: ignore
import yfinance as yf  # type: ignore
try:
    import yaml  # type: ignore
    HAS_YAML = True
except Exception:
    HAS_YAML = False

# ============================================================
# 全域設定 / 檔案路徑
# ============================================================

CACHE_DIR = "cache"
VALID_CODES_FILE = "valid_tw_codes.txt"
ERROR_CODES_FILE = "error_codes.txt"
HELD_STOCKS_FILE = "held_stocks.txt"

os.makedirs(CACHE_DIR, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (compatible; tw-stock-pipeline/ultimate/1.0)"}

TWSE_LIST_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_LIST_URL = "https://www.tpex.org.tw/openapi/v1/company_basic_info"

TWSE_DAY_K = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={date}&stockNo={code}"
TPEX_DAY_K = "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d={date}&s={code}"

# ============================================================
# 預設設定（可被 config.yaml 覆寫）
# ============================================================

DEFAULT_CFG: Dict[str, Any] = {
    # 進場指標
    "ema_period": 117,
    "vol_fast": 5,
    "vol_slow": 10,
    "kd_n": 9,
    "kd_k": 3,
    "kd_d": 3,
    "kmin": 20.0,
    "kmax": 80.0,
    "dmin": 20.0,
    "dmax": 80.0,
    "adx_period": 14,
    "adx_min": 33.0,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "macd_require_positive": True,
    "macd_require_cross": True,

    # 出場條件
    "exit_ema_break_bars": 2,
    "exit_volume_fade": True,
    "exit_macd_flip": True,
    "exit_adx_weaken": True,
    "exit_adx_weak_threshold": 25.0,
    "exit_adx_weak_bars": 3,
    "exit_kd_death_high": True,

    # 停損 / 追蹤停損
    "stop_atr_period": 14,
    "stop_atr_mult": 2.0,
    "trail_use_ema": True,
    "trail_ema_period": 50,

    # 評分權重（技術面）
    "score_w_trend": 0.3,
    "score_w_vol": 0.2,
    "score_w_adx": 0.3,
    "score_w_macd": 0.2,

    # Telegram 推播
    "telegram_token": None,
    "telegram_chat_id": None,
    "notify_on_entry": True,
    "notify_on_exit": True,

    # 回測設定
    "enable_backtest": False,
    "backtest_initial_capital": 1_000_000.0,
    "backtest_risk_per_trade": 0.1,
    "backtest_commission_pct": 0.001,
    "backtest_slippage_pct": 0.001,
    "backtest_max_positions": 1,
    "backtest_min_holding_days": 3,

    # 法人相關設定（A = 四週買超資訊，B = 評分，不當硬條件）
    "score_w_inst": 0.0,               # B：法人強度評分權重（0 = 只當資訊）
    "inst_lookback": 20,               # 看 20 個交易日 ≒ 4 週
    "inst_flow_file": "inst_flow.csv", # 三大法人資料檔
    "inst_norm": 5000.0,               # 正規化基準，買超越大 inst_score 越高
}

CN_COND_NAMES = {
    "cond1": "股價高於EMA",
    "cond2": "成交量放大",
    "cond3": "KD合理區間",
    "cond4": "趨勢強勁",
    "cond5": "MACD多頭",
    "cond6": "法人4週買超為正",   # 只做資訊，不做硬條件
}

EXIT_REASON_MAP = {
    "trend_break_EMA": "股價連續多天跌破 EMA，趨勢轉弱",
    "volume_fade": "成交量明顯縮小且跌破 MA5，買盤力道減弱",
    "macd_flip_down": "MACD 由多翻空，動能轉弱",
    "adx_below_threshold": "ADX 低於門檻，趨勢力道不足",
    "adx_weaken": "ADX 連續多天走弱，趨勢轉疲",
    "kd_death_cross_>80": "KD 高檔（>80）出現死亡交叉，短線轉弱",
}

# ============================================================
# 通用小工具
# ============================================================

def save_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def last_scalar(x) -> float:
    """安全拿最後一個數值，轉 float，失敗就 NaN。"""
    try:
        if isinstance(x, pd.Series):
            val = x.iloc[-1]
        elif isinstance(x, (list, tuple, np.ndarray)):
            if len(x) == 0:
                return float("nan")
            val = x[-1]
        else:
            val = x
        arr = pd.to_numeric([val], errors="coerce").values
        return float(arr[0]) if arr.size else float("nan")
    except Exception:
        try:
            return float(np.asarray(x).reshape(-1)[-1])
        except Exception:
            return float("nan")


# ============================================================
# 黑名單 / 有效清單 / 持股清單
# ============================================================

def load_error_codes() -> set:
    if not os.path.exists(ERROR_CODES_FILE):
        return set()
    lines = open(ERROR_CODES_FILE, "r", encoding="utf-8").read().splitlines()
    return {ln.strip() for ln in lines if ln.strip()}


def save_error_code(code: str) -> None:
    with open(ERROR_CODES_FILE, "a", encoding="utf-8") as f:
        f.write(code + "\n")


def load_valid_codes() -> Optional[List[str]]:
    if not os.path.exists(VALID_CODES_FILE):
        return None
    lines = open(VALID_CODES_FILE, "r", encoding="utf-8").read().splitlines()
    return [ln.strip() for ln in lines if ln.strip()]


def save_valid_codes(codes: List[str]) -> None:
    with open(VALID_CODES_FILE, "w", encoding="utf-8") as f:
        for c in sorted(set(codes)):
            f.write(c + "\n")


def load_held_stocks(path: str = HELD_STOCKS_FILE) -> set:
    """
    讀取持股清單：
    - 可以寫 2330 或 2330.TW
    - 這裡統一只記「數字代碼」方便比對
    """
    if not os.path.exists(path):
        return set()
    roots = set()
    for ln in open(path, "r", encoding="utf-8"):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        m = re.search(r"(\d+)", s)
        if m:
            roots.add(m.group(1))
    return roots


# ============================================================
# 下載 TWSE / TPEX 股票代碼（建立 valid_tw_codes.txt）
# ============================================================

def load_all_tw_codes() -> List[str]:
    codes = load_valid_codes()
    if codes is not None:
        return codes

    print("⚠ 未發現 valid_tw_codes.txt → 正在從 TWSE / TPEx 抓取代碼…")

    all_codes: List[str] = []

    # TWSE
    try:
        r = requests.get(TWSE_LIST_URL, headers=UA, timeout=20)
        js = r.json()
        if isinstance(js, list):
            for row in js:
                c = str(row.get("公司代號") or "").strip()
                if c.isdigit():
                    all_codes.append(f"{c}.TW")
    except Exception as e:
        print(f"[警告] TWSE 代碼抓取失敗：{e}")

    # TPEX
    try:
        r = requests.get(TPEX_LIST_URL, headers=UA, timeout=20)
        js = r.json()
        if isinstance(js, list):
            for row in js:
                c = str(row.get("code") or "").strip()
                if c.isdigit():
                    all_codes.append(f"{c}.TWO")
    except Exception as e:
        print(f"[警告] TPEx 代碼抓取失敗：{e}")

    all_codes = sorted(set(all_codes))
    save_valid_codes(all_codes)
    print(f"✔ 已建立 valid_tw_codes.txt（共 {len(all_codes)} 檔）")
    return all_codes


# ============================================================
# Cache 支援
# ============================================================

def load_from_cache(code: str) -> Optional[pd.DataFrame]:
    path = os.path.join(CACHE_DIR, f"{code}.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, parse_dates=["日期"])
        df = df.set_index("日期")
        return df
    except Exception:
        return None


def save_to_cache(code: str, df: pd.DataFrame) -> None:
    path = os.path.join(CACHE_DIR, f"{code}.csv")
    df.to_csv(path, encoding="utf-8-sig")


# ============================================================
# 價格下載：Yahoo + Fallback（TWSE / TPEx）
# ============================================================

def _fix_tz(df: pd.DataFrame) -> pd.DataFrame:
    if getattr(df.index, "tz", None) is not None:
        df = df.tz_localize(None)
    return df.dropna()


def yahoo_download(code: str, start: str, end: str) -> Optional[pd.DataFrame]:
    try:
        df = yf.download(code, start=start, end=end, progress=False, auto_adjust=False, threads=False)
        if df is not None and not df.empty:
            df = _fix_tz(df)
            df.index.name = "日期"
            return df
    except Exception:
        pass
    # fallback 期間模式
    for period in ["5y", "2y", "max"]:
        try:
            df = yf.download(code, period=period, interval="1d", progress=False, auto_adjust=False, threads=False)
            if df is not None and not df.empty:
                df = _fix_tz(df)
                df.index.name = "日期"
                try:
                    s = pd.to_datetime(start)
                    e = pd.to_datetime(end)
                    df = df.loc[(df.index >= s) & (df.index <= e)]
                except Exception:
                    pass
                if not df.empty:
                    return df
        except Exception:
            time.sleep(0.3)
            continue
    return None


def twse_download(code: str, years: List[int]) -> Optional[pd.DataFrame]:
    dfs = []
    for y in years:
        for m in range(1, 13):
            date = f"{y}{m:02d}01"
            url = TWSE_DAY_K.format(date=date, code=code)
            try:
                r = requests.get(url, headers=UA, timeout=10)
                if r.status_code != 200:
                    continue
                data = r.json()
                if "data" not in data:
                    continue
                rows = data["data"]
                df = pd.DataFrame(rows, columns=[
                    "日期", "成交股數", "成交金額", "開盤價",
                    "最高價", "最低價", "收盤價", "漲跌", "成交筆數"
                ])
                df["日期"] = pd.to_datetime(df["日期"].str.replace("/", "-"))
                df = df.rename(columns={
                    "開盤價": "Open",
                    "最高價": "High",
                    "最低價": "Low",
                    "收盤價": "Close",
                    "成交股數": "Volume",
                })
                for col in ["Open", "High", "Low", "Close", "Volume"]:
                    df[col] = pd.to_numeric(df[col].str.replace(",", ""), errors="coerce")
                df = df.dropna(subset=["Close"])
                dfs.append(df)
            except Exception:
                continue
    if not dfs:
        return None
    df_all = pd.concat(dfs)
    df_all = df_all.sort_values("日期").set_index("日期")
    return df_all


def tpex_download(code: str, years: List[int]) -> Optional[pd.DataFrame]:
    # 簡單版：實務上 TPEx fallback 較吃 API，這邊走極簡模式
    # 若要更強可再強化
    return None  # 先關閉，主要依賴 Yahoo


def fallback_download(code: str, start: str, end: str) -> Optional[pd.DataFrame]:
    years = list(range(int(start[:4]), dt.date.today().year + 1))
    if code.endswith(".TW"):
        base = code.replace(".TW", "")
        df = twse_download(base, years)
    else:
        base = code.replace(".TWO", "")
        df = tpex_download(base, years)
    if df is None:
        return None
    # 裁切日期
    try:
        s = pd.to_datetime(start)
        e = pd.to_datetime(end)
        df = df.loc[(df.index >= s) & (df.index <= e)]
    except Exception:
        pass
    return df if not df.empty else None


def load_price(code: str, start: str, end: str) -> Optional[pd.DataFrame]:
    """
    完整流程：黑名單判斷 → cache → Yahoo → fallback → 黑名單紀錄
    """
    error_codes = load_error_codes()
    if code in error_codes:
        print(f"[SKIP] {code} 在黑名單中，略過")
        return None

    # 先試 cache
    df_cache = load_from_cache(code)
    if df_cache is not None and not df_cache.empty:
        last_day = df_cache.index.max().date()
        end_day = pd.to_datetime(end).date()
        # cache 已涵蓋 → 直接用
        if last_day >= end_day:
            return df_cache
        # 補新的部份
        start_dl = (last_day + dt.timedelta(days=1)).isoformat()
        df_new = yahoo_download(code, start_dl, end)
        if df_new is not None and not df_new.empty:
            df_all = pd.concat([df_cache, df_new])
            df_all = df_all[~df_all.index.duplicated(keep="last")].sort_index()
            save_to_cache(code, df_all)
            return df_all
        # Yahoo 補不到 → 試 fallback
        df_fb = fallback_download(code, start_dl, end)
        if df_fb is not None and not df_fb.empty:
            df_all = pd.concat([df_cache, df_fb])
            df_all = df_all[~df_all.index.duplicated(keep="last")].sort_index()
            save_to_cache(code, df_all)
            return df_all
        # 都失敗 → 黑名單
        save_error_code(code)
        return None

    # cache 沒有 → 直接 Yahoo
    df_yf = yahoo_download(code, start, end)
    if df_yf is not None and not df_yf.empty:
        save_to_cache(code, df_yf)
        return df_yf

    # Yahoo 失敗 → fallback
    df_fb = fallback_download(code, start, end)
    if df_fb is not None and not df_fb.empty:
        save_to_cache(code, df_fb)
        return df_fb

    save_error_code(code)
    return None


# ============================================================
# 法人資料：自動抓 TWSE T86 + 讀入 inst_flow.csv
# ============================================================

def build_inst_flow(start: str, end: str, out_path: str) -> None:
    """
    自動抓 TWSE 三大法人 T86，產出 inst_flow.csv

    使用 API：
    https://www.twse.com.tw/rwd/zh/fund/T86?date=YYYYMMDD&selectType=ALL

    產出欄位：
    date, code, net_inst   （net_inst = 三大法人買賣超「張數」）
    注意：T86 回傳單位是「股數」，這裡統一除以 1000 轉成「張」。
    """
    print(f"📥 build_inst_flow：從 {start} 到 {end} 抓取 TWSE 三大法人資料…")

    try:
        d_start = dt.datetime.strptime(start, "%Y-%m-%d").date()
        d_end   = dt.datetime.strptime(end, "%Y-%m-%d").date()
    except Exception as e:
        print(f"⚠ build_inst_flow：日期格式錯誤 {e}，不產生法人資料")
        return

    records = []
    cur = d_start
    while cur <= d_end:
        # 週末跳過
        if cur.weekday() >= 5:
            cur += dt.timedelta(days=1)
            continue

        dstr = cur.strftime("%Y%m%d")
        url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={dstr}&selectType=ALL"

        try:
            r = requests.get(url, headers=UA, timeout=15)
            js = r.json()
            data = js.get("data") or []
            if not data:
                print(f"[法人] {cur} 無資料（可能非交易日 / API 無回傳）")
                cur += dt.timedelta(days=1)
                continue

            for row in data:
                code = str(row[0]).strip()
                if not code or not code[0].isdigit():
                    continue

                # T86 最後一欄是「三大法人買賣超股數合計」
                net_str = str(row[-1]).replace(",", "")
                try:
                    net_shares = int(net_str)       # 股數
                except Exception:
                    continue

                net_lots = net_shares / 1000.0     # 轉成「張」
                records.append({
                    "date": cur.isoformat(),
                    "code": code,
                    "net_inst": net_lots,
                })

            print(f"[法人] {cur} 抓取成功，{len(data)} 檔")
            time.sleep(0.3)

        except Exception as e:
            print(f"[法人] {cur} 抓取失敗：{e}")
            time.sleep(1.0)

        cur += dt.timedelta(days=1)

    if not records:
        print("⚠ build_inst_flow：沒有抓到任何法人資料，inst_flow.csv 不會更新")
        return

    df = pd.DataFrame(records)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"✔ 已輸出三大法人資料 → {out_path}（共 {len(df)} 筆記錄）")



def load_inst_data(path: str) -> Optional[pd.DataFrame]:
    """
    讀三大法人資料檔 inst_flow.csv

    預期格式：
    date,code,net_inst
    2023-01-02,2330,1234
    2023-01-02,2603,-500
    ...
    """
    if not os.path.exists(path):
        print(f"⚠ 找不到法人資料檔：{path}，將略過法人資訊與評分")
        return None

    df = pd.read_csv(path, dtype={"code": str})
    if "date" not in df.columns or "code" not in df.columns:
        print("⚠ inst_flow 檔缺少 date / code 欄位，略過法人功能")
        return None

    if "net_inst" not in df.columns:
        print("⚠ inst_flow 檔沒有 net_inst 欄位，略過法人功能")
        return None

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["code", "date"])
    df = df.set_index(["date", "code"])  # MultiIndex
    return df


def get_inst_series_for_code(inst_df: Optional[pd.DataFrame],
                             code: str,
                             index: pd.DatetimeIndex) -> Optional[pd.Series]:
    """
    從法人 DataFrame 裡，取出單一股票的 daily net_inst，
    並對齊到價格 df 的 index（日期）。
    """
    if inst_df is None:
        return None

    m = re.match(r"(\d+)", code)
    root = m.group(1) if m else None
    if not root:
        return None

    try:
        s = inst_df.xs(root, level="code")["net_inst"]
    except KeyError:
        return None

    s = s.reindex(index).fillna(0.0)
    s.name = "net_inst"
    return s


# ============================================================
# 技術指標
# ============================================================

def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def true_range(h: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    pc = c.shift(1)
    tr1 = h - l
    tr2 = (h - pc).abs()
    tr3 = (l - pc).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def atr(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    return true_range(h, l, c).rolling(n).mean()


def adx(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    """強化版 ADX：強制 1D numpy，避免 (N,1) 維度問題"""
    up = h.diff().to_numpy().reshape(-1)
    down = (-l.diff()).to_numpy().reshape(-1)

    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    plus_dm_s = pd.Series(plus_dm, index=h.index).abs()
    minus_dm_s = pd.Series(minus_dm, index=h.index).abs()

    tr = true_range(h, l, c)
    atr_v = tr.rolling(n).mean()

    plus_di = 100 * plus_dm_s.rolling(n).sum() / atr_v
    minus_di = 100 * minus_dm_s.rolling(n).sum() / atr_v

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.rolling(n).mean()


def stochastic_kd(h: pd.Series, l: pd.Series, c: pd.Series,
                  n: int = 9, k_smooth: int = 3, d_smooth: int = 3):
    ll = l.rolling(n).min()
    hh = h.rolling(n).max()
    fast_k = 100 * (c - ll) / (hh - ll)
    k = fast_k.rolling(k_smooth).mean()
    d = k.rolling(d_smooth).mean()
    return k, d


def macd(c: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    fast_ = ema(c, fast)
    slow_ = ema(c, slow)
    macd_line = fast_ - slow_
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


# ============================================================
# Telegram 推播
# ============================================================

def tg_send(message: str, cfg: Dict[str, Any]) -> None:
    token = cfg.get("telegram_token")
    chat_id = cfg.get("telegram_chat_id")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception:
        pass


def format_entry_card(code: str, m: Dict[str, Any]) -> str:
    """進場訊號卡片（Telegram HTML 格式）"""
    ema_period = int(m.get("ema_period", 117))
    inst_4w = m.get("法人4週買超", float("nan"))
    if np.isnan(inst_4w):
        inst_text = "資料不足"
    else:
        inst_text = f"{inst_4w:.0f} 張"

    lines = [
        f"🚀 <b>進場訊號：{code}</b>",
        f"📅 日期：{m['日期']}",
        f"💰 收盤：{m['收盤']:.2f}",
        f"📈 EMA{ema_period}：{m['EMA']:.2f}",
        f"🔍 KD：K={m['K值']:.2f}，D={m['D值']:.2f}",
        f"📊 ADX：{m['ADX']:.2f}",
        f"🏦 法人4週買超：{inst_text}",
        f"📤 MACD：{m['MACD']:.2f}",
        f"⭐ 綜合評分：{m.get('綜合評分(score)', 0):.3f}",
    ]
    return "\n".join(lines)


def format_exit_card(code: str, m: Dict[str, Any], reasons: List[str]) -> str:
    """出場訊號卡片（只對持股推）"""
    if not reasons:
        reason_block = "（未提供詳細原因）"
    else:
        reason_lines = []
        for r in reasons:
            cn = EXIT_REASON_MAP.get(r, r)
            reason_lines.append(f"• {cn}")
        reason_block = "\n".join(reason_lines)

    lines = [
        f"⚠️ <b>出場訊號：{code}</b>",
        f"📅 日期：{m['日期']}",
        f"💰 收盤：{m['收盤']:.2f}",
        "",
        "📌 <b>出場原因：</b>",
        reason_block,
    ]
    return "\n".join(lines)


# ============================================================
# 策略核心：進出場判斷 + 評分（含法人 A+B）
# ============================================================

def screen_and_exit(df: pd.DataFrame,
                    cfg: Dict[str, Any],
                    inst_series: Optional[pd.Series] = None):
    """
    回傳：
    - metrics: dict（會進 CSV，包含建議進/退場價 + 法人資訊）
    - entry_pass: bool 是否符合進場條件（👉 只看五個技術條件）
    - conds_map: 各條件的 True/False（cond6 只是法人資訊）
    - exit_reasons: list[str] 出場理由代碼（給回測 / 推播用）
    """
    df = df.copy()
    df = df[~df.index.duplicated(keep="last")]

    c = df["Close"]
    h = df["High"]
    l = df["Low"]
    v = df["Volume"]

    # ===== 技術指標 =====
    ema_val = ema(c, int(cfg["ema_period"]))
    vol_fast = v.rolling(int(cfg["vol_fast"])).mean()
    vol_slow = v.rolling(int(cfg["vol_slow"])).mean()
    k, d = stochastic_kd(
        h, l, c,
        int(cfg["kd_n"]), int(cfg["kd_k"]), int(cfg["kd_d"])
    )
    adxN = adx(h, l, c, int(cfg["adx_period"]))
    macd_line, sig_line, hist = macd(
        c,
        int(cfg["macd_fast"]),
        int(cfg["macd_slow"]),
        int(cfg["macd_signal"]),
    )
    ma5 = c.rolling(5).mean()
    atr_val = atr(h, l, c, int(cfg["stop_atr_period"]))
    trail_ema = ema(c, int(cfg["trail_ema_period"]))

    # ===== 尾值抽出 =====
    close_last = last_scalar(c)
    ema_last   = last_scalar(ema_val)
    vfast_last = last_scalar(vol_fast)
    vslow_last = last_scalar(vol_slow)
    k_last     = last_scalar(k)
    d_last     = last_scalar(d)
    adx_last   = last_scalar(adxN)
    macd_last  = last_scalar(macd_line)
    sig_last   = last_scalar(sig_line)
    hist_last  = last_scalar(hist)
    ma5_last   = last_scalar(ma5)
    atr_last   = last_scalar(atr_val)
    trail_last = last_scalar(trail_ema)

    latest_day = df.index[-1].date().isoformat()

    # ===== 法人 4 週淨買超（A：資訊用） =====
    inst_4w_sum = float("nan")
    if inst_series is not None:
        lookback = int(cfg.get("inst_lookback", 20))
        if len(inst_series.dropna()) >= lookback:
            inst_4w_sum = float(inst_series.rolling(lookback).sum().iloc[-1])

    # ===== 初始停損 & 建議價位 =====
    init_stop = float("nan")
    if not np.isnan(close_last) and not np.isnan(atr_last):
        init_stop = close_last - float(cfg["stop_atr_mult"]) * atr_last

    # ===== 進場條件（👉 僅五個技術條件） =====
    cond1 = close_last >= ema_last
    cond2 = vfast_last >= vslow_last
    cond3 = (
        float(cfg["kmin"]) <= k_last <= float(cfg["kmax"])
        and float(cfg["dmin"]) <= d_last <= float(cfg["dmax"])
    )
    cond4 = adx_last > float(cfg["adx_min"])
    macd_pos   = (macd_last > 0.0) if bool(cfg["macd_require_positive"]) else True
    macd_cross = (macd_last > sig_last) if bool(cfg["macd_require_cross"]) else True
    cond5 = macd_pos and macd_cross

    # cond6：法人4週是否為正，只做資訊，不影響 entry_pass
    cond6 = False
    if not np.isnan(inst_4w_sum):
        cond6 = inst_4w_sum > 0

    entry_pass = all([cond1, cond2, cond3, cond4, cond5])

    # ===== 出場條件 =====
    exit_reasons: List[str] = []

    # EMA 連續 N 天跌破
    N = int(cfg["exit_ema_break_bars"])
    if N > 0 and len(c) >= N:
        tail_c   = c.tail(N).to_numpy(dtype=float)
        tail_ema = ema_val.tail(N).to_numpy(dtype=float)
        if np.all(tail_c < tail_ema):
            exit_reasons.append("trend_break_EMA")

    # 量縮 + 跌破 MA5
    if bool(cfg["exit_volume_fade"]) and vfast_last < vslow_last and close_last < ma5_last:
        exit_reasons.append("volume_fade")

    # MACD 翻空
    if bool(cfg["exit_macd_flip"]) and (macd_last < sig_last) and (macd_last < 0.0):
        exit_reasons.append("macd_flip_down")

    # ADX 弱化
    if bool(cfg["exit_adx_weaken"]):
        if adx_last < float(cfg["exit_adx_weak_threshold"]):
            exit_reasons.append("adx_below_threshold")
        weaken_n = int(cfg["exit_adx_weak_bars"])
        if len(adxN.dropna()) >= weaken_n + 1:
            diffs = adxN.diff().dropna().tail(weaken_n).to_numpy(dtype=float)
            if len(diffs) == weaken_n and np.all(diffs < 0):
                exit_reasons.append("adx_weaken")

    # KD 高檔死亡交叉
    if bool(cfg["exit_kd_death_high"]) and len(k.dropna()) >= 2:
        k_prev = last_scalar(k.iloc[-2])
        d_prev = last_scalar(d.iloc[-2])
        if (k_prev > 80.0) and (k_prev > d_prev) and (k_last < d_last):
            exit_reasons.append("kd_death_cross_>80")

    # ===== 綜合評分（技術 + 可選法人 B） =====
    trend_ratio = close_last / ema_last if ema_last > 0 else 0.0
    vol_ratio   = vfast_last / vslow_last if vslow_last > 0 else 0.0
    adx_ratio   = adx_last / float(cfg["adx_min"]) if float(cfg["adx_min"]) > 0 else 0.0
    macd_mom    = hist_last / close_last if close_last > 0 else 0.0
    macd_mom    = max(0.0, macd_mom)

    trend_ratio = float(np.clip(trend_ratio, 0.0, 2.0))
    vol_ratio   = float(np.clip(vol_ratio,   0.0, 3.0))
    adx_ratio   = float(np.clip(adx_ratio,   0.0, 2.0))

    # B：法人強度分數（0~1），只影響排序，不影響 entry_pass
    inst_score = 0.0
    if not np.isnan(inst_4w_sum):
        norm = float(cfg.get("inst_norm", 5000.0))
        if norm > 0:
            inst_score_raw = np.tanh(inst_4w_sum / norm)
            inst_score = max(0.0, float(inst_score_raw))

    score = (
        float(cfg["score_w_trend"]) * trend_ratio +
        float(cfg["score_w_vol"])   * vol_ratio   +
        float(cfg["score_w_adx"])   * adx_ratio   +
        float(cfg["score_w_macd"])  * macd_mom    +
        float(cfg.get("score_w_inst", 0.0)) * inst_score
    )

    # ===== 組合回傳欄位 =====
    adx_col_name = f"ADX{int(cfg['adx_period'])}"
    exit_cn_list = [EXIT_REASON_MAP.get(r, r) for r in exit_reasons]

    metrics: Dict[str, Any] = {
        "日期": latest_day,
        "收盤": close_last,
        "EMA": ema_last,
        "ema_period": int(cfg["ema_period"]),
        f"{int(cfg['vol_fast'])}日均量": vfast_last,
        f"{int(cfg['vol_slow'])}日均量": vslow_last,
        "K值": k_last,
        "D值": d_last,
        adx_col_name: adx_last,
        "ADX": adx_last,
        "MACD": macd_last,
        "MACD訊號": sig_last,
        "MACD柱": hist_last,
        "初始停損價(ATR)": init_stop,
        f"建議移動停損(EMA{int(cfg['trail_ema_period'])})": trail_last,

        # 建議進 / 退場價
        "建議進場價格": close_last,   # 當天收盤價視為假設進場價
        "建議退場價格": init_stop,    # ATR 初始停損價

        # 條件結果 / 評分
        "股價高於EMA": bool(cond1),
        "成交量放大": bool(cond2),
        "KD合理區間": bool(cond3),
        "趨勢強勁": bool(cond4),
        "MACD多頭": bool(cond5),
        "法人4週買超通過": bool(cond6),   # 只做展示
        "是否符合": "符合" if entry_pass else "不符合",
        "綜合評分(score)": score,

        # 法人資訊
        "法人4週買超": inst_4w_sum,
        "法人強度分數": inst_score,

        # 出場理由
        "出場原因代碼": ";".join(exit_reasons),
        "出場原因中文": ";".join(exit_cn_list),
    }

    conds_map = {
        "cond1": cond1,
        "cond2": cond2,
        "cond3": cond3,
        "cond4": cond4,
        "cond5": cond5,
        "cond6": cond6,
    }

    return metrics, entry_pass, conds_map, exit_reasons


# ============================================================
# 回測工具（T+1 開盤價模擬，含法人）
# ============================================================

def calc_cagr(start_value: float, end_value: float, years: float) -> float:
    if start_value <= 0 or end_value <= 0 or years <= 0:
        return 0.0
    return (end_value / start_value) ** (1.0 / years) - 1.0


def run_backtest_for_code(df: pd.DataFrame,
                          cfg: Dict[str, Any],
                          inst_series: Optional[pd.Series] = None):
    """
    簡易單檔回測（T+1 開盤價模擬）：
    - 第 i 根 K 棒收盤後，根據當天指標決定「隔天開盤」是否進/出場
    - 實際成交價 = 第 i+1 天開盤價 ± 滑價
    - 回傳：
        stat: 總報酬率 / 年化報酬率 / 勝率...
        trades_detail: 每一筆交易（進出場日期 / 價格 / 損益 / 原因）
    """
    df = df.sort_index().copy()
    if df.empty:
        return {}, []

    # === 參數 ===
    initial_capital = float(cfg.get("backtest_initial_capital", 1_000_000))
    risk_pct        = float(cfg.get("backtest_risk_per_trade", 0.1))
    commission_pct  = float(cfg.get("backtest_commission_pct", 0.001))
    slippage_pct    = float(cfg.get("backtest_slippage_pct", 0.001))

    # === 狀態變數 ===
    cash        = initial_capital
    position    = 0
    entry_price = 0.0
    entry_date  = None

    equity_curve  = []
    trades_pnl    = []
    trades_detail = []

    closes = df["Close"].astype(float).to_numpy().reshape(-1)
    opens  = df["Open"].astype(float).to_numpy().reshape(-1)

    idx = list(df.index)
    n   = len(idx)

    # 因為要用「隔天開盤」，最後一天沒得交易，所以只跑到 n-2
    for i in range(50, n - 1):
        sub = df.iloc[: i + 1]          # 給策略看的歷史（含今天）
        cur_date  = idx[i]
        next_date = idx[i + 1]

        px_close_today = float(closes[i])
        px_open_next   = float(opens[i + 1])

        # 法人子序列也切到目前為止
        sub_inst = None
        if inst_series is not None:
            sub_inst = inst_series.iloc[: i + 1]

        # 更新「今天收盤」的資產淨值（只是記錄績效曲線）
        equity = cash + position * px_close_today if position > 0 else cash
        equity_curve.append(equity)

        # 用到目前為止的資料算指標 → 決定是否在「明天開盤」進 / 出場
        metrics, entry_ok, conds_map, exit_reasons = screen_and_exit(sub, cfg, sub_inst)

        # === 有部位：若今天出現出場訊號 → 明天開盤價賣出 ===
        if position > 0 and exit_reasons:
            sell_price = px_open_next * (1.0 - slippage_pct)
            gross      = sell_price * position
            fee        = gross * commission_pct
            cash      += gross - fee

            profit = gross - fee - entry_price * position
            trades_pnl.append(profit)

            trades_detail.append({
                "進場日期": entry_date.date().isoformat() if entry_date is not None else "",
                "退場日期": next_date.date().isoformat(),
                "進場價格": entry_price,
                "退場價格": sell_price,
                "股數": position,
                "毛利": gross - entry_price * position,
                "手續費": fee,
                "淨利": profit,
                "報酬率": profit / (entry_price * position) if position > 0 else 0.0,
                "出場原因": ";".join(exit_reasons),
            })

            position    = 0
            entry_price = 0.0
            entry_date  = None
            continue

        # === 無部位：若今天符合進場條件 → 明天開盤價買進 ===
        if position == 0 and entry_ok:
            alloc = cash * risk_pct
            if alloc <= 0:
                continue

            buy_price = px_open_next * (1.0 + slippage_pct)
            qty       = int(alloc // buy_price)
            if qty <= 0:
                continue

            cost       = buy_price * qty
            fee        = cost * commission_pct
            total_cost = cost + fee
            if total_cost > cash:
                continue

            cash       -= total_cost
            position    = qty
            entry_price = buy_price
            entry_date  = next_date   # 進場日 = 實際成交那天（隔天）

    # === 迴圈跑完但還有部位 → 用最後一根 K 的收盤價強制平倉 ===
    if position > 0:
        last_date  = idx[-1]
        last_close = float(closes[-1])
        sell_price = last_close * (1.0 - slippage_pct)
        gross      = sell_price * position
        fee        = gross * commission_pct
        cash      += gross - fee

        profit = gross - fee - entry_price * position
        trades_pnl.append(profit)

        trades_detail.append({
            "進場日期": entry_date.date().isoformat() if entry_date is not None else "",
            "退場日期": last_date.date().isoformat(),
            "進場價格": entry_price,
            "退場價格": sell_price,
            "股數": position,
            "毛利": gross - entry_price * position,
            "手續費": fee,
            "淨利": profit,
            "報酬率": profit / (entry_price * position) if position > 0 else 0.0,
            "出場原因": "強制平倉",
        })

        position    = 0
        entry_price = 0.0
        entry_date  = None

    # === 統計結果 ===
    final_equity = cash if not equity_curve else equity_curve[-1]
    total_return = (final_equity / initial_capital) - 1.0

    n_trades = len(trades_pnl)
    wins     = [p for p in trades_pnl if p > 0]
    losses   = [p for p in trades_pnl if p <= 0]
    win_rate = (len(wins) / n_trades) if n_trades > 0 else 0.0

    days  = (df.index[-1] - df.index[0]).days
    years = days / 365.0 if days > 0 else 0.0
    cagr  = calc_cagr(initial_capital, final_equity, years) if years > 0 else 0.0

    stat = {
        "總報酬率": total_return,
        "年化報酬率": cagr,
        "交易次數": n_trades,
        "勝率": win_rate,
        "平均獲利": float(np.mean(wins)) if wins else 0.0,
        "平均虧損": float(np.mean(losses)) if losses else 0.0,
        "期初資金": initial_capital,
        "期末資金": final_equity,
    }

    return stat, trades_detail


# ============================================================
# 設定檔載入
# ============================================================

def load_config(path: Optional[str]) -> Dict[str, Any]:
    cfg = dict(DEFAULT_CFG)
    if not path:
        return cfg
    text = open(path, "r", encoding="utf-8").read()
    try:
        if HAS_YAML and path.lower().endswith((".yml", ".yaml")):
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
        if isinstance(data, dict):
            cfg.update(data)
    except Exception as e:
        print(f"[警告] 無法解析設定檔 {path}：{e}（使用預設＋部分覆寫）")
    return cfg


# ============================================================
# main
# ============================================================

def main():
    import argparse

    ap = argparse.ArgumentParser(description="小壞蛋台股終極策略 tw_stock_pipeline.py")

    ap.add_argument("--start", type=str, default="2023-01-01")
    ap.add_argument("--end", type=str, default=dt.date.today().isoformat())
    ap.add_argument("--config", type=str, default="config.yaml")
    ap.add_argument("--out", type=str, default="tw_screen_results.csv")
    ap.add_argument("--report_all", action="store_true",
                    help="輸出全市場當日指標報表 tw_all_results.csv")
    ap.add_argument("--codes", type=str,
                    help="只掃這些股票，逗號分隔，例如：2330.TW,2603.TW,5483.TWO")
    # 回測
    ap.add_argument("--backtest_codes", type=str,
                    help="只對這些代碼做回測，逗號分隔，例如：2330.TW,2603.TW")
    ap.add_argument("--backtest_out", type=str, default="backtest_results.csv")

    args = ap.parse_args()

    cfg = load_config(args.config)
    held_roots = load_held_stocks()

    # 讀法人資料（檔案不存在就自動抓 T86）
    inst_df: Optional[pd.DataFrame] = None
    inst_path = cfg.get("inst_flow_file", "inst_flow.csv")

    if not os.path.exists(inst_path):
        print(f"⚠ 找不到 {inst_path}，自動從 TWSE 抓取三大法人資料產生…")
        build_inst_flow(args.start, args.end, inst_path)

    inst_df = load_inst_data(inst_path)
    if inst_df is None:
        print("⚠ 無法載入法人資料，將只使用技術面條件與評分")
        cfg["score_w_inst"] = 0.0

    # 準備股票清單
    if args.codes:
        codes = []
        for part in args.codes.split(","):
            s = part.strip().upper()
            if not s:
                continue
            if s.endswith(".TW") or s.endswith(".TWO"):
                codes.append(s)
            elif s.isdigit():
                codes.append(f"{s}.TW")
        codes = sorted(set(codes))
    else:
        codes = load_all_tw_codes()

    print(f"📌 本次處理股票數量：{len(codes)}")

    passed_rows = []
    all_rows = []

    for code in codes:
        print(f"\n=== 處理 {code} ===")
        df = load_price(code, args.start, args.end)
        if df is None or df.empty:
            print(f"❌ 無法取得 {code} 價格資料，已加入黑名單或略過")
            continue

        inst_series = get_inst_series_for_code(inst_df, code, df.index)

        metrics, entry_pass, conds_map, exit_reasons = screen_and_exit(df, cfg, inst_series)
        row = {"代碼": code, **metrics}
        all_rows.append(row)

        # 進場結果印出
        if entry_pass:
            passed_rows.append(row)
            print(f"✅ 符合：{code}（score={metrics['綜合評分(score)']:.3f}）")
        else:
            # 只列出沒過的五個技術條件（法人只做參考）
            failed = [
                name
                for k, name in CN_COND_NAMES.items()
                if k in ("cond1", "cond2", "cond3", "cond4", "cond5")
                and not conds_map.get(k, True)
            ]
            if failed:
                print(f"❌ 不符合：{code}（未過：{', '.join(failed)}）")
            else:
                print(f"❌ 不符合：{code}")

        # Telegram 進場推播
        if entry_pass and cfg.get("notify_on_entry") and cfg.get("telegram_token") and cfg.get("telegram_chat_id"):
            msg = format_entry_card(code, metrics)
            tg_send(msg, cfg)

        # Telegram 出場推播（只對持股清單內的代碼）
        if exit_reasons and cfg.get("notify_on_exit") and cfg.get("telegram_token") and cfg.get("telegram_chat_id"):
            m = re.match(r"(\d+)", code)
            root = m.group(1) if m else ""
            if root and root in held_roots:
                msg = format_exit_card(code, metrics, exit_reasons)
                tg_send(msg, cfg)

    # ===== 結果輸出 =====
    if passed_rows:
        df_pass = pd.DataFrame(passed_rows)
        df_pass = df_pass.sort_values(["日期", "綜合評分(score)"], ascending=[True, False])
        df_pass.to_csv(args.out, index=False, encoding="utf-8-sig")
        print(f"\n🎉 已輸出符合進場清單 → {args.out}")
    else:
        print("\n⚠ 目前無符合此門檻之標的。")

    if args.report_all and all_rows:
        df_all = pd.DataFrame(all_rows)
        df_all.to_csv("tw_all_results.csv", index=False, encoding="utf-8-sig")
        print("📄 已輸出全市場完整報表 → tw_all_results.csv")

    # ===== 回測流程（選用） =====
    if cfg.get("enable_backtest", False) and args.backtest_codes:
        bt_codes = [c.strip().upper() for c in args.backtest_codes.split(",") if c.strip()]
        bt_rows: List[Dict[str, Any]] = []
        all_trades: List[Dict[str, Any]] = []

        print(f"\n📊 開始回測（共 {len(bt_codes)} 檔）：{', '.join(bt_codes)}")

        for code in bt_codes:
            print(f"  ▶ 回測 {code} ...")
            df_bt = load_price(code, args.start, args.end)
            if df_bt is None or df_bt.empty:
                print(f"    ⚠ 無法取得 {code} 資料，略過")
                continue

            inst_series_bt = get_inst_series_for_code(inst_df, code, df_bt.index)

            stat, trades_detail = run_backtest_for_code(df_bt, cfg, inst_series_bt)
            if not stat:
                print(f"    ⚠ {code} 無法計算回測結果，略過")
                continue

            # 彙總結果
            row = {"代碼": code}
            row.update(stat)
            bt_rows.append(row)

            # 單筆交易明細
            for t in trades_detail:
                t_row = {"代碼": code}
                t_row.update(t)
                all_trades.append(t_row)

        # 輸出每一筆交易明細
        if all_trades:
            df_trades = pd.DataFrame(all_trades)
            df_trades.to_csv("backtest_trades_detail.csv", index=False, encoding="utf-8-sig")
            print("✅ 已輸出每一筆交易明細 → backtest_trades_detail.csv")
        else:
            print("⚠ 沒有任何交易紀錄可輸出（可能完全沒觸發進出場條件）")

        # 輸出每檔回測摘要
        if bt_rows:
            df_bt = pd.DataFrame(bt_rows)
            df_bt["總報酬率(%)"] = df_bt["總報酬率"] * 100
            df_bt["年化報酬率(%)"] = df_bt["年化報酬率"] * 100
            df_bt["勝率(%)"] = df_bt["勝率"] * 100
            df_bt.to_csv(args.backtest_out, index=False, encoding="utf-8-sig")
            print(f"✅ 回測結果已輸出：{args.backtest_out}")
        else:
            print("⚠ 沒有可用的回測結果（bt_rows 為空）")

if __name__ == "__main__":
    main()
