"""Per-security RSI computation, screening, classification and scoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

import pandas as pd

from .config import Config
from .rsi_engine import drop_incomplete_last, latest_rsi, resample_ohlc, wilder_rsi

# Output categories (spec section 19).
CAT_NO_SIGNAL = "No Signal"
CAT_WATCHLIST = "Watchlist"
CAT_PRIMARY = "Primary Signal"
CAT_STRONG = "Strong Momentum"
CAT_INSUFFICIENT = "Insufficient Data"

CATEGORY_EMOJI = {
    CAT_NO_SIGNAL: "🔴",
    CAT_WATCHLIST: "🟡",
    CAT_PRIMARY: "🟢",
    CAT_STRONG: "🔵",
    CAT_INSUFFICIENT: "⚪",
}


@dataclass
class ScreenResult:
    isin: str
    company: str
    nse_symbol: str | None
    bse_code: str | None
    exchanges: str
    yahoo_ticker: str
    price: float | None = None
    rsi_1d: float | None = None
    rsi_1w: float | None = None
    rsi_1m: float | None = None
    prev_rsi_1d: float | None = None
    prev_rsi_1w: float | None = None
    prev_rsi_1m: float | None = None
    rsi_signal: bool = False
    category: str = CAT_INSUFFICIENT
    provisional: bool = False
    momentum_score: float | None = None
    days_in_signal: int | None = None
    signal_since: str | None = None
    market_cap_cr: float | None = None
    mcap_class: str = "Unknown"
    pe: float | None = None
    pe_type: str = "trailing"
    forward_pe: float | None = None
    sector: str | None = None
    industry: str | None = None
    avg_volume: float | None = None
    last_date: str | None = None
    data_flags: list[str] = field(default_factory=list)

    def to_row(self) -> dict:
        return asdict(self)


def _round(x):
    return round(float(x), 2) if x is not None else None


def compute_rsis(cfg: Config, daily: pd.DataFrame) -> dict:
    """Compute daily/weekly/monthly RSI (current + previous period) plus flags.

    Returns a dict; on insufficient data the relevant RSI values are None and a
    flag is recorded. Weekly/monthly use completed candles only when
    ``candles.confirmed_only`` is true.
    """
    period = cfg.rsi_period
    confirmed_only = bool(cfg.get("candles", "confirmed_only", default=True))
    wrule = cfg.get("candles", "weekly_rule", default="W-FRI")
    mrule = cfg.get("candles", "monthly_rule", default="ME")
    min_d = int(cfg.get("data", "min_daily_bars", default=60))
    min_w = int(cfg.get("data", "min_weekly_bars", default=20))
    min_m = int(cfg.get("data", "min_monthly_bars", default=16))
    stale_days = int(cfg.get("data", "stale_days", default=5))

    flags: list[str] = []
    res = {
        "rsi_1d": None, "rsi_1w": None, "rsi_1m": None,
        "prev_1d": None, "prev_1w": None, "prev_1m": None,
        "price": None, "avg_volume": None, "last_date": None,
        "provisional": False, "flags": flags,
    }

    if daily is None or daily.empty:
        flags.append("Missing OHLC data")
        return res

    close = daily["Close"].dropna()
    asof = close.index[-1]
    res["price"] = _round(close.iloc[-1])
    res["last_date"] = asof.strftime("%Y-%m-%d")
    if "Volume" in daily.columns:
        res["avg_volume"] = _round(daily["Volume"].tail(20).mean())

    # Staleness: last close far behind "today" (best-effort; scan-time relative).
    age_days = (pd.Timestamp.now().normalize() - asof.normalize()).days
    if age_days > stale_days * 2:
        flags.append(f"Stale price ({age_days}d old)")

    # ---- Daily RSI (current + previous bar) ------------------------------
    if len(close) < min_d + period:
        flags.append("Insufficient daily history")
    else:
        d_series = wilder_rsi(close, period).dropna()
        if len(d_series) >= 2:
            res["rsi_1d"] = _round(d_series.iloc[-1])
            res["prev_1d"] = _round(d_series.iloc[-2])

    # ---- Weekly RSI ------------------------------------------------------
    weekly = resample_ohlc(daily, wrule)
    if confirmed_only:
        weekly = drop_incomplete_last(weekly, wrule, asof)
    if len(weekly) < min_w + period:
        flags.append("Insufficient weekly history")
    else:
        w_series = wilder_rsi(weekly["Close"], period).dropna()
        if len(w_series) >= 2:
            res["rsi_1w"] = _round(w_series.iloc[-1])
            res["prev_1w"] = _round(w_series.iloc[-2])

    # ---- Monthly RSI -----------------------------------------------------
    monthly = resample_ohlc(daily, mrule)
    if confirmed_only:
        monthly = drop_incomplete_last(monthly, mrule, asof)
    if len(monthly) < min_m + period:
        flags.append("Insufficient monthly history")
    else:
        m_series = wilder_rsi(monthly["Close"], period).dropna()
        if len(m_series) >= 2:
            res["rsi_1m"] = _round(m_series.iloc[-1])
            res["prev_1m"] = _round(m_series.iloc[-2])

    res["provisional"] = not confirmed_only
    return res


def evaluate_signal(cfg: Config, rsi_1d, rsi_1w, rsi_1m) -> tuple[bool, str]:
    """Return (rsi_signal, category) from the three RSI values."""
    if rsi_1d is None or rsi_1w is None or rsi_1m is None:
        return False, CAT_INSUFFICIENT

    th = cfg.thresholds
    strong = cfg.get("classification", "strong")
    watch = cfg.get("classification", "watchlist")

    primary = (rsi_1m > th["monthly_gt"] and rsi_1w > th["weekly_gt"] and rsi_1d > th["daily_gt"])

    if (rsi_1m > strong["monthly_gt"] and rsi_1w > strong["weekly_gt"] and rsi_1d > strong["daily_gt"]):
        return True, CAT_STRONG
    if primary:
        return True, CAT_PRIMARY
    if (rsi_1m > watch["monthly_gt"] and rsi_1w > watch["weekly_gt"] and rsi_1d > watch["daily_gt"]):
        return False, CAT_WATCHLIST
    return False, CAT_NO_SIGNAL


def momentum_score(cfg: Config, rsi_1d, rsi_1w, rsi_1m) -> float | None:
    """0-100 momentum score (spec section 18). Never overrides the signal."""
    if rsi_1d is None or rsi_1w is None or rsi_1m is None:
        return None
    w = cfg.get("momentum_score")
    score = (
        w["weight_monthly"] * rsi_1m
        + w["weight_weekly"] * rsi_1w
        + w["weight_daily"] * rsi_1d
    )
    return round(max(0.0, min(100.0, score)), 1)


def current_signal_streak(cfg: Config, daily: pd.DataFrame, in_signal: bool) -> tuple[int | None, str | None]:
    """Trading days the stock has continuously satisfied the signal, and the
    date the current run began.

    Reconstructs the daily signal with no look-ahead (weekly/monthly RSI become
    visible only after their candle closes) and counts the trailing run of
    True values. Computed only for stocks currently in signal, so it is cheap.
    """
    if not in_signal or daily is None or daily.empty:
        return None, None
    from . import backtest  # local import avoids a circular dependency

    df = backtest.signal_series(cfg, daily)
    if df.empty:
        return (1, None) if in_signal else (None, None)
    sig = df["signal"].to_numpy()
    run = 0
    for v in sig[::-1]:
        if v:
            run += 1
        else:
            break
    if run == 0:
        # Screener (confirmed candles) says in-signal but the daily
        # reconstruction disagrees at the last bar; report at least today.
        return 1, df.index[-1].strftime("%Y-%m-%d")
    since = df.index[len(sig) - run]
    return run, since.strftime("%Y-%m-%d")


def screen_security(cfg: Config, sec: dict, daily: pd.DataFrame, fund: dict | None) -> ScreenResult:
    """Full evaluation for one security."""
    rr = compute_rsis(cfg, daily)
    signal, category = evaluate_signal(cfg, rr["rsi_1d"], rr["rsi_1w"], rr["rsi_1m"])
    score = momentum_score(cfg, rr["rsi_1d"], rr["rsi_1w"], rr["rsi_1m"])
    days_in_signal, signal_since = current_signal_streak(cfg, daily, signal)

    fund = fund or {}
    price = rr["price"] if rr["price"] is not None else fund.get("price")
    if fund.get("market_cap_cr") is None:
        rr["flags"].append("Missing market cap")
    if fund.get("pe") is None and category != CAT_INSUFFICIENT:
        rr["flags"].append("Missing/negative P/E")

    return ScreenResult(
        isin=sec.get("isin", ""),
        company=sec.get("company", ""),
        nse_symbol=_clean(sec.get("nse_symbol")),
        bse_code=_clean(sec.get("bse_code")),
        exchanges=sec.get("exchanges", "?"),
        yahoo_ticker=sec["yahoo_ticker"],
        price=_round(price) if price is not None else None,
        rsi_1d=rr["rsi_1d"], rsi_1w=rr["rsi_1w"], rsi_1m=rr["rsi_1m"],
        prev_rsi_1d=rr["prev_1d"], prev_rsi_1w=rr["prev_1w"], prev_rsi_1m=rr["prev_1m"],
        rsi_signal=signal, category=category, provisional=rr["provisional"],
        momentum_score=score,
        days_in_signal=days_in_signal, signal_since=signal_since,
        market_cap_cr=fund.get("market_cap_cr"),
        mcap_class=fund.get("mcap_class", "Unknown"),
        pe=fund.get("pe"), pe_type=fund.get("pe_type", "trailing"),
        forward_pe=fund.get("forward_pe"),
        sector=fund.get("sector"), industry=fund.get("industry"),
        avg_volume=rr["avg_volume"], last_date=rr["last_date"],
        data_flags=rr["flags"],
    )


def _clean(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "nan", "<NA>", "None"):
        return None
    return s
