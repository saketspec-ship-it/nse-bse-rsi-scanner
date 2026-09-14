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
WINDOW = {"1D": 500, "1W": 300, "1M": 120}   # bars kept per timeframe for charts


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


def build_sector_indices(cfg, results, frames, min_mcap_cr: float = 2000.0) -> dict:
    """Return the sector-index bundle for the dashboard's page 2."""
    wrule = cfg.get("candles", "weekly_rule", default="W-FRI")
    mrule = cfg.get("candles", "monthly_rule", default="ME")

    # Group qualifying constituents by sector.
    groups: dict[str, list[tuple[str, float]]] = {}
    mcaps: dict[str, float] = {}
    for r in results:
        if not r.sector or r.sector == "Unknown":
            continue
        if not r.market_cap_cr or r.market_cap_cr < min_mcap_cr:
            continue
        if not r.yahoo_ticker:
            continue
        groups.setdefault(r.sector, []).append((r.yahoo_ticker, r.market_cap_cr))
        mcaps[r.sector] = mcaps.get(r.sector, 0.0) + r.market_cap_cr

    sectors_out = {}
    for sector, cons in groups.items():
        daily = _index_daily_ohlc(frames, cons)
        if daily is None or len(daily) < 60:
            continue

        tf = {}
        latest_close = None
        for name, candles in (("1D", daily),
                              ("1W", resample_ohlc(daily, wrule)),
                              ("1M", resample_ohlc(daily, mrule))):
            if len(candles) < 15:
                continue
            cutoff = WINDOW.get(name, 400)
            trimmed = candles.tail(cutoff)
            # RSI/MA computed on the FULL series then trimmed, so warm-up is correct.
            full = _indicators(candles)
            keep = len(trimmed)
            tf[name] = {k: (v[-keep:] if isinstance(v, list) else v) for k, v in full.items()}
            if name == "1D":
                latest_close = candles["Close"]

        if "1D" not in tf:
            continue

        def rsi_last(name):
            arr = tf.get(name, {}).get("rsi") or []
            for v in reversed(arr):
                if v is not None:
                    return v
            return None

        sectors_out[sector] = {
            "constituents": len(cons),
            "mcap_cr": round(mcaps[sector], 0),
            "summary": {
                "level": round(float(latest_close.iloc[-1]), 2),
                "chg_1d": _pct(latest_close, 1),
                "chg_1w": _pct(latest_close, 5),
                "chg_1m": _pct(latest_close, 21),
                "rsi_1d": rsi_last("1D"),
                "rsi_1w": rsi_last("1W"),
                "rsi_1m": rsi_last("1M"),
            },
            "tf": tf,
        }

    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "min_mcap_cr": min_mcap_cr,
        "ma_periods": MA_PERIODS,
        "bb": [BB_PERIOD, BB_K],
        "sectors": sectors_out,
    }
