"""Deterministic checks for the Wilder RSI engine and candle resampling."""

import numpy as np
import pandas as pd

from rsi_scanner.rsi_engine import (
    drop_incomplete_last,
    latest_rsi,
    resample_ohlc,
    wilder_rsi,
)

# Canonical Wilder / StockCharts 14-period RSI worked example.
STOCKCHARTS = [
    44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245,
    45.8433, 46.0826, 45.8931, 46.0328, 45.6140, 46.2820, 46.2820, 46.0028,
    46.0328, 46.4116, 46.2222, 45.6439, 46.2122, 46.2521, 45.7137, 46.4515,
    45.7835, 45.3548, 44.0288, 44.1783, 44.2181, 44.5672, 43.4205, 42.6628,
    43.1314,
]
# Expected RSI values from StockCharts' published worked example. The first
# defined RSI (index 14) and the two Wilder-smoothed values after it are the
# canonical reference figures (~70.53, 66.32, 66.55); small deltas come from
# the rounded input prices used here.
EXPECTED = {14: 70.53, 15: 66.32, 16: 66.55}


def test_wilder_matches_stockcharts():
    rsi = wilder_rsi(pd.Series(STOCKCHARTS), period=14)
    for idx, exp in EXPECTED.items():
        assert abs(rsi.iloc[idx] - exp) < 0.15, (idx, rsi.iloc[idx], exp)


def test_warmup_is_nan():
    rsi = wilder_rsi(pd.Series(STOCKCHARTS), period=14)
    assert rsi.iloc[:14].isna().all()
    assert not np.isnan(rsi.iloc[14])


def test_all_gains_gives_100():
    close = pd.Series(np.arange(1, 40, dtype=float))  # strictly rising
    assert latest_rsi(close, 14) == 100.0


def test_all_losses_gives_0():
    close = pd.Series(np.arange(40, 1, -1, dtype=float))  # strictly falling
    assert latest_rsi(close, 14) == 0.0


def test_insufficient_history_returns_none():
    assert latest_rsi(pd.Series([1.0, 2.0, 3.0]), 14) is None


def test_resample_weekly_ohlc():
    idx = pd.bdate_range("2024-01-01", periods=10)  # two trading weeks
    df = pd.DataFrame(
        {
            "Open": range(10),
            "High": [i + 2 for i in range(10)],
            "Low": [i - 1 for i in range(10)],
            "Close": [i + 1 for i in range(10)],
            "Volume": [100] * 10,
        },
        index=idx,
    )
    wk = resample_ohlc(df, "W-FRI")
    assert len(wk) == 2
    # First week: open = first day's open, close = Friday's close, high = max.
    assert wk.iloc[0]["Open"] == 0
    assert wk.iloc[0]["Close"] == 5
    assert wk.iloc[0]["High"] == max(i + 2 for i in range(5))
    assert wk.iloc[0]["Volume"] == 500


def test_last_cross_up():
    from rsi_scanner.screener import _last_cross_up
    idx = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30"])
    # Crosses up through 60 between Feb (58) and Mar (63); stays above in Apr.
    s = pd.Series([55.0, 58.0, 63.0, 65.0], index=idx)
    days, cdate, months, before = _last_cross_up(s, 60.0, pd.Timestamp("2024-04-30"))
    assert cdate == "2024-03-31" and months == 1 and before is False
    assert days == 30
    # Currently below the level -> no active crossing.
    s2 = pd.Series([65.0, 62.0, 58.0], index=idx[:3])
    assert _last_cross_up(s2, 60.0, idx[2])[0] is None
    # Above for the whole series -> crossing predates the data.
    s3 = pd.Series([61.0, 62.0, 63.0], index=idx[:3])
    d, cd, mo, before3 = _last_cross_up(s3, 60.0, idx[2])
    assert before3 is True and cd == "2024-01-31"


def test_drop_incomplete_last_week():
    idx = pd.bdate_range("2024-01-01", periods=10)
    df = pd.DataFrame({"Close": range(10)}, index=idx)
    wk = df.resample("W-FRI", label="right", closed="right").agg({"Close": "last"})
    # As-of the Wednesday of the second week: last week not yet closed.
    asof = pd.Timestamp("2024-01-10")
    trimmed = drop_incomplete_last(wk, "W-FRI", asof)
    assert len(trimmed) == len(wk) - 1
