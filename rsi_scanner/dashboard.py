"""Dashboard generator.

Two emission modes from one shell:
  * ``render_embedded`` -> a single self-contained ``dashboard.html`` (data
    inlined) for opening directly from disk / inline preview.
  * ``write_site`` -> a GitHub Pages bundle: ``index.html`` (app shell) plus
    ``data.json`` and ``meta.json`` fetched at runtime, so the shell stays tiny
    and the daily payload is a separate file.

Features: every column is sortable (click header) AND filterable (a filter box
per column — numeric boxes accept ``>60``, ``<15``, ``40-60`` or a plain number
meaning ``>=``; text boxes match substrings; category is a dropdown). Includes
a "Days in Signal" column (trading days the stock has continuously met the
condition) and a per-stock detail modal.
"""

from __future__ import annotations

import json
from datetime import datetime

from .config import Config
from .screener import ScreenResult


def build_payload(results: list[ScreenResult]) -> list[dict]:
    rows = []
    for r in results:
        d = r.to_row()
        d["chart"] = (
            f"https://www.tradingview.com/chart/?symbol=NSE:{r.nse_symbol}"
            if r.nse_symbol else
            (f"https://www.tradingview.com/chart/?symbol=BSE:{r.bse_code}" if r.bse_code else "")
        )
        rows.append(d)
    return rows


def build_meta(cfg: Config, recon: dict, scanned: int, backtest_summary: dict | None, results=None) -> dict:
    th = cfg.thresholds
    n_crossover = sum(1 for r in (results or []) if getattr(r, "pure_crossover_1m", False))
    return {
        "timestamp": recon["timestamp"],
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "scanned": scanned,
        "n_active": len(recon["active"]),
        "n_new": len(recon["new"]),
        "n_exited": len(recon["exited"]),
        "n_strong": len(recon["strong"]),
        "n_crossover": n_crossover,
        "new_isins": [r.isin for r in recon["new"]],
        "thresholds": {k: float(v) for k, v in th.items()},
        "confirmed_only": bool(cfg.get("candles", "confirmed_only", default=True)),
        "backtest": (backtest_summary or {}).get("overall") if backtest_summary else None,
    }


def render_embedded(cfg, results, recon, scanned, backtest_summary=None) -> str:
    data = json.dumps(build_payload(results))
    meta = json.dumps(build_meta(cfg, recon, scanned, backtest_summary, results))
    loader = f"<script>window.__META__={meta};window.__DATA__={data};</script>"
    return _SHELL.replace("<!--DATA_LOADER-->", loader)


