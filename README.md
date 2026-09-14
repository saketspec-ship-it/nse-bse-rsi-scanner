# NSE + BSE RSI Momentum Scanner & Alert System

A deterministic technical screener that tracks **all actively traded NSE and
BSE equities** and flags stocks satisfying a multi-timeframe RSI momentum
condition:

> **RSI(14) 1M > 60  AND  RSI(14) 1W > 40  AND  RSI(14) 1D > 40**

It answers one question up front: *which NSE/BSE stocks are showing strong
long-term momentum while keeping healthy daily and weekly momentum?*

> ⚠️ **This is a technical screening & alert tool, not investment advice.** An
> RSI signal alone is not a buy/sell recommendation.

---

## What it does

- Builds a **master security table** for NSE + BSE, deduplicated by **ISIN**
  (a company on both exchanges is one security, both identifiers retained).
- Pulls **adjusted** daily OHLCV per security and builds correct **weekly** and
  **monthly** candles.
- Computes **Wilder RSI(14)** on daily / weekly / monthly closes.
- Applies the primary AND-condition, plus **Strong Momentum**, **Primary**,
  **Watchlist**, **No Signal**, and **Insufficient Data** classification.
- Detects **new** vs **exited** signals against the previous scan and fires
  **de-duplicated alerts** (only on fresh entries).
- Writes a **daily summary**, an interactive **HTML dashboard**, and a
  **signal history** log. Every dashboard column is **sortable and filterable**,
  and a **Days in Signal** column shows how long each stock has continuously met
  the condition (derived from price history, so it is accurate on the first run).
- Publishes as a **live dashboard on GitHub Pages** — updated daily from your PC
  (reliable) plus a best-effort GitHub Actions cloud run.
- Optional **backtest** of every historical signal entry (5/10/20/60-day
  forward returns, win rate, drawdown) with look-ahead protection.

---

## Data provider, adjustment & licensing

| | |
|---|---|
| **Universe – NSE** | `https://archives.nseindia.com/content/equities/EQUITY_L.csv` (SYMBOL, NAME, SERIES, ISIN). Series kept: `EQ`, `BE`. |
| **Universe – BSE** | `https://api.bseindia.com/BseIndiaAPI/api/ListOfScripData` (segment=Equity, status=Active): SCRIP_CD, ISIN, scrip_id. |
| **Prices / fundamentals** | **Yahoo Finance** via the `yfinance` library. NSE tickers use `.NS`, BSE scrip codes use `.BO`. |
| **Refresh** | End-of-day. Intraday quotes are delayed; intraday mode is labelled **PROVISIONAL**. |
| **Adjustment** | `auto_adjust=True` → OHLC are **split/bonus/dividend adjusted**. **RSI is computed on adjusted closing prices** so corporate actions do not create artificial RSI moves. |
| **Timezone** | All timestamps are **IST (Asia/Kolkata)**. |
| **Licensing** | Yahoo data is intended for **personal, non-commercial** use per Yahoo's terms. NSE/BSE lists are public. Verify terms before any commercial/redistribution use. |
| **Limitations** | Coverage of illiquid BSE-only scrips is patchy; Yahoo can return empty history for delisted/suspended/newly listed symbols. These surface as data-quality flags — never silently substituted with stale/estimated data. |

---

## RSI methodology (deterministic)

- **Wilder's RSI(14).** First average gain/loss = simple mean of the first 14
  deltas; thereafter `avg = (prev·13 + current)/14`. `avg_loss = 0` → RSI 100.
  Validated against the canonical StockCharts worked example
  (`tests/test_rsi_engine.py`).
- **Weekly candle** (`W-FRI`): open = first day's open, high = max high,
  low = min low, close = last day's close.
- **Monthly candle** (`ME`): same construction, calendar month.
- **Confirmed candles only** for the primary signal: the in-progress week/month
  is dropped so RSI cannot flip before the candle closes. Set
  `candles.confirmed_only: false` (or `--provisional`) to include the live
  candle — every such signal is then flagged **PROVISIONAL** and never mixed
  with confirmed signals.
- **No look-ahead:** in the backtest, weekly/monthly RSI becomes visible only on
  the trading day *after* the candle closes.

---

## Install

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Unix
```

## Run

```bash
# Full NSE + BSE scan (P/E + sector fetched only for in-signal/watchlist names)
python -m rsi_scanner.scan

# Bounded run (e.g. first 500 by universe order)
python -m rsi_scanner.scan --limit 500

# Intraday / provisional mode (incomplete candle, flagged PROVISIONAL)
python -m rsi_scanner.scan --provisional

# Also run the historical backtest
python -m rsi_scanner.scan --backtest

