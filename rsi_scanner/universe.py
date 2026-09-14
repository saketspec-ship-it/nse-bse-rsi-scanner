"""Build the master security table for NSE + BSE equities.

Sources (public, no auth):
  * NSE : https://archives.nseindia.com/content/equities/EQUITY_L.csv
          columns include SYMBOL, NAME OF COMPANY, SERIES, ISIN NUMBER.
  * BSE : https://api.bseindia.com/BseIndiaAPI/api/ListOfScripData/w
          (segment=Equity, status=Active) -> SCRIP_CD, ISIN_NUMBER, scrip_id,
          Issuer_Name, GROUP, FACE_VALUE, Mktcap.

Deduplication: a company listed on both exchanges is ONE security, keyed by
ISIN. NSE and BSE identifiers are both retained. Excludes non-equity
instruments (ETFs / bonds / warrants / suspended / delisted) by relying on the
exchanges' own equity/active classifications and an ISIN sanity check.

The resulting table is cached as parquet + csv and only rebuilt when older
than ``universe.refresh_days``.
"""

from __future__ import annotations

import io
import json
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from .config import Config

NSE_EQUITY_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
BSE_LIST_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/ListOfScripData/w"
    "?Group=&Scripcode=&industry=&segment=Equity&status=Active"
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/json,*/*",
}
_BSE_HEADERS = dict(_HEADERS, Referer="https://www.bseindia.com/")

# ISINs starting with INE/INF are ordinary equities/InvITs; INF is fund units.
# Ordinary equity ISINs are of the form IN + E + 9 alphanumerics.
_ISIN_EQUITY_PREFIX = "INE"


def _fetch_nse() -> pd.DataFrame:
    resp = requests.get(NSE_EQUITY_URL, headers=_HEADERS, timeout=40)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(
        columns={
            "SYMBOL": "nse_symbol",
            "NAME OF COMPANY": "company",
            "SERIES": "series",
            "ISIN NUMBER": "isin",
        }
    )
    keep = ["nse_symbol", "company", "series", "isin"]
    df = df[[c for c in keep if c in df.columns]].copy()
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    df["exch_nse"] = True
    return df


def _fetch_bse() -> pd.DataFrame:
    resp = requests.get(BSE_LIST_URL, headers=_BSE_HEADERS, timeout=60)
    resp.raise_for_status()
    data = json.loads(resp.text)
    df = pd.DataFrame(data)
    rename = {
        "SCRIP_CD": "bse_code",
        "Scrip_Name": "company_bse",
        "ISIN_NUMBER": "isin",
        "scrip_id": "bse_symbol",
        "GROUP": "bse_group",
        "FACE_VALUE": "face_value",
        "Issuer_Name": "issuer",
        "Status": "bse_status",
        "INDUSTRY": "industry",
        "Mktcap": "mktcap_cr",  # BSE reports market cap directly in INR crore
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    for c in ("bse_code", "company_bse", "isin", "bse_symbol", "bse_group", "issuer", "bse_status", "industry"):
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    if "mktcap_cr" in df.columns:
        df["mktcap_cr"] = pd.to_numeric(df["mktcap_cr"], errors="coerce")
    if "bse_status" in df.columns:
        df = df[df["bse_status"].str.lower() == "active"]
    df["exch_bse"] = True
    return df


def build_universe(cfg: Config, force: bool = False) -> pd.DataFrame:
    """Return the deduped master security table, rebuilding if stale."""
    out_parquet = cfg.path("universe_dir") / "master_securities.parquet"
    out_csv = cfg.path("universe_dir") / "master_securities.csv"
    refresh_days = int(cfg.get("universe", "refresh_days", default=7))

    if out_parquet.exists() and not force:
        age = time.time() - out_parquet.stat().st_mtime
        if age < refresh_days * 86400:
            return pd.read_parquet(out_parquet)

    source = cfg.get("universe", "source", default="both")
    series_ok = set(cfg.get("universe", "include_series", default=["EQ", "BE"]))

    frames = []
    nse = bse = None
    if source in ("nse", "both"):
        nse = _fetch_nse()
        if series_ok:
            nse = nse[nse["series"].isin(series_ok)]
    if source in ("bse", "both"):
        bse = _fetch_bse()

    master = _merge(nse, bse)

    # Equity sanity: keep only ordinary-equity ISINs (INE...). Rows without a
    # valid ISIN are dropped to avoid ETFs/warrants/bonds leaking in.
    master = master[master["isin"].str.startswith(_ISIN_EQUITY_PREFIX, na=False)]
    master = master.drop_duplicates(subset=["isin"]).reset_index(drop=True)

    master["exchanges"] = master.apply(_exchange_label, axis=1)
    master["active"] = True
    master["built_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    limit = int(cfg.get("universe", "limit", default=0) or 0)
    if limit > 0:
        master = master.head(limit).copy()

    ordered = [
        "isin", "company", "nse_symbol", "bse_code", "bse_symbol",
        "exchanges", "series", "bse_group", "face_value", "mktcap_cr",
        "industry", "active", "built_utc",
    ]
    for c in ordered:
        if c not in master.columns:
            master[c] = pd.NA
    master = master[ordered]

    master.to_parquet(out_parquet, index=False)
    master.to_csv(out_csv, index=False)
    return master


def _merge(nse: pd.DataFrame | None, bse: pd.DataFrame | None) -> pd.DataFrame:
    if nse is not None and bse is not None:
        merged = pd.merge(nse, bse, on="isin", how="outer", suffixes=("", "_bse"))
        merged["company"] = merged["company"].fillna(merged.get("company_bse"))
        merged["company"] = merged["company"].fillna(merged.get("issuer"))
        return merged
    if nse is not None:
        nse["bse_code"] = pd.NA
        return nse
    if bse is not None:
        bse["company"] = bse.get("company_bse")
        bse["nse_symbol"] = pd.NA
        return bse
    raise ValueError("No universe source selected")


def _exchange_label(row: pd.Series) -> str:
    parts = []
    if row.get("exch_nse") is True or pd.notna(row.get("nse_symbol")):
        if str(row.get("nse_symbol", "")).strip() not in ("", "nan", "<NA>"):
            parts.append("NSE")
    if row.get("exch_bse") is True or pd.notna(row.get("bse_code")):
        if str(row.get("bse_code", "")).strip() not in ("", "nan", "<NA>"):
            parts.append("BSE")
    return "+".join(parts) if parts else "?"


def yahoo_ticker(row: pd.Series) -> str | None:
    """Preferred Yahoo Finance ticker for a security.

    NSE symbols use the ``.NS`` suffix; BSE scrip codes use ``.BO``. NSE is
    preferred (deeper liquidity / cleaner data); BSE is the fallback for
    BSE-only listings.
    """
    nse = str(row.get("nse_symbol", "")).strip()
    if nse and nse not in ("nan", "<NA>", "None"):
        return f"{nse}.NS"
    bse = str(row.get("bse_code", "")).strip()
    if bse and bse not in ("nan", "<NA>", "None"):
        # yfinance expects the numeric scrip code for BSE, e.g. 500002.BO
        bse = bse.split(".")[0]
        return f"{bse}.BO"
    return None
