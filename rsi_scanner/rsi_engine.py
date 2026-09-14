"""Deterministic Wilder RSI(14) and multi-timeframe candle construction.

Design goals (spec section 21):
  * RSI is reproducible and deterministic for a given price series.
  * Weekly / monthly candles are built correctly from daily OHLC.
  * No look-ahead bias: RSI at bar i uses only closes up to and including i.
  * Completed candles only for the confirmed signal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI on a close series.

    Uses the canonical Wilder smoothing: the first average gain/loss is the
    simple mean of the first ``period`` deltas; subsequent values use the
    recursive smoothing ``avg = (prev*(period-1) + current) / period``.

    Returns a Series aligned to ``close`` with NaN for the warm-up region
    (the first ``period`` bars, which lack a defined RSI).
    """
    if not isinstance(close, pd.Series):
        close = pd.Series(close)
    close = close.astype("float64")
    n = len(close)
    rsi = pd.Series(np.nan, index=close.index, dtype="float64")
    if n <= period:
        return rsi

    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    gain_v = gain.to_numpy()
    loss_v = loss.to_numpy()
    out = np.full(n, np.nan, dtype="float64")

    # Seed at index `period` with the simple average of the first `period`
    # deltas (indices 1..period). delta[0] is NaN and excluded.
    avg_gain = np.nanmean(gain_v[1 : period + 1])
    avg_loss = np.nanmean(loss_v[1 : period + 1])
    out[period] = _rsi_from_avgs(avg_gain, avg_loss)

    inv = 1.0 / period
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gain_v[i]) * inv
        avg_loss = (avg_loss * (period - 1) + loss_v[i]) * inv
        out[i] = _rsi_from_avgs(avg_gain, avg_loss)

    rsi[:] = out
    return rsi


def _rsi_from_avgs(avg_gain: float, avg_loss: float) -> float:
    """Convert Wilder averages to an RSI value, handling the zero cases."""
    if avg_loss == 0.0:
        # No losses over the window -> maximally overbought.
        return 100.0 if avg_gain > 0.0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def latest_rsi(close: pd.Series, period: int = 14) -> float | None:
    """Return the most recent non-NaN RSI value, or None if undefined."""
    series = wilder_rsi(close, period)
    series = series.dropna()
    if series.empty:
        return None
    return float(series.iloc[-1])


# ---------------------------------------------------------------------------
# Candle resampling
# ---------------------------------------------------------------------------

_OHLC_AGG = {
    "Open": "first",
    "High": "max",
    "Low": "min",
    "Close": "last",
    "Volume": "sum",
}


def resample_ohlc(daily: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample a daily OHLCV frame to weekly/monthly candles.

    Weekly: open = first day's open, high = max high, low = min low,
    close = last day's close (spec section 4). ``rule`` is a pandas offset
    alias such as ``"W-FRI"`` or ``"ME"``.

    The index is a DatetimeIndex; only columns present are aggregated.
    """
    agg = {c: how for c, how in _OHLC_AGG.items() if c in daily.columns}
    out = daily.resample(rule, label="right", closed="right").agg(agg)
    # Drop periods with no trading (holidays/gaps produce all-NaN rows).
    return out.dropna(subset=["Close"])


def drop_incomplete_last(candles: pd.DataFrame, rule: str, asof: pd.Timestamp) -> pd.DataFrame:
    """Remove the final candle if its period has not yet closed as of ``asof``.

    Prevents look-ahead / provisional contamination: a week labelled Friday
    that lies in the future relative to the last trading day, or the current
    month before month-end, is dropped for the confirmed signal.
    """
    if candles.empty:
        return candles
    last_label = candles.index[-1]
    period_end = _period_end(last_label, rule)
    if asof < period_end:
        return candles.iloc[:-1]
    return candles


def _period_end(label: pd.Timestamp, rule: str) -> pd.Timestamp:
    """The real calendar end of the period a right-labelled candle represents."""
    label = pd.Timestamp(label).normalize()
    if rule.upper().startswith("W"):
        return label  # W-FRI label already sits on the week's closing day
    # Month/other: label is period end for ME already.
    return label