# P/E + sector for EVERY stock (slow; many Yahoo .info calls)
python -m rsi_scanner.scan --fundamentals-scope all
```

Outputs land in `data/output/`:

- `dashboard.html` — interactive, self-contained dashboard (open in a browser).
- `summary_latest.txt` / `summary_YYYYMMDD.txt` — daily summary.
- `alerts/alerts_*.txt` — new-signal alerts (only on fresh entries).
- `backtest.json` / `backtest_entries.csv` — backtest results.

State & history:

- `data/state/signal_state.json` — `previous_signal_status` per ISIN (dedup).
- `data/history/signal_history.csv` — every ENTER/EXIT event.
- `data/cache/` — per-ticker OHLC parquet (refreshed once/day) + fundamentals.
- `data/universe/master_securities.csv` — the deduped master table.

The **first run is a cold start**: it seeds the baseline state without firing
alerts (so you are not flooded by every stock already in signal). From the
second run onward, only genuine new entries alert.

---

## Live dashboard on GitHub Pages

The scanner emits a Pages-ready bundle in `site/` (`index.html` + `data.json` +
`meta.json`). It is published to the `gh-pages` branch and served by GitHub
Pages. Two update paths run together ("Both"):

- **Local (reliable):** a scheduled task on your PC runs the scan and pushes the
  fresh `site/` to `gh-pages`. Yahoo Finance works from a home IP.
- **GitHub Actions (best-effort):** a scheduled cloud run
  (`.github/workflows/pages.yml`) scans and deploys too — but GitHub's
  datacenter IPs are often rate-limited by Yahoo, so a **data-sufficiency guard**
  (`scripts/check_site.py`) fails the CI job before deploy if too little data
  comes back, so it never overwrites the good local dashboard.

### One-time setup

```powershell
# 1. Install + authenticate the GitHub CLI (interactive; you log in yourself)
winget install --id GitHub.cli -e
gh auth login                       # GitHub.com -> HTTPS -> login with browser

# 2. Create the public repo, push, publish the first dashboard, enable Pages
powershell -ExecutionPolicy Bypass -File scripts\setup_github.ps1

# 3. Register the daily auto-update (scan + deploy) task
powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1
```

`setup_github.ps1` prints your live URL: `https://<user>.github.io/<repo>/`.

### Manual re-publish anytime

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy_pages.ps1            # scan + deploy
powershell -ExecutionPolicy Bypass -File scripts\deploy_pages.ps1 -SkipScan  # deploy current site/
```

## Dashboard toolbar: export, counter, refresh

- **CSV / Excel export** — download the currently filtered + sorted rows. Excel
  uses the SpreadsheetML 2003 XML format (a real `.xls`, no library needed).
  Works out of the box.
- **Visitor / download counter** — via [GoatCounter](https://www.goatcounter.com).
  Configured in `rsi_scanner/dashboard.py` (`GOATCOUNTER`, `GC` path prefix). It
  reuses the existing `vcpdash.goatcounter.com` site with distinct `/rsi*` paths,
  so RSI counts stay separate from the VCP dashboard. Point `GOATCOUNTER` at a
  dedicated site if you prefer; counts can lag up to ~4h (GoatCounter free tier).
- **Refresh scan button** — hidden until you set `REFRESH_PROXY_URL` in
  `dashboard.py`. It POSTs to a small Cloudflare Worker (`cloudflare/refresh-worker.js`)
  that holds a GitHub token server-side and fires a `repository_dispatch` to
  re-run the cloud workflow. See that file's header for setup.
  **Caveat:** the cloud scan uses Yahoo, which often blocks GitHub runners, so a
  cloud refresh is best-effort — the reliable updates come from the local task.

## Scheduling (daily, after market close)

Run once per trading day after the Indian market closes (weekly/monthly RSI use
the latest **completed** candle). See `scripts/` for a ready-made scheduler.

**Windows Task Scheduler** (run `scripts/register_task.ps1` once):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1
```

**cron (Unix), ~18:30 IST on weekdays:**

```cron
0 13 * * 1-5  cd /path/to/RSI && .venv/bin/python -m rsi_scanner.scan >> data/output/cron.log 2>&1
```

---

## Configuration

All parameters live in [`config.yaml`](config.yaml). Defaults:

```text
RSI period            = 14
1D / 1W / 1M threshold = >40 / >40 / >60   (ALL must be true — never OR)
Universe              = NSE + BSE equities (source: both)
Primary signal        = confirmed candle only
Scanner frequency     = daily after market close
Timezone              = Asia/Kolkata
Quality filters       = OFF (price/mcap/volume/PE — never applied to the
                        primary RSI signal unless explicitly enabled)
```

## Tests

```bash
.venv/Scripts/python.exe -m pytest -q
```

## Project layout

```
config.yaml               all tunable parameters
rsi_scanner/
  rsi_engine.py           Wilder RSI + weekly/monthly candle construction
  universe.py             NSE+BSE master table, ISIN dedup, Yahoo ticker map
  datafetch.py            yfinance OHLCV with on-disk cache
  fundamentals.py         market cap / P/E / sector (best-effort, cached)
  screener.py             RSI compute, screening, classification, momentum score
  signals.py              state persistence, new/exited detection, history
  alerts.py               new-signal alert formatting/dispatch
  summary.py              daily text summary
  backtest.py             historical signal replay + forward returns
  dashboard.py            standalone HTML dashboard
  scan.py                 orchestrator / CLI
tests/                    deterministic RSI checks
```

---

## Disclaimer

This software is for **educational and technical-screening** purposes only. It
is **not investment advice**, not a recommendation to buy or sell any security,
and makes **no claim of profitability**. Backtest results are descriptive, use
only currently-listed symbols (so they carry **survivorship bias**), and past
behaviour does not predict future results. Verify all data independently and
consult a SEBI-registered adviser before investing.