def write_site(cfg, out_dir, results, recon, scanned, backtest_summary=None) -> str:
    """Write index.html + data.json + meta.json into ``out_dir`` (a Path)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "data.json").write_text(json.dumps(build_payload(results)), encoding="utf-8")
    (out_dir / "meta.json").write_text(json.dumps(build_meta(cfg, recon, scanned, backtest_summary, results)), encoding="utf-8")
    loader = (
        "<script>"
        "window.__LOAD__=Promise.all(["
        "fetch('meta.json').then(r=>r.json()),"
        "fetch('data.json').then(r=>r.json())"
        "]).then(([m,d])=>{window.__META__=m;window.__DATA__=d;});"
        "</script>"
    )
    html = _SHELL.replace("<!--DATA_LOADER-->", loader)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    return str(out_dir / "index.html")


# Back-compat: scan.py may still call render().
def render(cfg, results, recon, scanned, backtest_summary=None) -> str:
    return render_embedded(cfg, results, recon, scanned, backtest_summary)


_SHELL = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NSE + BSE RSI Momentum Scanner</title>
<style>
:root{
  --bg:#f6f7f9;--card:#fff;--ink:#1a1d24;--muted:#5b6472;--line:#e4e7ec;
  --grn:#0f9d58;--grn-bg:#e6f4ea;--blu:#1a73e8;--blu-bg:#e8f0fe;
  --yel:#b7791f;--yel-bg:#fef3c7;--red:#9aa0a6;--red-bg:#f1f3f4;
  --gry:#9aa0a6;--accent:#0b5cff;--shadow:0 1px 3px rgba(0,0,0,.08);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0f1216;--card:#171b21;--ink:#e6e9ef;--muted:#9aa4b2;--line:#262c35;
  --grn:#3ecf8e;--grn-bg:#0f2e21;--blu:#5b9dff;--blu-bg:#12233f;
  --yel:#f0c04a;--yel-bg:#332a12;--red:#7b828c;--red-bg:#1c2129;
  --accent:#4d8bff;--shadow:0 1px 3px rgba(0,0,0,.4);
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1600px;margin:0 auto;padding:20px 16px 60px}
header h1{font-size:22px;margin:0 0 2px}
header .sub{color:var(--muted);font-size:13px}
.cond{margin:14px 0;padding:12px 16px;background:var(--grn-bg);border:1px solid var(--line);
  border-radius:10px;font-weight:600}
.cond small{font-weight:400;color:var(--muted);display:block;margin-top:3px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:14px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;box-shadow:var(--shadow)}
.tile .n{font-size:26px;font-weight:700}
.tile .l{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.03em}
.tile.new .n{color:var(--grn)}.tile.strong .n{color:var(--blu)}.tile.exit .n{color:var(--yel)}
.chips{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0}
.chips input[type=text]{background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 10px;font-size:13px;min-width:200px}
.chip{display:inline-flex;align-items:center;gap:6px;background:var(--card);border:1px solid var(--line);border-radius:999px;padding:5px 11px;font-size:13px;cursor:pointer;user-select:none}
.chip input{margin:0}
.chip.on{background:var(--blu-bg);border-color:var(--blu);color:var(--blu)}
button.reset{background:transparent;border:1px solid var(--line);color:var(--muted);border-radius:8px;padding:6px 12px;cursor:pointer;font-size:13px}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0 2px}
.toolbar button{background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 12px;cursor:pointer;font-size:13px}
.toolbar button:hover:not(:disabled){background:var(--blu-bg);border-color:var(--blu)}
.toolbar button:disabled{opacity:.5;cursor:default}
#refresh-status{font-size:12px;color:var(--muted)}
#visitor-counts{font-size:12px;color:var(--muted);margin:2px 0 8px}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card);box-shadow:var(--shadow)}
table{border-collapse:collapse;width:100%;font-size:13px;min-width:1180px}
th,td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th.l,td.l{text-align:left}
thead th{position:sticky;top:0;background:var(--card);cursor:pointer;user-select:none;font-weight:600;z-index:2}
thead th:hover{color:var(--accent)}
thead tr.filt th{position:sticky;top:33px;background:var(--card);z-index:2;padding:4px 6px;cursor:auto}
thead tr.filt input,thead tr.filt select{width:100%;min-width:56px;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:3px 5px;font-size:12px}
tbody tr:hover{background:var(--blu-bg);cursor:pointer}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600}
.b-strong{background:var(--blu-bg);color:var(--blu)}.b-primary{background:var(--grn-bg);color:var(--grn)}
.b-watch{background:var(--yel-bg);color:var(--yel)}.b-none{background:var(--red-bg);color:var(--red)}
.b-insuff{background:var(--red-bg);color:var(--gry)}
.b-cross{background:transparent;color:var(--accent);border:1px solid var(--accent);font-weight:700}
.new-dot{color:var(--grn);font-weight:700}.prov{color:var(--yel);font-size:11px}
.muted{color:var(--muted)}.sortarrow{font-size:10px;opacity:.7}
.days{font-weight:600}.rsi-ok{color:var(--grn);font-weight:600}
.disc{margin-top:16px;padding:12px 14px;border:1px dashed var(--line);border-radius:10px;background:var(--card);color:var(--muted)}
footer{margin-top:22px;color:var(--muted);font-size:12px}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.5);display:none;align-items:center;justify-content:center;padding:16px;z-index:10}
.modal.open{display:flex}
.modal .box{background:var(--card);border:1px solid var(--line);border-radius:14px;max-width:560px;width:100%;padding:20px;box-shadow:0 10px 40px rgba(0,0,0,.3)}
.modal h3{margin:0 0 2px}
.modal .grid{display:grid;grid-template-columns:1fr 1fr;gap:6px 18px;margin:14px 0}
.modal .grid div{display:flex;justify-content:space-between;border-bottom:1px solid var(--line);padding:4px 0}
.modal .grid span{color:var(--muted)}
.modal a.btn{display:inline-block;margin-top:8px;background:var(--accent);color:#fff;text-decoration:none;padding:8px 14px;border-radius:8px;font-weight:600}
.modal .close{float:right;cursor:pointer;color:var(--muted);font-size:20px}
.tag{font-size:11px;color:var(--muted)}
#loading{padding:40px;text-align:center;color:var(--muted)}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>NSE + BSE RSI Momentum Scanner</h1>
  <div class="sub" id="sub">Loading…</div>
</header>
<div class="cond" id="cond"></div>
<div class="tiles" id="tiles"></div>

<div class="chips">
  <input type="text" id="q" placeholder="Search company / NSE / BSE…">
  <span class="chip" id="chSig"><input type="checkbox" id="fSig"> Signal only</span>
  <span class="chip" id="chNew"><input type="checkbox" id="fNew"> New only</span>
  <span class="chip" id="chStrong"><input type="checkbox" id="fStrong"> Strong only</span>
  <span class="chip" id="chCross"><input type="checkbox" id="fCross"> ⚡ Pure 1M crossover</span>
  <button class="reset" id="reset">Reset filters</button>
  <span class="tag" id="count"></span>
</div>

<div class="toolbar">
  <button id="refresh-btn" onclick="triggerRefresh()" hidden>&#8635; Refresh scan</button>
  <button id="csv-btn" onclick="downloadCsv()">&#8681; CSV</button>
  <button id="excel-btn" onclick="downloadExcel()">&#8681; Excel</button>
  <span id="refresh-status"></span>
</div>
<div id="visitor-counts">Visitors today: <span id="vc-today">-</span> &middot; All-time: <span id="vc-total">-</span> &middot; Downloads: <span id="vc-downloads">-</span> <span style="opacity:.6">(may lag up to 4h)</span></div>

<div class="tablewrap">
<table id="tbl">
<thead>
  <tr id="hrow"></tr>
  <tr class="filt" id="frow"></tr>
</thead>
<tbody id="tbody"><tr><td id="loading" colspan="17">Loading data…</td></tr></tbody>
</table>
</div>

<div class="disc">
  <strong>Disclaimer.</strong> Technical screening &amp; alert system, <b>not investment advice</b>.
  An RSI signal alone is not a buy/sell recommendation. RSI uses Wilder's method on split/bonus-adjusted
  closes; weekly/monthly signals use completed candles. End-of-day data from Yahoo Finance may have gaps
  for illiquid or newly listed scrips. Many micro/penny stocks can satisfy the raw RSI condition (RSI pins
  near 100 on circuit-limit moves) — use the Market Cap column filter to focus on liquid names.
</div>
<footer>
  Categories: 🔴 No Signal · 🟡 Watchlist · 🟢 Primary Signal · 🔵 Strong Momentum · ⚪ Insufficient Data.
  Every column sorts (click header) and filters (box below it; numeric boxes accept <code>&gt;60</code>,
  <code>&lt;15</code>, <code>40-60</code>, or a number = ≥). Click any row for details.
  <br><b>RSI 1M</b> = last <i>completed</i> monthly candle (drives the signal, per the completed-candle rule).
  <b>1M live</b> = current in-progress month (matches a live chart). <b>Days since 1M&gt;60</b> uses the
  <i>live</i> value, so it is blank when the live monthly RSI is not currently above 60 — even if the last
  completed candle was.
</footer>
</div>

<div class="modal" id="modal"><div class="box" id="mbox"></div></div>

<!--DATA_LOADER-->
<script>
const COLS=[
 {k:'rank',label:'#',type:'rank',align:'r'},
 {k:'company',label:'Company',type:'text',align:'l'},
 {k:'nse_symbol',label:'NSE',type:'text',align:'l'},
 {k:'bse_code',label:'BSE',type:'text',align:'l'},
 {k:'price',label:'Price ₹',type:'num',align:'r'},
 {k:'market_cap_cr',label:'MCap Cr',type:'num',align:'r'},
 {k:'pe',label:'P/E',type:'num',align:'r'},
 {k:'rsi_1d',label:'RSI 1D',type:'num',align:'r'},
 {k:'rsi_1w',label:'RSI 1W',type:'num',align:'r'},
 {k:'rsi_1m',label:'RSI 1M',type:'num',align:'r'},
 {k:'live_rsi_1m',label:'1M live',type:'num',align:'r'},
 {k:'momentum_score',label:'Score',type:'num',align:'r'},
 {k:'days_since_1m_cross60',label:'Days since 1M>60',type:'num',align:'r'},
 {k:'pure_crossover_1m',label:'Pure 1M x-over',type:'bool',align:'r'},
 {k:'days_in_signal',label:'Days in Signal',type:'num',align:'r'},
 {k:'category',label:'Signal',type:'cat',align:'l'},
 {k:'last_date',label:'Updated',type:'text',align:'l'},
];
const CATS=['Strong Momentum','Primary Signal','Watchlist','No Signal','Insufficient Data'];
const CATCLASS={'Strong Momentum':'b-strong','Primary Signal':'b-primary','Watchlist':'b-watch','No Signal':'b-none','Insufficient Data':'b-insuff'};
const CATEMOJI={'Strong Momentum':'🔵','Primary Signal':'🟢','Watchlist':'🟡','No Signal':'🔴','Insufficient Data':'⚪'};

let DATA=[],META={},NEW=new Set();
let sortKey='market_cap_cr',sortDir=-1;
const filters={};

function esc(s){return (s==null?'':String(s)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function fnum(v,nd){return (v==null||v==='')?'<span class=muted>–</span>':Number(v).toLocaleString('en-IN',{maximumFractionDigits:nd,minimumFractionDigits:nd});}

function matchNum(v,expr){
  expr=(expr||'').trim(); if(!expr) return true;
  if(expr.toLowerCase()==='na') return v==null;
  if(v==null||v==='') return false; v=Number(v);
  let m;
  if(m=expr.match(/^(>=|<=|>|<)\s*(-?\d+\.?\d*)$/)){const t=+m[2],op=m[1];
    return op==='>'?v>t:op==='>='?v>=t:op==='<'?v<t:v<=t;}
  if(m=expr.match(/^(-?\d+\.?\d*)\s*-\s*(-?\d+\.?\d*)$/)) return v>=+m[1]&&v<=+m[2];
  if(m=expr.match(/^=?\s*(-?\d+\.?\d*)$/)) return v>=+m[1];
  return true;
}
function matchText(v,expr){expr=(expr||'').trim().toLowerCase(); if(!expr) return true; return String(v==null?'':v).toLowerCase().includes(expr);}

function passes(d){
  const q=document.getElementById('q').value.trim().toLowerCase();
  if(q){const s=(d.company+' '+(d.nse_symbol||'')+' '+(d.bse_code||'')).toLowerCase(); if(!s.includes(q)) return false;}
  if(document.getElementById('fSig').checked && !d.rsi_signal) return false;
  if(document.getElementById('fNew').checked && !d.is_new) return false;
  if(document.getElementById('fStrong').checked && d.category!=='Strong Momentum') return false;
  if(document.getElementById('fCross').checked && !d.pure_crossover_1m) return false;
  for(const c of COLS){
    const ex=filters[c.k]; if(!ex) continue;
    if(c.type==='num'){ if(!matchNum(d[c.k],ex)) return false; }
    else if(c.type==='cat'){ if(d.category!==ex) return false; }
    else if(c.type==='bool'){ if(ex==='yes'&&!d[c.k]) return false; if(ex==='no'&&d[c.k]) return false; }
    else if(c.type==='text'){ if(!matchText(d[c.k],ex)) return false; }
  }
  return true;
}
function sorted(rows){
  return rows.sort((a,b)=>{
    let x=a[sortKey],y=b[sortKey];
    if(x==null) x=(typeof y==='string')?'':-Infinity;
    if(y==null) y=(typeof x==='string')?'':-Infinity;
    if(typeof x==='string'||typeof y==='string') return sortDir*String(x).localeCompare(String(y));
    return sortDir*(x-y);
  });
}
function render(){
  const rows=sorted(DATA.filter(passes));
  document.getElementById('count').textContent=rows.length.toLocaleString('en-IN')+' / '+DATA.length.toLocaleString('en-IN')+' stocks';
  const tb=document.getElementById('tbody');
  const frag=rows.slice(0,3000).map((d,i)=>{
    const cls=CATCLASS[d.category]||'b-none';
    const nb=d.is_new?'<span class="new-dot">● NEW </span>':'';
    const prov=d.provisional?'<span class="prov"> PROV</span>':'';
    const days=d.days_in_signal!=null?('<span class="days">'+d.days_in_signal+'</span>'):'<span class=muted>–</span>';
    return '<tr data-isin="'+esc(d.isin)+'">'+
      '<td>'+(i+1)+'</td>'+
      '<td class="l">'+nb+esc(d.company)+'</td>'+
      '<td class="l">'+(d.nse_symbol||'<span class=muted>–</span>')+'</td>'+
      '<td class="l">'+(d.bse_code||'<span class=muted>–</span>')+'</td>'+
      '<td>'+fnum(d.price,2)+'</td>'+
      '<td>'+fnum(d.market_cap_cr,0)+'</td>'+
      '<td>'+(d.pe==null?'<span class=muted>N/A</span>':Number(d.pe).toFixed(1))+'</td>'+
      '<td>'+fnum(d.rsi_1d,1)+'</td>'+
      '<td>'+fnum(d.rsi_1w,1)+'</td>'+
      '<td>'+fnum(d.rsi_1m,1)+'</td>'+
      '<td class="'+(d.live_rsi_1m!=null&&d.live_rsi_1m>60?'rsi-ok':'muted')+'">'+fnum(d.live_rsi_1m,1)+'</td>'+
      '<td>'+fnum(d.momentum_score,1)+'</td>'+
      '<td>'+(d.days_since_1m_cross60!=null?d.days_since_1m_cross60:'<span class=muted>–</span>')+'</td>'+
      '<td>'+(d.pure_crossover_1m?'<span class="badge b-cross">⚡ CROSS</span>':'<span class=muted>–</span>')+'</td>'+
      '<td>'+days+'</td>'+
      '<td class="l"><span class="badge '+cls+'">'+(CATEMOJI[d.category]||'')+' '+d.category+'</span>'+prov+'</td>'+
      '<td class="l muted">'+(d.last_date||'–')+'</td></tr>';
  }).join('');
  tb.innerHTML=frag + (rows.length>3000?'<tr><td class="l muted" colspan="17">… '+(rows.length-3000).toLocaleString('en-IN')+' more rows hidden — filter to narrow.</td></tr>':'');
}
function buildHead(){
  document.getElementById('hrow').innerHTML=COLS.map(c=>{
    const arrow=(c.k===sortKey)?(' <span class="sortarrow">'+(sortDir<0?'▼':'▲')+'</span>'):'';
    return '<th class="'+(c.align==='l'?'l':'')+'" data-k="'+c.k+'">'+c.label+arrow+'</th>';
  }).join('');
  document.getElementById('frow').innerHTML=COLS.map(c=>{
    if(c.type==='rank') return '<th></th>';
    if(c.type==='cat') return '<th><select data-k="'+c.k+'"><option value="">All</option>'+CATS.map(x=>'<option>'+x+'</option>').join('')+'</select></th>';
    if(c.type==='bool') return '<th><select data-k="'+c.k+'"><option value="">All</option><option value="yes">Yes</option><option value="no">No</option></select></th>';
    const ph=c.type==='num'?'>60':'text';
    return '<th><input data-k="'+c.k+'" placeholder="'+ph+'"></th>';
  }).join('');
  document.querySelectorAll('#hrow th').forEach(th=>th.onclick=()=>{
    const k=th.dataset.k; if(k==='rank') return;
    if(sortKey===k) sortDir*=-1; else{sortKey=k; sortDir=(COLS.find(c=>c.k===k).type==='num')?-1:1;}
    buildHead(); render();
  });
  document.querySelectorAll('#frow input,#frow select').forEach(el=>{
    el.value=filters[el.dataset.k]||'';
    const ev=el.tagName==='SELECT'?'change':'input';
    el.addEventListener(ev,()=>{filters[el.dataset.k]=el.value; render();});
  });
}
function buildTop(){
  const th=META.thresholds||{monthly_gt:60,weekly_gt:40,daily_gt:40};
  document.getElementById('sub').innerHTML='Last scan: '+esc(META.timestamp)+' IST · Mode: '+(META.confirmed_only?'Confirmed candles':'PROVISIONAL')+' · Data: Yahoo Finance (adjusted OHLC) · Generated '+esc(META.generated);
  document.getElementById('cond').innerHTML='Primary signal — 1M RSI &gt; '+th.monthly_gt+' &nbsp;AND&nbsp; 1W RSI &gt; '+th.weekly_gt+' &nbsp;AND&nbsp; 1D RSI &gt; '+th.daily_gt+
    '<small>Which NSE/BSE stocks show strong long-term momentum while keeping healthy daily &amp; weekly momentum?</small>';
  const T=[['scanned','Scanned',''],['n_new','🚨 New Signals','new'],['n_active','🟢 In Signal',''],['n_strong','🔵 Strong','strong'],['n_crossover','⚡ Pure 1M X-overs','strong'],['n_exited','Exited','exit']];
  document.getElementById('tiles').innerHTML=T.map(([k,l,c])=>'<div class="tile '+c+'"><div class="n">'+(META[k]!=null?Number(META[k]).toLocaleString('en-IN'):'–')+'</div><div class="l">'+l+'</div></div>').join('');
}
function trend(cur,prev){if(cur==null||prev==null) return ''; const d=cur-prev,a=d>0?'▲':(d<0?'▼':'▬'); return ' <span class="tag">'+a+' '+d.toFixed(1)+' vs prev</span>';}
function openModal(d){
  const b=document.getElementById('mbox');
  const R=(k,v)=>'<div><span>'+k+'</span><b>'+v+'</b></div>';
  b.innerHTML='<span class="close" onclick="closeModal()">×</span><h3>'+esc(d.company)+'</h3>'+
   '<div class="tag">'+esc(d.exchanges)+' · ISIN '+esc(d.isin)+' · '+esc(d.sector||'Sector N/A')+' / '+esc(d.industry||'—')+'</div>'+
   '<div class="grid">'+
   R('NSE',esc(d.nse_symbol||'–'))+R('BSE',esc(d.bse_code||'–'))+
   R('Price',d.price!=null?'₹'+Number(d.price).toFixed(2):'N/A')+
   R('Market Cap',d.market_cap_cr!=null?('₹'+Number(d.market_cap_cr).toLocaleString('en-IN')+' Cr ('+esc(d.mcap_class)+')'):'N/A')+
   R('P/E',d.pe!=null?Number(d.pe).toFixed(1)+' ('+esc(d.pe_type)+')':'N/A / Negative Earnings')+
   R('Forward P/E',d.forward_pe!=null?Number(d.forward_pe).toFixed(1):'–')+
   R('RSI 1D',(d.rsi_1d!=null?d.rsi_1d.toFixed(1):'–')+trend(d.rsi_1d,d.prev_rsi_1d))+
   R('RSI 1W',(d.rsi_1w!=null?d.rsi_1w.toFixed(1):'–')+trend(d.rsi_1w,d.prev_rsi_1w))+
   R('RSI 1M (confirmed)',(d.rsi_1m!=null?d.rsi_1m.toFixed(1):'–')+trend(d.rsi_1m,d.prev_rsi_1m))+
   R('RSI 1M (live)',(d.live_rsi_1m!=null?d.live_rsi_1m.toFixed(1)+(d.live_rsi_1m>60?' ▲>60':' <60'):'–'))+
   R('Momentum Score',d.momentum_score!=null?d.momentum_score:'–')+
   R('Days since 1M&gt;60 (live)',d.days_since_1m_cross60!=null?(d.days_since_1m_cross60+' days'+(d.months_since_1m_cross60!=null?' ('+d.months_since_1m_cross60+' mo)':'')):'not above 60')+
   R('1M crossed 60 on',esc(d.m1_cross_date||'—'))+
   R('Pure 1M crossover',d.pure_crossover_1m?'⚡ Yes — clean cross (was &lt;60 for 6 mo)':'No')+
   R('Days in Signal',d.days_in_signal!=null?d.days_in_signal+' trading days':'—')+
   R('In signal since',esc(d.signal_since||'—'))+
   R('Signal',(CATEMOJI[d.category]||'')+' '+esc(d.category))+
   R('Updated',esc(d.last_date||'–'))+'</div>'+
   ((d.data_flags&&d.data_flags.length)?'<div class="tag" style="color:var(--yel)">⚠ '+esc(d.data_flags.join(' · '))+'</div>':'')+
   (d.chart?'<a class="btn" href="'+d.chart+'" target="_blank" rel="noopener">Open chart (1D/1W/1M/…) ↗</a>':'');
  document.getElementById('modal').classList.add('open');
}
function closeModal(){document.getElementById('modal').classList.remove('open');}

// ---- toolbar: config + CSV/Excel export + visitor counter + refresh -------
// Reuses the existing GoatCounter site with an /rsi* path prefix so these
// counts stay separate from the VCP dashboard. Point GOATCOUNTER at a
// dedicated site if you prefer. Set REFRESH_PROXY_URL to your Cloudflare
// Worker URL to reveal the "Refresh scan" button.
const GOATCOUNTER='https://vcpdash.goatcounter.com';
const GC='/rsi';
const REFRESH_PROXY_URL='';

const EXPORT_COLS=[
 ['company','Company'],['nse_symbol','NSE'],['bse_code','BSE'],['isin','ISIN'],
 ['price','Price'],['market_cap_cr','MarketCap_Cr'],['mcap_class','Cap'],['pe','PE'],
 ['rsi_1d','RSI_1D'],['rsi_1w','RSI_1W'],['rsi_1m','RSI_1M_confirmed'],['live_rsi_1m','RSI_1M_live'],
 ['momentum_score','Score'],['days_since_1m_cross60','DaysSince_1M_gt60'],['m1_cross_date','Crossed60On'],
 ['pure_crossover_1m','PureCrossover'],['days_in_signal','DaysInSignal'],['signal_since','InSignalSince'],
 ['category','Signal'],['sector','Sector'],['industry','Industry'],['last_date','Updated'],
];
function exportRows(){ return sorted(DATA.filter(passes)); }
function todayStr(){ return new Date().toISOString().slice(0,10); }
function fname(ext){ return 'nse_bse_rsi_'+todayStr()+'.'+ext; }
function triggerDownload(blob,fn){ const u=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=u; a.download=fn; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(u); }
function recordDownload(){ if(!GOATCOUNTER) return; const i=new Image(); i.src=GOATCOUNTER+'/count?p='+encodeURIComponent(GC+'-download')+'&t='+encodeURIComponent(document.title+' download'); }
function downloadCsv(){ recordDownload(); const rows=exportRows(); if(!rows.length) return;
  const esc=v=>{ if(v===null||v===undefined) v=''; if(typeof v==='boolean') v=v?'Yes':''; return '"'+String(v).replace(/"/g,'""')+'"'; };
  const lines=[EXPORT_COLS.map(c=>esc(c[1])).join(',')];
  rows.forEach(r=>lines.push(EXPORT_COLS.map(c=>esc(r[c[0]])).join(',')));
  triggerDownload(new Blob([lines.join('\r\n')],{type:'text/csv;charset=utf-8;'}), fname('csv')); }
function downloadExcel(){ recordDownload(); const rows=exportRows(); if(!rows.length) return;
  const xe=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&apos;');
  const cell=v=>{ if(typeof v==='boolean') v=v?'Yes':''; const t=(typeof v==='number')?'Number':'String'; const txt=(v===null||v===undefined)?'':v; return '<Cell><Data ss:Type="'+t+'">'+xe(txt)+'</Data></Cell>'; };
  const hdr='<Row>'+EXPORT_COLS.map(c=>'<Cell><Data ss:Type="String">'+xe(c[1])+'</Data></Cell>').join('')+'</Row>';
  const body=rows.map(r=>'<Row>'+EXPORT_COLS.map(c=>cell(r[c[0]])).join('')+'</Row>').join('');
  const xml='<?xml version="1.0"?><?mso-application progid="Excel.Sheet"?>'+
    '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'+
    '<Worksheet ss:Name="RSI Scan"><Table>'+hdr+body+'</Table></Worksheet></Workbook>';
  triggerDownload(new Blob([xml],{type:'application/vnd.ms-excel;charset=utf-8;'}), fname('xls')); }
function triggerRefresh(){ const b=document.getElementById('refresh-btn'), s=document.getElementById('refresh-status');
  if(!REFRESH_PROXY_URL){ s.textContent='Refresh not configured.'; return; }
  b.disabled=true; s.textContent='Triggering a full re-scan...';
  fetch(REFRESH_PROXY_URL,{method:'POST'}).then(r=>r.text().then(t=>({ok:r.ok,text:t}))).then(res=>{
    s.textContent=res.ok?'Triggered. Cloud scan runs (best-effort) — reload in a few minutes.':'Trigger failed: '+res.text;
    if(!res.ok) b.disabled=false;
  }).catch(()=>{ s.textContent='Trigger failed (network).'; b.disabled=false; });
  setTimeout(()=>{b.disabled=false;},120000); }
function initCounter(){ if(!GOATCOUNTER) return; const d=todayStr();
  const rec=p=>{ const i=new Image(); i.src=GOATCOUNTER+'/count?p='+encodeURIComponent(p)+'&t='+encodeURIComponent(document.title); };
  const show=(p,el)=>fetch(GOATCOUNTER+'/counter/'+encodeURIComponent(p)+'.json').then(r=>r.json()).then(x=>{document.getElementById(el).textContent=x.count||'0';}).catch(()=>{document.getElementById(el).textContent='?';});
  rec(GC+'-lifetime'); rec(GC+'-daily/'+d);
  show(GC+'-lifetime','vc-total'); show(GC+'-daily/'+d,'vc-today'); show(GC+'-download','vc-downloads'); }

function boot(){
  DATA=window.__DATA__||[]; META=window.__META__||{};
  NEW=new Set(META.new_isins||[]);
  DATA.forEach(d=>d.is_new=NEW.has(d.isin));
  buildTop(); buildHead(); render();
  ['q','fSig','fNew','fStrong','fCross'].forEach(id=>{const el=document.getElementById(id);
    el.addEventListener(el.type==='checkbox'?'change':'input',render);});
  [['fSig','chSig'],['fNew','chNew'],['fStrong','chStrong'],['fCross','chCross']].forEach(([f,c])=>{
    document.getElementById(f).addEventListener('change',()=>document.getElementById(c).classList.toggle('on',document.getElementById(f).checked));
  });
  document.getElementById('reset').onclick=()=>{
    for(const k in filters) delete filters[k];
    document.getElementById('q').value='';
    ['fSig','fNew','fStrong','fCross'].forEach(id=>{document.getElementById(id).checked=false;});
    ['chSig','chNew','chStrong','chCross'].forEach(id=>document.getElementById(id).classList.remove('on'));
    buildHead(); render();
  };
  document.getElementById('tbody').onclick=e=>{const tr=e.target.closest('tr[data-isin]'); if(!tr) return; const d=DATA.find(x=>x.isin===tr.dataset.isin); if(d) openModal(d);};
  document.getElementById('modal').onclick=e=>{if(e.target.id==='modal') closeModal();};
  document.addEventListener('keydown',e=>{if(e.key==='Escape') closeModal();});
  if(REFRESH_PROXY_URL) document.getElementById('refresh-btn').hidden=false;
  initCounter();
}
(window.__LOAD__||Promise.resolve()).then(boot).catch(e=>{document.getElementById('loading').textContent='Failed to load data.json: '+e;});
</script>
</body>
</html>
"""
