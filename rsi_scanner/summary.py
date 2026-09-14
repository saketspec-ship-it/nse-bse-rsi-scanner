"""Daily market summary text (spec section 20)."""

from __future__ import annotations

from .config import Config
from .fundamentals import pe_display
from .screener import CAT_STRONG, ScreenResult


def _row(r: ScreenResult) -> str:
    price = f"{r.price:,.1f}" if r.price is not None else "N/A"
    mcap = f"{r.market_cap_cr:,.0f}" if r.market_cap_cr is not None else "N/A"
    pe = pe_display({"pe": r.pe})
    return (
        f"| {r.company[:34]:34} | {price:>10} | {mcap:>10} | {pe:>6} "
        f"| {_f(r.rsi_1d):>6} | {_f(r.rsi_1w):>6} | {_f(r.rsi_1m):>6} |"
    )


def _f(v):
    return f"{v:.1f}" if isinstance(v, (int, float)) else "-"


def build_summary(cfg: Config, results: list[ScreenResult], recon: dict, scanned: int) -> str:
    new = recon["new"]
    active = recon["active"]
    exited = recon["exited"]
    strong = recon["strong"]

    top10 = sorted(
        [r for r in active if r.momentum_score is not None],
        key=lambda r: r.momentum_score,
        reverse=True,
    )[:10]

    hdr = "| Company                            |      Price |      MCap |    P/E | RSI 1D | RSI 1W | RSI 1M |"
    sep = "|" + "-" * (len(hdr) - 2) + "|"

    lines = [
        "NSE/BSE RSI Scanner — Daily Update",
        f"({recon['timestamp']} IST)",
        "",
        f"* Total stocks scanned:        {scanned}",
        f"* Stocks with NEW signals:     {len(new)}",
        f"* Stocks currently in signal:  {len(active)}",
        f"* Stocks exiting signal:       {len(exited)}",
        f"* Strong momentum stocks:      {len(strong)}",
        "",
        "### New Signals",
    ]
    if new:
        lines += [hdr, sep] + [_row(r) for r in sorted(new, key=lambda r: -(r.rsi_1m or 0))]
    else:
        lines.append("(none)")

    lines += ["", "### Strongest Signals (top 10 by momentum score)"]
    if top10:
        lines += [hdr, sep] + [
            _row(r) + f"  score={r.momentum_score}" for r in top10
        ]
    else:
        lines.append("(none)")

    lines += ["", "### Exited Signals"]
    if exited:
        lines += [hdr, sep] + [_row(r) for r in exited]
    else:
        lines.append("(none)")

    lines += [
        "",
        "-" * 70,
        "DISCLAIMER: This is a technical screening & alert system, not "
        "investment advice. An RSI signal alone is not a buy/sell "
        "recommendation.",
    ]
    return "\n".join(lines)
