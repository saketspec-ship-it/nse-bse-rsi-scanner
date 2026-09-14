"""Fundamentals: market cap, P/E, sector/industry via yfinance.

These are display/context fields, NOT part of the primary RSI signal. They are
fetched best-effort and cached, because Yahoo's fundamentals endpoint is slow
and rate-limited at universe scale. Missing/negative values are surfaced
honestly (spec sections 7, 8, 16) rather than coerced to zero.

  * Market cap: `fast_info.market_cap` (INR). Classified into Large/Mid/Small/
    Micro using AMFI-style INR-crore cutoffs; the cutoff methodology is stored
    alongside so it is not confused with any single provider's buckets.
  * P/E: trailing P/E from `.info` (trailingPE). Negative/absent earnings ->
    "N/A / Negative Earnings". Forward P/E captured when present.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import Config

# Market-cap classification cutoffs in INR crore. Documented methodology:
# broadly aligned with SEBI/AMFI large(>~ top 100)/mid/small tiers but applied
# here as fixed absolute INR-crore thresholds for reproducibility.
MCAP_METHOD = "absolute-inr-crore (Large>=20000, Mid>=5000, Small>=1000, else Micro)"


def classify_mcap(mcap_cr: float | None) -> str:
    if mcap_cr is None:
        return "Unknown"
    if mcap_cr >= 20000:
        return "Large Cap"
    if mcap_cr >= 5000:
        return "Mid Cap"
    if mcap_cr >= 1000:
        return "Small Cap"
    return "Micro Cap"


def _cache(cfg: Config) -> Path:
    return cfg.path("cache_dir") / "fundamentals.json"


def _load_cache(cfg: Config) -> dict:
    p = _cache(cfg)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cfg: Config, data: dict) -> None:
    try:
        _cache(cfg).write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def load_cache(cfg: Config) -> dict:
    """Return the full on-disk fundamentals cache (ticker -> record).

    Sector is stable, so this is overlaid onto every security each run — once a
    ticker's sector has been fetched once it persists without re-fetching.
    """
    return _load_cache(cfg)


def fetch_fundamentals(
    cfg: Config,
    tickers: list[str],
    want_pe_sector: bool = True,
    max_age_days: int = 3,
    abort_after_failures: int = 40,
) -> dict[str, dict]:
    """Fetch P/E / sector / (fallback) price via Yahoo's `.info` endpoint.

    Market cap is NOT taken from Yahoo here (its quote endpoint is frequently
    rate-limited with HTTP 401); it is supplied from the BSE scrip master
    instead (see universe.mktcap_cr). This function only enriches P/E, forward
    P/E, sector and industry, best-effort.

    Yahoo's fundamentals endpoint can be blocked wholesale. To avoid grinding
    through thousands of doomed calls, the pass aborts early once
    ``abort_after_failures`` consecutive calls have failed with nothing yet
    succeeding. Cached to disk; only refreshes stale entries.
    """
    import yfinance as yf

    cache = _load_cache(cfg)
    now = datetime.now(timezone.utc)
    out: dict[str, dict] = {}
    consecutive_fail = 0
    any_success = False
    aborted = False

    for t in tickers:
        entry = cache.get(t)
        fresh = False
        if entry and entry.get("asof") and entry.get("pe") is not None:
            try:
                fresh = (now - datetime.fromisoformat(entry["asof"])).days < max_age_days
            except Exception:
                fresh = False
        if fresh:
            out[t] = entry
            continue

        rec = {
            "pe": None, "pe_type": "trailing", "forward_pe": None,
            "sector": None, "industry": None, "price": None,
            "asof": now.isoformat(timespec="seconds"),
        }
        ok = False
        if want_pe_sector and not aborted:
            try:
                info = yf.Ticker(t).info or {}
                if info:
                    tpe = info.get("trailingPE")
                    rec["pe"] = round(tpe, 2) if isinstance(tpe, (int, float)) and tpe > 0 else None
                    fpe = info.get("forwardPE")
                    rec["forward_pe"] = round(fpe, 2) if isinstance(fpe, (int, float)) and fpe > 0 else None
                    rec["sector"] = info.get("sector")
                    rec["industry"] = info.get("industry")
                    rec["price"] = info.get("currentPrice")
                    if rec["sector"] or rec["pe"] is not None:
                        ok = True
            except Exception:
                ok = False

        if ok:
            any_success = True
            consecutive_fail = 0
            cache[t] = rec
        else:
            consecutive_fail += 1
            if not any_success and consecutive_fail >= abort_after_failures:
                aborted = True  # endpoint appears blocked; stop hammering it
        out[t] = rec
        time.sleep(0.03)

    _save_cache(cfg, cache)
    return out


def pe_display(rec: dict) -> str:
    pe = rec.get("pe")
    if pe is None:
        return "N/A / Negative Earnings"
    return f"{pe:.1f}"


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None
