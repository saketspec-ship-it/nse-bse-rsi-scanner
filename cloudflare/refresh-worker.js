// Cloudflare Worker that powers the dashboard's "Refresh scan" button.
//
// The button on the public GitHub Pages site cannot hold a GitHub token, so it
// POSTs to this Worker instead. The Worker holds the token as a secret and
// fires a `repository_dispatch` event, which triggers .github/workflows/pages.yml
// (a best-effort cloud re-scan + redeploy).
//
// ── Setup ───────────────────────────────────────────────────────────────────
// 1. Create a GitHub fine-grained Personal Access Token scoped to ONLY the
//    `nse-bse-rsi-scanner` repo, with permission: Contents = Read and write
//    (or a classic token with the `repo` scope). Keep it secret.
// 2. Create a Worker (dash.cloudflare.com → Workers → Create) and paste this file.
// 3. Add a Worker secret named GH_TOKEN with that token
//    (Settings → Variables → Add secret), and a plain var GH_REPO =
//    "saketspec-ship-it/nse-bse-rsi-scanner".
// 4. Deploy. Copy the Worker URL (e.g. https://rsi-refresh.<you>.workers.dev).
// 5. In rsi_scanner/dashboard.py set REFRESH_PROXY_URL to that URL, re-scan and
//    redeploy — the Refresh button then appears.
//
// ⚠️ Note: our scan uses Yahoo Finance, which frequently blocks GitHub's cloud
// runners, so a cloud refresh may fail to fetch data (the workflow's guard then
// skips deploy). The reliable updates come from the local scheduled task.

const ALLOW_ORIGIN = "https://saketspec-ship-it.github.io";

export default {
  async fetch(request, env) {
    const cors = {
      "Access-Control-Allow-Origin": ALLOW_ORIGIN,
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };
    if (request.method === "OPTIONS") return new Response(null, { headers: cors });
    if (request.method !== "POST")
      return new Response("POST only", { status: 405, headers: cors });

    const resp = await fetch(`https://api.github.com/repos/${env.GH_REPO}/dispatches`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.GH_TOKEN}`,
        "Accept": "application/vnd.github+json",
        "User-Agent": "rsi-refresh-worker",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ event_type: "refresh" }),
    });

    if (resp.status === 204)
      return new Response("Refresh triggered.", { status: 200, headers: cors });
    const text = await resp.text();
    return new Response(`GitHub error ${resp.status}: ${text}`, { status: 502, headers: cors });
  },
};
