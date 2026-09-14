"""Signal state persistence: dedup, new/exited detection, history log.

State is keyed by ISIN and stored in data/state/signal_state.json. Each entry
records the previous signal status so alerts fire only on NEW entries into the
condition (spec section 11), never repeatedly while the stock stays in signal.

Every entry/exit transition is appended to data/history/signal_history.csv for
later forward-return analysis (spec section 13).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .config import Config
from .screener import ScreenResult


def _state_path(cfg: Config) -> Path:
    return cfg.path("state_dir") / "signal_state.json"


def _history_path(cfg: Config) -> Path:
    return cfg.path("history_dir") / "signal_history.csv"


def load_state(cfg: Config) -> dict:
    p = _state_path(cfg)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(cfg: Config, state: dict) -> None:
    _state_path(cfg).write_text(json.dumps(state, indent=2), encoding="utf-8")


def now_ist(cfg: Config) -> datetime:
    return datetime.now(ZoneInfo(cfg.timezone))


def reconcile(cfg: Config, results: list[ScreenResult]) -> dict:
    """Compare current results with prior state.

    Returns {new, exited, active, strong, results_by_isin, timestamp} and
    updates + persists the state. ``new`` are stocks whose signal flipped
    False->True; ``exited`` flipped True->False.
    """
    state = load_state(cfg)
    cold_start = len(state) == 0  # first run: seed baseline, don't alert-storm
    ts = now_ist(cfg).isoformat(timespec="seconds")

    new_signals: list[ScreenResult] = []
    exited_signals: list[ScreenResult] = []
    active_signals: list[ScreenResult] = []

    history_rows: list[dict] = []

    for r in results:
        prev = state.get(r.isin, {})
        prev_signal = bool(prev.get("rsi_signal", False))
        cur_signal = bool(r.rsi_signal)

        if cur_signal:
            active_signals.append(r)

        # Transition detection (only meaningful for confirmed, non-provisional).
        # On a cold start we seed the baseline without treating existing
        # signals as "new" (avoids an alert storm on the first ever scan).
        if not r.provisional and not cold_start:
            if cur_signal and not prev_signal:
                new_signals.append(r)
                history_rows.append(_history_row(r, "ENTER", ts))
            elif prev_signal and not cur_signal:
                exited_signals.append(r)
                history_rows.append(_history_row(r, "EXIT", ts))

        # Persist current status. Keep last_signal_date for context.
        state[r.isin] = {
            "company": r.company,
            "rsi_signal": cur_signal,
            "category": r.category,
            "rsi_1d": r.rsi_1d, "rsi_1w": r.rsi_1w, "rsi_1m": r.rsi_1m,
            "prev_rsi_1d": r.prev_rsi_1d, "prev_rsi_1w": r.prev_rsi_1w, "prev_rsi_1m": r.prev_rsi_1m,
            "price": r.price,
            "days_in_signal": r.days_in_signal, "signal_since": r.signal_since,
            "last_scan": ts,
            "last_signal_date": ts if cur_signal else prev.get("last_signal_date"),
        }

    if not cfg.get("candles", "confirmed_only", default=True):
        # In provisional mode we do not persist transitions to avoid polluting
        # confirmed history; only refresh scan metadata already done above.
        pass
    else:
        save_state(cfg, state)
        if history_rows:
            _append_history(cfg, history_rows)

    strong = [r for r in active_signals if r.category == "Strong Momentum"]
    return {
        "new": new_signals,
        "exited": exited_signals,
        "active": active_signals,
        "strong": strong,
        "timestamp": ts,
        "cold_start": cold_start,
    }


def _history_row(r: ScreenResult, event: str, ts: str) -> dict:
    return {
        "timestamp": ts,
        "event": event,
        "isin": r.isin,
        "company": r.company,
        "nse_symbol": r.nse_symbol,
        "bse_code": r.bse_code,
        "price": r.price,
        "market_cap_cr": r.market_cap_cr,
        "pe": r.pe,
        "rsi_1d": r.rsi_1d,
        "rsi_1w": r.rsi_1w,
        "rsi_1m": r.rsi_1m,
        "prev_rsi_1d": r.prev_rsi_1d,
        "prev_rsi_1w": r.prev_rsi_1w,
        "prev_rsi_1m": r.prev_rsi_1m,
        "signal_type": r.category,
        # Forward returns filled in later by the backtest/return-updater.
        "ret_5d": None, "ret_20d": None, "ret_60d": None,
    }


def _append_history(cfg: Config, rows: list[dict]) -> None:
    path = _history_path(cfg)
    df = pd.DataFrame(rows)
    if path.exists():
        df.to_csv(path, mode="a", header=False, index=False)
    else:
        df.to_csv(path, index=False)


def load_history(cfg: Config) -> pd.DataFrame:
    path = _history_path(cfg)
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame()
