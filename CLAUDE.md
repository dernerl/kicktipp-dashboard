# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Kicktipp football-tipping bot + score/odds tracking + results dashboard (local
and hosted). Split out from [dernerl/kicktipp-mcp](https://github.com/dernerl/kicktipp-mcp)
(see `docs/adr/0009-github-actions-cron-und-vercel-hosting.md`) — that repo
keeps the generic MCP server + Kicktipp client aligned with upstream
`Cloudy261/kicktipp-mcp` for future PRs; this repo has everything specific to
running and displaying this Tippkreis's automation.

- `kicktipp.py` — the HTTP client + all HTML parsing; everything else builds
  on it. **Vendored** (copied, not symlinked/submoduled) from
  `dernerl/kicktipp-mcp` — port parser fixes back there manually when relevant,
  same for `strategies.py`.
- `main.py` — CLI bot, run on a schedule by GitHub Actions
  (`.github/workflows/kicktipp-bot.yml`, replaces the old launchd job);
  strategies in `strategies.py` (`random`, `llm`).
- `dashboard_data.py` — shared, pure payload-building logic (no HTTP, no live Kicktipp access).
- `dashboard.py` — local dev server (full payload incl. personal section) at `http://localhost:8765`.
- `api/data.py` — hosted read-only deployment on Vercel (community-only payload). See ADR 0009.

## Gotchas (Claude will get these wrong otherwise)

- **`kicktipp.py`/`strategies.py` are vendored copies**, not the canonical
  source — that's `dernerl/kicktipp-mcp`. If you're fixing a Kicktipp
  HTML-parsing bug or improving the LLM prompt, consider whether the fix
  belongs upstream (in the fork) too, and port it manually — there's no
  automated sync between the two repos (deliberate: cross-repo checkout in the
  cron workflow was considered and rejected as more complex than it's worth
  for a file that rarely changes; see ADR 0009).
- **Non-standard scoring (4/3/2/0).** This community scores **4 = exact, 3 = correct
  goal difference (non-draw), 2 = correct tendency (incl. a non-exact draw), 0 = wrong** —
  NOT the standard Kicktipp 3/2/1. `tracking._points` implements this scheme
  (verified 1:1 against the live cell points in `community_tips.jsonl`). Tip-outcome
  classification (`dashboard_data._enrich_tip` `status`, and *Verrückte Tipps*) is done by
  tip-vs-result, so it's correct regardless of the point values. See ADR 0005.
- **Bookmaker odds: live forward-capture + retroactive backfill.** Kicktipp shows the
  ODDSET 1/X/2 odds on the Tippabgabe page for *every* Spieltag, including already-played
  ones (table `tippabgabeSpiele`). `odds_history.record_odds` upserts open-match odds each
  run; `odds_history.backfill_odds` pulls the real historical odds for all Spieltage in one
  pass (`KicktippClient.fetch_all_odds`). Stored in `data/odds_history.jsonl`. (Earlier docs
  wrongly claimed odds couldn't be backfilled — see ADR 0007.)
- **`data/` is tracked, not gitignored.** The GitHub Actions workflow commits
  `data/*.jsonl` (+ `data/status.json`) back to `main` on every run — that's
  the persistence layer the hosted Vercel dashboard reads from. See ADR 0009.
  This does **not** include `~/Library/Logs/kicktipp-ai.log` (Claude's
  reasoning) — that file only ever exists locally and is never committed.
- **Personal section stays local, structurally not just visually.**
  `dashboard_data.build_payload(include_personal=False)` (used by `api/data.py`)
  skips computing `tips`/`summary`/reasoning entirely rather than hiding them in
  the frontend — don't reintroduce them into the community-only path even for
  convenience. `web/dashboard.html` renders `sectionPersonal()` only when
  `DATA.local` is true.
- **Historical standings/tips are reconstructed**, not stored: scraped from each
  per-Spieltag `tippuebersicht` page (table `id="ranking"`, per-match `<sub class="p">`
  point cells). The Gesamtübersicht's `spieltagIndex` param is ignored by Kicktipp.

## Commands

```bash
uv run python main.py --strategy random --dry-run    # bot, prints tips, submits nothing
uv run python ranking_history.py                     # rebuild dashboard data (logs in once)
uv run python odds_history.py --backfill             # pull real historical odds (all Spieltage)
uv run python dashboard.py                            # serve dashboard at http://localhost:8765
uv run python -m py_compile <files>                  # quick sanity check (no test suite)
```

Credentials live in `.env` (`KICKTIPP_EMAIL`/`PASSWORD`/`COMMUNITY`), gitignored.

## Conventions

- **No new dependencies.** Stdlib + the existing three (`requests`, `beautifulsoup4`,
  `python-dotenv`). The dashboard server is stdlib `http.server`; its frontend
  is one vanilla-JS/SVG file (`web/dashboard.html`), no build step. `api/` has its own
  scoped `requirements.txt` (empty — stdlib only) so Vercel's Python build doesn't
  pull in the bot's `requests`/`beautifulsoup4`/`python-dotenv`.
- **Don't touch the tipping/scoring path casually** (`strategies.py` selection,
  `tracking._points`) — changing scoring rewrites historical comparisons.
- **Record non-trivial decisions as ADRs** (Nygard format) in `docs/adr/`.
- There is no automated test suite; verify by running the commands above (dry-run for
  the bot, headless Chrome or a reload for the dashboard).
