"""Alert formatting and dispatch for newly-entered signals (spec section 10).

Only NEW signals are alerted (dedup handled upstream in signals.reconcile).
Default channel writes alerts to data/output/alerts/. Webhook/Telegram/email
channels can be added by extending ``dispatch``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .config import Config
from .fundamentals import pe_display
from .screener import CATEGORY_EMOJI, ScreenResult


def _fmt(v, nd=1):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "N/A"


def _mcap(v):
    return f"₹{v:,.0f} Cr" if isinstance(v, (int, float)) else "N/A"


def format_alert(r: ScreenResult, timestamp: str) -> str:
    nse = r.nse_symbol or "-"
    bse = r.bse_code or "-"
    chart = None
    if r.nse_symbol:
        chart = f"https://www.tradingview.com/chart/?symbol=NSE:{r.nse_symbol}"
    elif r.bse_code:
        chart = f"https://www.tradingview.com/chart/?symbol=BSE:{r.bse_code}"

    lines = [
        "🚨 RSI Momentum Signal",
        "",
        f"Company: {r.company}",
        f"NSE: {nse}",
        f"BSE: {bse}",
        "",
        f"Price: ₹{_fmt(r.price, 2)}",
        f"Market Cap: {_mcap(r.market_cap_cr)}",
        f"P/E: {pe_display({'pe': r.pe})}",
        "",
        "RSI:",
        f"  1D: {_fmt(r.rsi_1d)}",
        f"  1W: {_fmt(r.rsi_1w)}",
        f"  1M: {_fmt(r.rsi_1m)}",
        "",
        f"Signal: 1M>60 | 1W>40 | 1D>40  ({CATEGORY_EMOJI.get(r.category,'')} {r.category})",
        "",
        "Previous RSI:",
        f"  1D: {_fmt(r.prev_rsi_1d)}",
        f"  1W: {_fmt(r.prev_rsi_1w)}",
        f"  1M: {_fmt(r.prev_rsi_1m)}",
        "",
        f"Signal detected: {timestamp}",
    ]
    if chart:
        lines.append(f"Chart: {chart}")
    return "\n".join(lines)


def dispatch(cfg: Config, new_signals: list[ScreenResult], timestamp: str) -> Path | None:
    """Write/send alerts for newly entered signals. Returns the alert file."""
    if not cfg.get("alerts", "enabled", default=True) or not new_signals:
        return None

    channels = cfg.get("alerts", "channels", default=["file"])
    alert_dir = cfg.path("output_dir") / "alerts"
    alert_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = alert_dir / f"alerts_{stamp}.txt"

    blocks = [format_alert(r, timestamp) for r in new_signals]
    text = ("\n\n" + "=" * 60 + "\n\n").join(blocks)

    if "file" in channels:
        path.write_text(text, encoding="utf-8")
    # Extension points: webhook / telegram / email would consume `blocks` here.
    return path
