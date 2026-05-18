# dashboard.md

`scripts/dashboard.html` is the only user-facing surface in `aegis-blackbox`. It is one static
HTML file. No server, no build step.

## How it loads data

The page uses `fetch('file://…')` against the four files under `~/.aegis/state/blackbox/`:

- `decisions.jsonl`
- `trades.jsonl`
- `signal_performance.jsonl`
- `decay_report.json`

Because some browsers block `file://` fetches for security, the page degrades gracefully: if a
fetch fails, the relevant panel shows a status banner with a one-line install hint
(`python -m http.server 8000` in `~/.aegis/state/blackbox/`).

## What it shows

1. **Header KPIs** — total decisions, total trades, win rate (realized), open hibernation status,
   most recent decay run timestamp.
2. **Recent trades table** — ts, token (sanitised, `textContent`), chain, side, size USD,
   realized PnL pct, decision_id, sim ok / tx hash.
3. **PnL chart** — cumulative realized PnL pct from `trades.jsonl` × `attribution`.
4. **Decision-reasons histogram** — counts of `gate_failed` reasons + `decision` verbs.
5. **Decay heatmap** — one row per source from `decay_report.json`, coloured `RETIRE` (red),
   `MONITOR` (amber), `ACTIVE` (green). Hover shows `decay_score`, n samples.
6. **Prompt-injection-suspect counter** — number of `prompt_injection_suspect` events seen.

## Library

`Chart.js` from CDN (single `<script>` tag, integrity attribute pinned). No npm install. The page
renders cleanly with Chart.js disabled — tables fall back to plain HTML.

## Untrusted-content handling

Token names, dev labels, and any other free-form CLI string is inserted via `.textContent =`
only. The page never uses `innerHTML` for CLI-sourced data. See
`../../_shared/prompt-injection.md`.

## Hard requirements

- No external HTTP except the Chart.js CDN.
- No cookies, no localStorage of secrets.
- No keys / env values rendered.
- Files load in browser within 2 seconds for up to 100 MB JSONL.
