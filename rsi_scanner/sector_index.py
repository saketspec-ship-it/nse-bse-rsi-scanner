"""Build synthetic sector indices from constituent stocks.

Universe for an index: stocks with market cap >= ``min_mcap_cr`` (default
₹2,000 Cr) and a KNOWN sector. The index is market-cap weighted and rebased to
100, constructed from daily returns (cap-weighted average of constituent daily
returns, weights renormalised each day over the names that have data), so
constituents with different history lengths compose cleanly without look-ahead.

For each index we emit 1D / 1W / 1M candles plus indicators computed on that
timeframe's closes: RSI(14), SMA(7,21,50,220 bars) and Bollinger Bands(20,2).
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from .rsi_engine import resample_ohlc, wilder_rsi

MA_PERIODS = [7, 21, 50, 220]
BB_PERIOD = 20
BB_K = 2.0
MIN_CONSTITUENTS = 3
WINDOW = {"1D": 320, "1W": 200, "1M": 110}   # bars kept per timeframe for charts

# Cap tiers used to slice each index (Micro < 2,000 Cr is below the index floor).
CAP_TIERS = ["All", "Large", "Mid", "Small"]


def cap_tier(mcap_cr: float) -> str | None:
    if mcap_cr >= 20000:
        return "Large"
    if mcap_cr >= 5000:
        return "Mid"
    if mcap_cr >= 2000:
        return "Small"
    return None


def _round_list(s: pd.Series, nd: int = 2) -> list:
    return [None if pd.isna(v) else round(float(v), nd) for v in s]


def _index_daily_ohlc(frames: dict, constituents: list[tuple[str, float]]) -> pd.DataFrame | None:
    """Cap-weighted rebased daily OHLC index for one sector.

    ``constituents``: list of (yahoo_ticker, market_cap_cr). Returns a daily
    OHLC frame (index level, base 100) or None if too few usable series.
    """
    closes, weights = {}, {}
    intraday = {}  # ticker -> DataFrame of open/high/low relative to close
    for tkr, mcap in constituents:
        df = frames.get(tkr)
        if df is None or df.empty or "Close" not in df:
            continue
        c = df["Close"].astype("float64")
        c = c[c > 0]
        if len(c) < 60:
            continue
        closes[tkr] = c
        weights[tkr] = float(mcap)
        if {"Open", "High", "Low"}.issubset(df.columns):
            intraday[tkr] = df[["Open", "High", "Low", "Close"]].astype("float64")

    if len(closes) < MIN_CONSTITUENTS:
        return None

    close_mat = pd.DataFrame(closes).sort_index()
    rets = close_mat.pct_change()
    w = pd.Series(weights)

    # Cap-weighted daily return: renormalise weights over names present each day.
    mask = rets.notna()
    wmat = mask.mul(w, axis=1)
    wsum = wmat.sum(axis=1)
    idx_ret = (rets.mul(w, axis=1).where(mask).sum(axis=1)) / wsum.replace(0, np.nan)
    idx_ret = idx_ret.fillna(0.0)
    level = 100.0 * (1.0 + idx_ret).cumprod()

    # Daily OHLC for the index: scale the close level by the cap-weighted
    # intraday open/high/low-to-close ratios so daily candles are meaningful.
    def wavg_ratio(field: str) -> pd.Series:
        parts = {}
        for tkr, df in intraday.items():
            r = (df[field] / df["Close"]).replace([np.inf, -np.inf], np.nan)
            parts[tkr] = r
        if not parts:
            return pd.Series(1.0, index=level.index)
        rmat = pd.DataFrame(parts).reindex(level.index)
        m = rmat.notna()
        wm = m.mul(w[rmat.columns], axis=1)
        return (rmat.mul(w[rmat.columns], axis=1).where(m).sum(axis=1) / wm.sum(axis=1).replace(0, np.nan)).fillna(1.0)

    out = pd.DataFrame(index=level.index)
    out["Close"] = level
    out["Open"] = level * wavg_ratio("Open")
    out["High"] = level * wavg_ratio("High")
    out["Low"] = level * wavg_ratio("Low")
    # Guard: high>=max(o,c), low<=min(o,c)
    out["High"] = out[["High", "Open", "Close"]].max(axis=1)
    out["Low"] = out[["Low", "Open", "Close"]].min(axis=1)
    return out.dropna(subset=["Close"])


def _indicators(candles: pd.DataFrame) -> dict:
    close = candles["Close"]
    data = {
        "dates": [d.strftime("%Y-%m-%d") for d in candles.index],
        "o": _round_list(candles["Open"]),
        "h": _round_list(candles["High"]),
        "l": _round_list(candles["Low"]),
        "c": _round_list(close),
        "rsi": _round_list(wilder_rsi(close, 14), 2),
    }
    for p in MA_PERIODS:
        data[f"ma{p}"] = _round_list(close.rolling(p).mean())
    mid = close.rolling(BB_PERIOD).mean()
    sd = close.rolling(BB_PERIOD).std()
    data["bb_up"] = _round_list(mid + BB_K * sd)
    data["bb_low"] = _round_list(mid - BB_K * sd)
    return data


def _pct(series: pd.Series, n: int) -> float | None:
    s = series.dropna()
    if len(s) <= n:
        return None
    return round((s.iloc[-1] / s.iloc[-1 - n] - 1) * 100, 2)


def _build_one(cfg, frames, constituents: list[tuple[str, float]]) -> dict | None:
    """Build one index (constituents = list of (ticker, mcap_cr))."""
    wrule = cfg.get("candles", "weekly_rule", default="W-FRI")
    mrule = cfg.get("candles", "monthly_rule", default="ME")
    daily = _index_daily_ohlc(frames, [(t, m) for t, m in constituents])
    if daily is None or len(daily) < 60:
        return None

    tf, latest_close = {}, None
    for name, candles in (("1D", daily),
                          ("1W", resample_ohlc(daily, wrule)),
                          ("1M", resample_ohlc(daily, mrule))):
        if len(candles) < 15:
            continue
        full = _indicators(candles)
        keep = min(len(candles), WINDOW.get(name, 300))
        tf[name] = {k: (v[-keep:] if isinstance(v, list) else v) for k, v in full.items()}
        if name == "1D":
            latest_close = candles["Close"]
    if "1D" not in tf:
        return None

    def rsi_last(nm):
        for v in reversed(tf.get(nm, {}).get("rsi") or []):
            if v is not None:
                return v
        return None

    return {
        "constituents": len(constituents),
        "mcap_cr": round(sum(m for _, m in constituents), 0),
        "summary": {
            "level": round(float(latest_close.iloc[-1]), 2),
            "chg_1d": _pct(latest_close, 1),
            "chg_1w": _pct(latest_close, 5),
            "chg_1m": _pct(latest_close, 21),
            "rsi_1d": rsi_last("1D"), "rsi_1w": rsi_last("1W"), "rsi_1m": rsi_last("1M"),
        },
        "tf": tf,
    }


def build_indices(cfg, results, frames, group_field: str,
                  min_mcap_cr: float = 2000.0, max_groups: int = 0) -> dict:
    """Build cap-tiered indices grouped by ``group_field`` ('sector'/'industry').

    Each group carries per-cap-tier sub-indices ("All"/"Large"/"Mid"/"Small";
    only tiers with >= MIN_CONSTITUENTS constituents are kept).
    """
    groups: dict[str, list[tuple[str, float]]] = {}
    for r in results:
        val = getattr(r, group_field, None)
        if not val or val == "Unknown":
            continue
        if not r.market_cap_cr or r.market_cap_cr < min_mcap_cr or not r.yahoo_ticker:
            continue
        groups.setdefault(val, []).append((r.yahoo_ticker, float(r.market_cap_cr)))

    # Optionally keep only the largest groups (keeps industries.json bounded).
    if max_groups and len(groups) > max_groups:
        ranked = sorted(groups.items(), key=lambda kv: -sum(m for _, m in kv[1]))
        groups = dict(ranked[:max_groups])

    out: dict[str, dict] = {}
    for name, cons in groups.items():
        tiers_out = {}
        for tier in CAP_TIERS:
            if tier == "All":
                sub = cons
            else:
                sub = [(t, m) for t, m in cons if cap_tier(m) == tier]
            if len(sub) < MIN_CONSTITUENTS:
                continue
            built = _build_one(cfg, frames, sub)
            if built:
                tiers_out[tier] = built
        if tiers_out:
            out[name] = tiers_out

    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "min_mcap_cr": min_mcap_cr,
        "ma_periods": MA_PERIODS,
        "bb": [BB_PERIOD, BB_K],
        "group_field": group_field,
        "tiers": CAP_TIERS,
        "groups": out,
    }


def build_sector_indices(cfg, results, frames, min_mcap_cr: float = 2000.0) -> dict:
    """Back-compat wrapper: sector-grouped indices."""
    return build_indices(cfg, results, frames, "sector", min_mcap_cr)
