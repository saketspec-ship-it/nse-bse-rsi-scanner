"""Historical OHLCV retrieval via yfinance, with on-disk caching.

Data provider: Yahoo Finance (via the `yfinance` library).
  * Refresh frequency: end-of-day; intraday quotes are delayed.
  * Adjusted prices: auto_adjust=True -> OHLC adjusted for splits & dividends,
    so long-term RSI is not distorted by corporate actions (spec section 3).
  * Limitations: coverage of illiquid BSE-only scrips is patchy; Yahoo may
    return empty history for delisted/suspended/newly listed symbols. Those
    are surfaced as data-quality flags rather than silently substituted.
  * Licensing: Yahoo data is for personal, non-commercial use per Yahoo's ToS.

Cache: one parquet per Yahoo ticker under data/cache/, refreshed when older
than one calendar day so repeated same-day scans do not re-hit the network.
"""

from __future__ import annotations

import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .config import Config

warnings.simplefilter("ignore", FutureWarning)

_OHLC_COLS = ["Open", "High", "Low", "Close", "Volume"]


def _cache_file(cfg: Config, ticker: str) -> Path:
    safe = ticker.replace("/", "_")
    return cfg.path("cache_dir") / f"{safe}.parquet"


def _is_fresh(path: Path, max_age_hours: float = 20) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < max_age_hours * 3600


def fetch_one(cfg: Config, ticker: str, force: bool = False) -> pd.DataFrame | None:
    """Return a cached-or-fresh daily OHLCV frame for a single Yahoo ticker."""
    import yfinance as yf

    max_age = float(cfg.get("data", "cache_max_age_hours", default=20))
    cache = _cache_file(cfg, ticker)
    if _is_fresh(cache, max_age) and not force:
        try:
            return pd.read_parquet(cache)
        except Exception:
            pass

    period = cfg.get("data", "history_period", default="6y")
    retries = int(cfg.get("data", "retries", default=3))
    df = None
    for attempt in range(retries):
        try:
            df = yf.download(
                ticker,
                period=period,
                interval="1d",
                auto_adjust=bool(cfg.get("data", "adjusted", default=True)),
                progress=False,
                threads=False,
                actions=False,
            )
            break
        except Exception:
            time.sleep(1.0 + attempt)
    if df is None or df.empty:
        return None

    df = _normalize(df)
    if df is None or df.empty:
        return None
    try:
        df.to_parquet(cache)
    except Exception:
        pass
    return df


def _normalize(df: pd.DataFrame) -> pd.DataFrame | None:
    """Flatten yfinance output to a clean single-index OHLCV frame."""
    if isinstance(df.columns, pd.MultiIndex):
        # yfinance returns (field, ticker); take the field level.
        df.columns = df.columns.get_level_values(0)
    df = df[[c for c in _OHLC_COLS if c in df.columns]].copy()
    df = df.dropna(subset=["Close"])
    df.index = pd.to_datetime(df.index)
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def fetch_many(
    cfg: Config, tickers: list[str], force: bool = False, on_progress=None
) -> dict[str, pd.DataFrame]:
    """Fetch many tickers concurrently, respecting batch pauses.

    Returns a dict ticker -> frame (only successful, non-empty results).
    """
    results: dict[str, pd.DataFrame] = {}
    max_workers = int(cfg.get("data", "max_workers", default=4))
    batch_size = int(cfg.get("data", "batch_size", default=40))
    pause = float(cfg.get("data", "request_pause", default=0.4))

    done = 0
    total = len(tickers)
    for start in range(0, total, batch_size):
        batch = tickers[start : start + batch_size]
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(fetch_one, cfg, t, force): t for t in batch}
            for fut in as_completed(futs):
                t = futs[fut]
                try:
                    df = fut.result()
                except Exception:
                    df = None
                if df is not None and not df.empty:
                    results[t] = df
                done += 1
                if on_progress:
                    on_progress(done, total, t)
        time.sleep(pause)
    return results


def last_trading_dates(frames: dict[str, pd.DataFrame]) -> dict[str, datetime]:
    return {t: df.index[-1].to_pydatetime() for t, df in frames.items() if not df.empty}
