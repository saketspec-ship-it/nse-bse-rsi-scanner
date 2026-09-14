"""Historical backtest of the RSI signal (spec sections 13 & 22).

For each security, the daily/weekly/monthly RSI is reconstructed through
history with NO look-ahead: on any daily date d the weekly and monthly RSI
reflect only candles that had CLOSED strictly before d (availability shifted to
the next trading day). Signal entries are days where the AND-condition flips
False->True. For each entry we compute forward 5/10/20/60-day returns plus the
max gain and max drawdown over the 60-day window.

Aggregate stats: number of signals, win rate, mean/median return, average max
drawdown, best/worst outcome, broken down by market-cap class, sector and
signal strength. Survivorship bias is noted: this uses only currently-listed
symbols, so delisted names are absent — reported honestly, not hidden.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Config
from .rsi_engine import resample_ohlc, wilder_rsi
from .screener import evaluate_signal


def _daily_aligned_rsi(daily: pd.DataFrame, rule: str, period: int) -> pd.Series:
    """Weekly/monthly RSI mapped onto the daily index, available next trading
    day after each candle closes (no intra-candle look-ahead)."""
    candles = resample_ohlc(daily, rule)
    rsi = wilder_rsi(candles["Close"], period)
    # Forward-fill onto daily dates, then shift by one trading day so the value
    # is only visible AFTER the candle's close.
    aligned = rsi.reindex(daily.index.union(rsi.index)).ffill().reindex(daily.index)
    return aligned.shift(1)


def signal_series(cfg: Config, daily: pd.DataFrame) -> pd.DataFrame:
    """Per-day RSI + signal boolean across history for one security."""
    period = cfg.rsi_period
    wrule = cfg.get("candles", "weekly_rule", default="W-FRI")
    mrule = cfg.get("candles", "monthly_rule", default="ME")

    close = daily["Close"]
    d_rsi = wilder_rsi(close, period)
    w_rsi = _daily_aligned_rsi(daily, wrule, period)
    m_rsi = _daily_aligned_rsi(daily, mrule, period)

    df = pd.DataFrame({"close": close, "rsi_1d": d_rsi, "rsi_1w": w_rsi, "rsi_1m": m_rsi})
    df = df.dropna(subset=["rsi_1d", "rsi_1w", "rsi_1m"])

    th = cfg.thresholds
    df["signal"] = (
        (df["rsi_1m"] > th["monthly_gt"])
        & (df["rsi_1w"] > th["weekly_gt"])
        & (df["rsi_1d"] > th["daily_gt"])
    )
    strong = cfg.get("classification", "strong")
    df["strong"] = (
        (df["rsi_1m"] > strong["monthly_gt"])
        & (df["rsi_1w"] > strong["weekly_gt"])
        & (df["rsi_1d"] > strong["daily_gt"])
    )
    return df


def entries_with_returns(cfg: Config, daily: pd.DataFrame, meta: dict | None = None) -> list[dict]:
    """Return one record per signal ENTRY with forward returns."""
    df = signal_series(cfg, daily)
    if df.empty:
        return []
    sig = df["signal"].to_numpy()
    entries_idx = np.where(sig & ~np.concatenate(([False], sig[:-1])))[0]

    closes = df["close"].to_numpy()
    dates = df.index
    horizons = [5, 10, 20, 60]
    out = []
    meta = meta or {}
    n = len(closes)
    for i in entries_idx:
        base = closes[i]
        rec = {
            "date": dates[i].strftime("%Y-%m-%d"),
            "entry_price": round(float(base), 2),
            "rsi_1d": round(float(df["rsi_1d"].iloc[i]), 2),
            "rsi_1w": round(float(df["rsi_1w"].iloc[i]), 2),
            "rsi_1m": round(float(df["rsi_1m"].iloc[i]), 2),
            "strength": "Strong Momentum" if df["strong"].iloc[i] else "Primary Signal",
            **meta,
        }
        window = closes[i : min(i + 61, n)]
        for h in horizons:
            if i + h < n:
                rec[f"ret_{h}d"] = round((closes[i + h] / base - 1) * 100, 2)
            else:
                rec[f"ret_{h}d"] = None
        if len(window) > 1:
            rec["max_gain"] = round((window.max() / base - 1) * 100, 2)
            rec["max_drawdown"] = round((window.min() / base - 1) * 100, 2)
        else:
            rec["max_gain"] = rec["max_drawdown"] = None
        out.append(rec)
    return out


def aggregate(records: list[dict], horizon: str = "ret_20d") -> dict:
    """Summary statistics over a list of entry records."""
    vals = [r[horizon] for r in records if r.get(horizon) is not None]
    if not vals:
        return {"n": 0}
    arr = np.array(vals, dtype=float)
    dds = np.array([r["max_drawdown"] for r in records if r.get("max_drawdown") is not None])
    return {
        "n": len(records),
        "n_with_return": len(arr),
        "win_rate_pct": round(float((arr > 0).mean() * 100), 1),
        "avg_return_pct": round(float(arr.mean()), 2),
        "median_return_pct": round(float(np.median(arr)), 2),
        "avg_max_drawdown_pct": round(float(dds.mean()), 2) if len(dds) else None,
        "best_pct": round(float(arr.max()), 2),
        "worst_pct": round(float(arr.min()), 2),
        "horizon": horizon,
    }


def run_backtest(
    cfg: Config, frames: dict[str, pd.DataFrame], sec_meta: dict[str, dict]
) -> dict:
    """Run the backtest across a set of securities' daily frames.

    ``frames``: yahoo_ticker -> daily df. ``sec_meta``: yahoo_ticker -> dict
    with company/mcap_class/sector for breakdowns.
    """
    all_records: list[dict] = []
    for ticker, daily in frames.items():
        meta = sec_meta.get(ticker, {})
        recs = entries_with_returns(cfg, daily, {
            "ticker": ticker,
            "company": meta.get("company"),
            "mcap_class": meta.get("mcap_class", "Unknown"),
            "sector": meta.get("sector") or "Unknown",
        })
        all_records.extend(recs)

    result = {
        "overall": aggregate(all_records),
        "by_horizon": {h: aggregate(all_records, h) for h in ("ret_5d", "ret_10d", "ret_20d", "ret_60d")},
        "by_mcap": {},
        "by_sector": {},
        "by_strength": {},
        "note": (
            "Survivorship bias: only currently-listed symbols are included; "
            "delisted names are absent. Results are descriptive, NOT a claim "
            "of profitability."
        ),
        "n_records": len(all_records),
    }
    for key, field in (("by_mcap", "mcap_class"), ("by_sector", "sector"), ("by_strength", "strength")):
        groups: dict[str, list] = {}
        for r in all_records:
            groups.setdefault(r.get(field, "Unknown"), []).append(r)
        result[key] = {g: aggregate(recs) for g, recs in groups.items()}
    result["records"] = all_records
    return result
