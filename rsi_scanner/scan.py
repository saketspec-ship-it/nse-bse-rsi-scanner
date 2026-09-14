"""Main scan orchestrator / CLI.

Pipeline:
  1. Build (or load cached) NSE+BSE master security table, deduped by ISIN.
  2. Fetch daily adjusted OHLCV per security via yfinance (cached).
  3. Fetch fundamentals (market cap / P/E / sector) best-effort.
  4. Compute Wilder RSI(14) on daily / weekly / monthly candles.
  5. Screen + classify + score each security.
  6. Reconcile with prior state -> new / exited signals (dedup).
  7. Fire alerts for NEW signals only.
  8. Write daily summary + HTML dashboard.
  9. Optionally run the historical backtest.

Usage:
  python -m rsi_scanner.scan                 # full run
  python -m rsi_scanner.scan --limit 300     # bounded run
  python -m rsi_scanner.scan --provisional   # intraday (incomplete candle)
  python -m rsi_scanner.scan --backtest              # also run backtest
  python -m rsi_scanner.scan --fundamentals-scope all  # P/E+sector for all (slow)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

import pandas as pd

from . import alerts, backtest, dashboard, datafetch, fundamentals, screener, sector_index, signals, summary
from .config import load_config
from .universe import build_universe, yahoo_ticker


def _log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def _clean_str(v):
    if v is None:
        return None
    s = str(v).strip()
    return None if s in ("", "nan", "<NA>", "None") else s


def run(args) -> dict:
    cfg = load_config(args.config)
    if args.limit is not None:
        cfg.raw.setdefault("universe", {})["limit"] = args.limit
    if args.provisional:
        cfg.raw.setdefault("candles", {})["confirmed_only"] = False
    if args.use_cache:
        # Reuse any on-disk OHLC regardless of age (offline / rerun mode).
        cfg.raw.setdefault("data", {})["cache_max_age_hours"] = 1_000_000

    _log("Building universe (NSE + BSE, deduped by ISIN)...")
    master = build_universe(cfg, force=args.refresh_universe)
    master = master.copy()
    # Apply the limit even when the universe was read from cache (build_universe
    # only caps at build time). Lets --limit bound any run.
    limit = int(cfg.get("universe", "limit", default=0) or 0)
    if limit > 0:
        master = master.head(limit).copy()
    master["yahoo_ticker"] = master.apply(yahoo_ticker, axis=1)
    master = master[master["yahoo_ticker"].notna()].reset_index(drop=True)
    _log(f"Universe: {len(master)} securities.")

    tickers = master["yahoo_ticker"].tolist()

    _log(f"Fetching daily OHLCV for {len(tickers)} tickers (cached where fresh)...")
    t0 = time.time()

    def prog(done, total, t):
        if done % 100 == 0 or done == total:
            _log(f"  fetched {done}/{total} ({t})")

    frames = datafetch.fetch_many(cfg, tickers, force=args.refresh_data, on_progress=prog)
    _log(f"Got data for {len(frames)}/{len(tickers)} in {time.time()-t0:.0f}s.")

    have = [t for t in tickers if t in frames]

    # Market cap comes from the BSE scrip master (INR crore) — no Yahoo call,
    # so it is unaffected by Yahoo's quote-endpoint rate limiting.
    fund_map: dict[str, dict] = {}
    for _, sec in master.iterrows():
        mcap = sec.get("mktcap_cr")
        mcap = float(mcap) if mcap is not None and str(mcap) not in ("nan", "<NA>", "None") and mcap == mcap else None
        fund_map[sec["yahoo_ticker"]] = {
            "market_cap_cr": round(mcap, 1) if mcap else None,
            "mcap_class": fundamentals.classify_mcap(mcap),
            "pe": None, "pe_type": "trailing", "forward_pe": None,
            "sector": None, "industry": _clean_str(sec.get("industry")), "price": None,
        }

    # Overlay any previously-cached sector / P/E / industry onto EVERY security
    # (not just the signal set). Sector is stable, so once fetched it persists
    # for all symbols without re-hitting Yahoo on every run.
    fcache = fundamentals.load_cache(cfg)
    n_sector = 0
    for t, base in fund_map.items():
        c = fcache.get(t)
        if not c:
            continue
        for k in ("pe", "forward_pe", "sector", "industry"):
            if c.get(k) is not None:
                base[k] = c[k]
        if base.get("sector"):
            n_sector += 1
    _log(f"Sector known for {n_sector}/{len(fund_map)} from cache (rest -> Unknown).")

    def do_screen():
        rows: list[screener.ScreenResult] = []
        for _, sec in master.iterrows():
            t = sec["yahoo_ticker"]
            rows.append(screener.screen_security(cfg, sec.to_dict(), frames.get(t), fund_map.get(t)))
        return rows

    _log("Screening securities...")
    results = do_screen()

    # Targeted P/E + sector pass via Yahoo .info (may be blocked -> stays N/A).
    # Only for the names that matter (in-signal / watchlist), or all if asked.
    if args.fundamentals_scope in ("all", "signal"):
        if args.fundamentals_scope == "all":
            targets = have
        else:
            targets = [
                r.yahoo_ticker for r in results
                if r.category in (screener.CAT_STRONG, screener.CAT_PRIMARY, screener.CAT_WATCHLIST)
            ]
        if targets:
            _log(f"Fetching P/E + sector for {len(targets)} relevant securities (best-effort)...")
            enriched = fundamentals.fetch_fundamentals(cfg, targets, want_pe_sector=True)
            got = 0
            for t, e in enriched.items():
                base = fund_map.get(t, {})
                for k in ("pe", "forward_pe", "sector"):
                    if e.get(k) is not None:
                        base[k] = e[k]
                        if k == "pe":
                            got += 1
                if e.get("industry"):
                    base["industry"] = e["industry"]
                fund_map[t] = base
            _log(f"P/E obtained for {got}/{len(targets)} (Yahoo .info); rest shown as N/A.")
            results = do_screen()

    _log("Reconciling signal state (new / exited, dedup)...")
    recon = signals.reconcile(cfg, results)

    alert_path = alerts.dispatch(cfg, recon["new"], recon["timestamp"])
    if alert_path:
        _log(f"Wrote {len(recon['new'])} new-signal alert(s) -> {alert_path}")

    # Daily summary
    summ = summary.build_summary(cfg, results, recon, scanned=len(results))
    out_dir = cfg.path("output_dir")
    summ_path = out_dir / f"summary_{datetime.now():%Y%m%d}.txt"
    summ_path.write_text(summ, encoding="utf-8")
    (out_dir / "summary_latest.txt").write_text(summ, encoding="utf-8")
    _log(f"Wrote daily summary -> {summ_path}")

    bt_summary = None
    if args.backtest:
        _log("Running historical backtest...")
        sec_meta = {
            r.yahoo_ticker: {"company": r.company, "mcap_class": r.mcap_class, "sector": r.sector}
            for r in results
        }
        bt_frames = {t: frames[t] for t in frames}
        bt_summary = backtest.run_backtest(cfg, bt_frames, sec_meta)
        bt_path = out_dir / "backtest.json"
        bt_path.write_text(json.dumps({k: v for k, v in bt_summary.items() if k != "records"}, indent=2), encoding="utf-8")
        pd.DataFrame(bt_summary["records"]).to_csv(out_dir / "backtest_entries.csv", index=False)
        _log(f"Backtest: {bt_summary['n_records']} historical entries -> {bt_path}")

    _log("Building sector indices (mcap >= 2000 Cr, known sector)...")
    sectors = sector_index.build_sector_indices(cfg, results, frames)
    _log(f"Built {len(sectors['sectors'])} sector indices.")

    _log("Rendering HTML dashboard...")
    html = dashboard.render_embedded(cfg, results, recon, scanned=len(results), backtest_summary=bt_summary, sectors=sectors)
    dash_path = out_dir / "dashboard.html"
    dash_path.write_text(html, encoding="utf-8")
    _log(f"Dashboard (self-contained) -> {dash_path}")

    site_dir = cfg.path("site_dir")
    dashboard.write_site(cfg, site_dir, results, recon, scanned=len(results), backtest_summary=bt_summary, sectors=sectors)
    _log(f"Pages site (index.html + data.json + sectors.json) -> {site_dir}")

    print("\n" + summ)
    return {
        "results": results, "recon": recon, "dashboard": str(dash_path),
        "summary": str(summ_path), "backtest": bt_summary,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="NSE + BSE RSI momentum scanner")
    p.add_argument("--config", default=None)
    p.add_argument("--limit", type=int, default=None, help="cap number of securities")
    p.add_argument("--provisional", action="store_true", help="use incomplete candles (PROVISIONAL)")
    p.add_argument("--backtest", action="store_true", help="also run historical backtest")
    p.add_argument("--refresh-universe", action="store_true")
    p.add_argument("--refresh-data", action="store_true", help="ignore OHLC cache")
    p.add_argument("--use-cache", action="store_true", help="reuse on-disk OHLC regardless of age")
    p.add_argument(
        "--fundamentals-scope", choices=["all", "signal", "none"], default="signal",
        help="all=P/E+sector for every stock (slow); signal=only for in-signal/"
             "watchlist names (default); none=skip market cap & P/E entirely",
    )
    args = p.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
