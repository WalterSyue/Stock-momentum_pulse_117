
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tw_stock_pipeline_param.py
Taiwan stock screener pipeline (parameterized)
- Supports CLI and --config (YAML/JSON) to customize thresholds.
"""
import argparse, os, sys, time, csv, math, io, re, datetime as dt, json
from typing import List, Optional, Dict, Any
import numpy as np
import pandas as pd

# deps
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
    if missing:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing, "-q"])
_ensure_pkgs()
import requests  # type: ignore
import yfinance as yf  # type: ignore

try:
    import yaml  # type: ignore
    HAS_YAML = True
except Exception:
    HAS_YAML = False

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/company_basic_info"
UA = {"User-Agent": "Mozilla/5.0 (compatible; tw-stock-pipeline/param/1.0)"}

CN_COND_NAMES = {
    "cond1": "股價高於EMA",
    "cond2": "成交量放大",
    "cond3": "KD合理區間",
    "cond4": "趨勢強勁",
    "cond5": "MACD多頭",
}

def save_text(path: str, content: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def fetch(url: str, tries: int = 4) -> Optional[requests.Response]:
    s = requests.Session()
    for _ in range(tries):
        try:
            r = s.get(url, headers=UA, timeout=30, params={"_": int(time.time()*1000)})
            if r.status_code == 200 and r.content:
                return r
        except Exception:
            pass
        time.sleep(0.6)
    return None

def parse_json_or_none(text: str):
    t = text.lstrip("\ufeff").strip()
    try:
        return json.loads(t)
    except Exception:
        return None

def last_scalar(x) -> float:
    try:
        if isinstance(x, pd.Series):
            val = x.iloc[-1]
        elif isinstance(x, (list, tuple, np.ndarray)):
            if len(x) == 0: return float("nan")
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

def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def true_range(h: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    pc = c.shift(1)
    tr1 = h - l
    tr2 = (h - pc).abs()
    tr3 = (l - pc).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

def adx(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    up = h.diff().to_numpy().reshape(-1)
    down = (-l.diff()).to_numpy().reshape(-1)
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_dm_s = pd.Series(plus_dm, index=h.index).abs()
    minus_dm_s = pd.Series(minus_dm, index=h.index).abs()
    tr = true_range(h, l, c)
    atr = tr.rolling(n).mean()
    plus_di = 100 * plus_dm_s.rolling(n).sum() / atr
    minus_di = 100 * minus_dm_s.rolling(n).sum() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.rolling(n).mean()

def stochastic_kd(h: pd.Series, l: pd.Series, c: pd.Series,
                  n: int = 9, k_smooth: int = 3, d_smooth: int = 3):
    ll = l.rolling(n).min(); hh = h.rolling(n).max()
    fast_k = 100 * (c - ll) / (hh - ll)
    k = fast_k.rolling(k_smooth).mean()
    d = k.rolling(d_smooth).mean()
    return k, d

def macd(c: pd.Series, fast=12, slow=26, signal=9):
    fast_ = ema(c, fast); slow_ = ema(c, slow)
    macd_line = fast_ - slow_
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def fetch_twse_csv(out_csv="twse.csv") -> str:
    r = fetch(TWSE_URL)
    if not r:
        raise RuntimeError("TWSE 下載失敗")
    data = parse_json_or_none(r.text)
    rows = []
    if isinstance(data, list):
        for row in data:
            code = str(row.get("公司代號") or row.get("Code") or "").strip()
            name = str(row.get("公司名稱") or row.get("Name") or "").strip()
            if code: rows.append((code, name, "TWSE"))
    else:
        try:
            df = pd.read_csv(io.StringIO(r.text), dtype=str)
            for _, rr in df.iterrows():
                code = str(rr.get("公司代號") or "").strip()
                name = str(rr.get("公司名稱") or "").strip()
                if code: rows.append((code, name, "TWSE"))
        except Exception:
            pass
    if not rows:
        raise RuntimeError("TWSE 解析失敗")
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["公司代號","公司名稱","市場別"]); w.writerows(rows)
    return out_csv

def _parse_tpex_from_text(text: str):
    rows = []
    for m in re.finditer(r'"code"\s*:\s*"(?P<code>\d{4,6})".{0,200}?"companyName"\s*:\s*"(?P<name>[^"]+)"', text, re.S):
        rows.append((m.group("code"), m.group("name").strip()))
    if rows: return rows
    for m in re.finditer(r'>(?P<code>\d{4,6})<[^<]{0,240}>(?P<name>[^<]{2,60})<', text, re.S):
        rows.append((m.group("code"), m.group("name").strip()))
    if rows: return rows
    codes = sorted(set(re.findall(r'\b(\d{4,6})\b', text)))
    return [(c, "") for c in codes]

def fetch_tpex_csv(out_csv="tpex.csv") -> str:
    r = fetch(TPEX_URL)
    rows = []
    raw_path = None
    if r and r.status_code == 200 and r.text:
        data = parse_json_or_none(r.text)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            for row in data:
                code = str(row.get("code") or "").strip()
                name = str(row.get("companyName") or "").strip()
                if code: rows.append((code, name))
        if not rows:
            raw_path = f"raw_tpex_{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
            save_text(raw_path, r.text)
            rows = _parse_tpex_from_text(r.text)
    else:
        raw_path = f"raw_tpex_{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        save_text(raw_path, (r.text if r else ""))

    if not rows and raw_path:
        try:
            txt = open(raw_path, "r", encoding="utf-8", errors="ignore").read()
            rows = _parse_tpex_from_text(txt)
        except Exception:
            pass

    if not rows:
        raise RuntimeError("TPEx 解析失敗（已存 raw，可手動轉）")

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["公司代號","公司名稱","市場別"])
        for code, name in rows:
            w.writerow([code, name, "TPEx"])
    return out_csv

def load_from_csvs(paths: List[str]) -> List[str]:
    symbols = []
    for p in paths:
        name = os.path.basename(p).lower()
        default_suffix = ".TW" if ("twse" in name or "listed" in name) else (".TWO" if ("tpex" in name or "otc" in name) else ".TW")
        with open(p, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            cols = [c.strip() for c in (reader.fieldnames or [])]
            code_key = next((c for c in cols if c.lower() in ("code","公司代號","證券代號","stock_code")), None)
            market_key = next((c for c in cols if c.lower() in ("market","市場別","mkt")), None)
            for r in reader:
                code = (r.get(code_key) or "").strip() if code_key else ""
                if not code: continue
                if market_key and r.get(market_key):
                    m = (r.get(market_key) or "").lower()
                    if ("上市" in m) or ("twse" in m) or ("tse" in m):
                        suffix = ".TW"
                    elif ("上櫃" in m) or ("tpex" in m) or ("otc" in m):
                        suffix = ".TWO"
                    else:
                        suffix = default_suffix
                else:
                    suffix = default_suffix
                symbols.append(f"{code}{suffix}")
    return sorted(set(symbols))

def load_codes_from_file(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]

def normalize_codes(codes: List[str], market: Optional[str]) -> List[str]:
    out = []
    for c in codes:
        c = c.strip().upper()
        if not c: continue
        if c.endswith(".TW") or c.endswith(".TWO"):
            out.append(c)
        else:
            suffix = ".TW" if (market or "TW").upper() == "TW" else ".TWO"
            out.append(f"{c}{suffix}")
    return sorted(set(out))

def _fix_tz(df: pd.DataFrame) -> pd.DataFrame:
    if getattr(df.index, "tz", None) is not None:
        df = df.tz_localize(None)
    return df.dropna()

def dl_yf(code: str, start: str, end: str):
    try:
        df = yf.download(code, start=start, end=end, progress=False, auto_adjust=False, threads=False)
        if df is not None and not df.empty:
            return _fix_tz(df)
    except Exception:
        pass
    for period in ["max", "5y", "2y"]:
        try:
            df = yf.download(code, period=period, interval="1d", progress=False, auto_adjust=False, threads=False)
            if df is not None and not df.empty:
                df = _fix_tz(df)
                try:
                    s = pd.to_datetime(start); e = pd.to_datetime(end)
                    df = df.loc[(df.index >= s) & (df.index <= e)]
                except Exception:
                    pass
                if not df.empty:
                    return df
        except Exception:
            time.sleep(0.3)
            continue
    return None

DEFAULT_CFG = {
    "ema_period": 117,
    "vol_fast": 5, "vol_slow": 10,
    "kd_n": 9, "kd_k": 3, "kd_d": 3,
    "kmin": 20.0, "kmax": 80.0, "dmin": 20.0, "dmax": 80.0,
    "adx_period": 14, "adx_min": 33.0,
    "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
    "macd_require_positive": True, "macd_require_cross": True,
}

def screen_and_exit(df: pd.DataFrame, cfg: Dict[str, Any]) -> Dict[str, Any]:
    df = df[~df.index.duplicated(keep="last")]
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    ema_n_val = ema(c, int(cfg["ema_period"]))
    vol_fast = v.rolling(int(cfg["vol_fast"])).mean()
    vol_slow = v.rolling(int(cfg["vol_slow"])).mean()
    k, d = stochastic_kd(h, l, c, int(cfg["kd_n"]), int(cfg["kd_k"]), int(cfg["kd_d"]))
    adxN = adx(h, l, c, int(cfg["adx_period"]))
    macd_line, signal_line, hist = macd(c, int(cfg["macd_fast"]), int(cfg["macd_slow"]), int(cfg["macd_signal"]))
    ma5 = c.rolling(5).mean()

    close_last = last_scalar(c)
    ema_last   = last_scalar(ema_n_val)
    vfast_last = last_scalar(vol_fast)
    vslow_last = last_scalar(vol_slow)
    k_last     = last_scalar(k)
    d_last     = last_scalar(d)
    adx_last   = last_scalar(adxN)
    macd_last  = last_scalar(macd_line)
    sig_last   = last_scalar(signal_line)
    hist_last  = last_scalar(hist)
    ma5_last   = last_scalar(ma5)

    latest = df.index[-1]
    metrics = {
        "日期": latest.date().isoformat(),
        "收盤": close_last, "EMA": ema_last,
        f"{int(cfg['vol_fast'])}日均量": vfast_last, f"{int(cfg['vol_slow'])}日均量": vslow_last,
        "K值": k_last, "D值": d_last, f"ADX{int(cfg['adx_period'])}": adx_last,
        "MACD": macd_last, "MACD訊號": sig_last, "MACD柱": hist_last,
    }

    cond1 = close_last >= ema_last
    cond2 = (vfast_last >= vslow_last)
    cond3 = (float(cfg["kmin"]) <= k_last <= float(cfg["kmax"])) and (float(cfg["dmin"]) <= d_last <= float(cfg["dmax"]))
    cond4 = adx_last > float(cfg["adx_min"])
    macd_pos = (macd_last > 0.0) if bool(cfg["macd_require_positive"]) else True
    macd_cross = (macd_last > sig_last) if bool(cfg["macd_require_cross"]) else True
    cond5 = macd_pos and macd_cross
    entry_pass = all([cond1, cond2, cond3, cond4, cond5])

    exit_reasons = []
    if len(c) >= 2:
        prev_close = last_scalar(c.iloc[-2:])
        prev_ema   = last_scalar(ema_n_val.iloc[-2:])
        if (prev_close < prev_ema) and (close_last < ema_last):
            exit_reasons.append("trend_break_EMA")
    if (vfast_last < vslow_last) and (close_last < ma5_last):
        exit_reasons.append("volume_fade")
    if (macd_last < sig_last) and (macd_last < 0.0):
        exit_reasons.append("macd_flip_down")
    adx_weaken3 = False
    if len(adxN.dropna()) >= 4:
        tail = adxN.diff().tail(3).values
        adx_weaken3 = np.all(tail < 0)
    if (adx_last < 25.0) or adx_weaken3:
        exit_reasons.append("adx_weaken")
    if len(k.dropna()) >= 2:
        k_prev = last_scalar(k.iloc[-2:])
        d_prev = last_scalar(d.iloc[-2:])
        if (k_prev > 80.0) and (k_prev > d_prev) and (k_last < d_last):
            exit_reasons.append("kd_death_cross_>80")

    result = {
        **metrics,
        "股價高於EMA": bool(cond1),
        "成交量放大": bool(cond2),
        "KD合理區間": bool(cond3),
        "趨勢強勁": bool(cond4),
        "MACD多頭": bool(cond5),
        "是否符合": "符合" if entry_pass else "不符合",
        "出場原因": ";".join(exit_reasons) if exit_reasons else "",
    }
    return result, entry_pass, {"cond1":cond1,"cond2":cond2,"cond3":cond3,"cond4":cond4,"cond5":cond5}

def load_config(path: Optional[str]) -> Dict[str, Any]:
    cfg = dict(DEFAULT_CFG)
    if not path:
        return cfg
    text = open(path, "r", encoding="utf-8").read()
    try:
        if HAS_YAML and path.lower().endswith((".yml",".yaml")):
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
        if isinstance(data, dict):
            cfg.update(data)
    except Exception as e:
        print(f"[警告] 無法解析設定檔 {path}：{e}（改用預設）")
    return cfg

def apply_cli_overrides(cfg: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    mappings = {
        "ema": "ema_period",
        "adx": "adx_min",
        "adx_period": "adx_period",
        "vol_fast": "vol_fast",
        "vol_slow": "vol_slow",
        "kd_n": "kd_n",
        "kd_k": "kd_k",
        "kd_d": "kd_d",
        "kmin": "kmin",
        "kmax": "kmax",
        "dmin": "dmin",
        "dmax": "dmax",
        "macd_fast": "macd_fast",
        "macd_slow": "macd_slow",
        "macd_signal": "macd_signal",
        "macd_pos": "macd_require_positive",
        "macd_cross": "macd_require_cross",
    }
    for cli_key, cfg_key in mappings.items():
        val = getattr(args, cli_key, None)
        if val is not None:
            cfg[cfg_key] = val
    return cfg

def main():
    ap = argparse.ArgumentParser(description="TW stock pipeline (parameterized)")
    ap.add_argument("--skip_fetch", action="store_true")
    ap.add_argument("--from_csv", nargs="+")
    ap.add_argument("--tickers", type=str)
    ap.add_argument("--codes", type=str)
    ap.add_argument("--market", type=str, choices=["TW","TWO"])
    ap.add_argument("--start", type=str, default="2023-01-01")
    ap.add_argument("--end", type=str, default=dt.date.today().isoformat())
    ap.add_argument("--out", type=str, default="tw_screen_results.csv")
    ap.add_argument("--report_all", action="store_true")
    ap.add_argument("--config", type=str)

    ap.add_argument("--ema", type=int)
    ap.add_argument("--adx", type=float)
    ap.add_argument("--adx_period", type=int)
    ap.add_argument("--vol_fast", type=int)
    ap.add_argument("--vol_slow", type=int)
    ap.add_argument("--kd_n", type=int)
    ap.add_argument("--kd_k", type=int)
    ap.add_argument("--kd_d", type=int)
    ap.add_argument("--kmin", type=float)
    ap.add_argument("--kmax", type=float)
    ap.add_argument("--dmin", type=float)
    ap.add_argument("--dmax", type=float)
    ap.add_argument("--macd_fast", type=int)
    ap.add_argument("--macd_slow", type=int)
    ap.add_argument("--macd_signal", type=int)
    ap.add_argument("--macd_pos", type=lambda x: x.lower() in ("1","true","yes","y"))
    ap.add_argument("--macd_cross", type=lambda x: x.lower() in ("1","true","yes","y"))

    args = ap.parse_args()

    if not args.skip_fetch and not args.from_csv and not args.tickers and not args.codes:
        try:
            p = fetch_twse_csv("twse.csv"); print(f"[TWSE] -> {p}")
        except Exception as e:
            print(f"[警告] TWSE 抓取失敗：{e}")
        try:
            p = fetch_tpex_csv("tpex.csv"); print(f"[TPEx] -> {p}")
        except Exception as e:
            print(f"[警告] TPEx 抓取失敗：{e}")

    codes: List[str] = []
    if args.from_csv:
        codes += load_from_csvs(args.from_csv)
    else:
        paths = [p for p in ["twse.csv","tpex.csv"] if os.path.exists(p)]
        if paths:
            codes += load_from_csvs(paths)
    if args.tickers and os.path.exists(args.tickers):
        codes += load_codes_from_file(args.tickers)
    if args.codes:
        codes += [x.strip() for x in args.codes.split(",") if x.strip()]

    if not codes:
        print("沒有代碼可用；請提供來源或不要 --skip_fetch。", file=sys.stderr)
        sys.exit(2)

    if args.codes and not any(x.endswith(".TW") or x.endswith(".TWO") for x in codes):
        norm = normalize_codes(codes, args.market)
    else:
        tmp = []
        for c in codes:
            c2 = c.strip().upper()
            if c2.endswith(".TW") or c2.endswith(".TWO"):
                tmp.append(c2)
            elif c2.isdigit():
                tmp.append(f"{c2}.TW")
        norm = sorted(set(tmp))

    cfg = load_config(args.config)
    cfg = apply_cli_overrides(cfg, args)

    passed, all_rows, errors = [], [], []
    for sym in norm:
        df = dl_yf(sym, args.start, args.end)
        if df is None or df.empty:
            errors.append(sym)
            if args.report_all:
                all_rows.append({"代碼": sym, "是否符合": "下載失敗"})
            print(f"❌ 不符合：{sym}（原因：資料下載失敗）")
            continue
        res, entry_pass, conds_map = screen_and_exit(df, cfg)
        row = {"代碼": sym, **res}
        all_rows.append(row)
        if entry_pass:
            passed.append(row); print(f"✅ 符合：{sym}")
        else:
            failed = [CN_COND_NAMES[k] for k,v in conds_map.items() if not v]
            print(f"❌ 不符合：{sym}（未過條件：{', '.join(failed)}）")

    if passed:
        pd.DataFrame(passed).sort_values(["日期","代碼"]).to_csv(args.out, index=False, encoding="utf-8-sig")
        print(f"已輸出符合清單 -> {args.out}")
    else:
        print("目前無符合此門檻之標的。")

    if args.report_all:
        pd.DataFrame(all_rows).to_csv("tw_screen_report_all.csv", index=False, encoding="utf-8-sig")
        print("已輸出完整報表 -> tw_screen_report_all.csv")

    if errors:
        print(f"{len(errors)} 檔下載失敗：{', '.join(errors[:20])}" + (" ..." if len(errors)>20 else ""))

if __name__ == "__main__":
    main()
