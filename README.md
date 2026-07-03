# kicktipp-dashboard

Automated [Kicktipp](https://www.kicktipp.de/) football tipping bot (LLM
strategy), score/odds tracking, and a results dashboard (local + hosted).

> Built on top of [dernerl/kicktipp-mcp](https://github.com/dernerl/kicktipp-mcp)
> (itself a fork of [Cloudy261/kicktipp-mcp](https://github.com/Cloudy261/kicktipp-mcp)),
> which provides the Kicktipp HTTP client (`kicktipp.py`) and an MCP server for
> Claude Desktop. This repo vendors a copy of `kicktipp.py`/`strategies.py` and
> builds the automated bot, score tracking, and dashboard on top — see
> `docs/adr/0009-github-actions-cron-und-vercel-hosting.md` for why this became
> its own repo instead of living inside the fork.

> ⚠️ Use responsibly and at your own risk. Automating logins to a third-party site may be against Kicktipp's terms of service. This is a personal hobby project.

## Features

- **CLI bot** (`main.py`) — fills in tips on a schedule. Two strategies:
  - `random` — weighted Poisson scoreline sampling
  - `llm` — shells out to the Claude Code CLI (`claude -p`) to predict scores
    with web search; fetches completed match results from Kicktipp and injects
    team form (goals, W/D/L, points) into the prompt as tournament context
- **Score/odds tracking** (`tracking.py`, `odds_history.py`, `ranking_history.py`)
  — every submitted tip + bookmaker odds snapshot + the community's full
  standings history, reconstructed match-by-match.
- **Dashboard** — a zero-dependency web page: a match-by-match
  position-over-time chart, the whole community's "craziest" tips, a season
  "Trophäenschrank", and (locally only) a personal section. Runs locally
  (`dashboard.py`) or hosted read-only on Vercel (`api/data.py`).

> **Scoring:** this Tipprunde uses **4 / 3 / 2 / 0** — not the standard Kicktipp
> 3 / 2 / 1. Exact score = 4, right goal-difference (non-draw) = 3, right tendency
> (incl. non-exact draws) = 2, wrong tendency = 0. `tracking._points` and the
> dashboard's personal section both use this scheme.

## Requirements

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (recommended) or plain `pip`
- A Kicktipp account and a community you're a member of
- For the `llm` strategy: the [Claude Code CLI](https://docs.claude.com/en/docs/claude-code) on your PATH

## Setup

1. **Install dependencies**

   ```bash
   uv sync          # or: pip install -e .
   ```

2. **Configure credentials**

   ```bash
   cp .env.example .env
   ```

   Then edit `.env` with your Kicktipp email, password, and community slug.
   The community slug is the path segment in your community URL — for
   `https://www.kicktipp.de/my-community/` it's `my-community`.

   `.env` is git-ignored; never commit it.

## Usage

### CLI bot

```bash
# Dry run — print tips without submitting
uv run python main.py --strategy random --dry-run

# Submit tips for matches starting within the next 48 hours
uv run python main.py --strategy random --max-hours-ahead 48

# Use the LLM strategy (requires the claude CLI)
uv run python main.py --strategy llm
```

Run `uv run python main.py --help` for all options (`--community`, `--debug-html`, …).

### Scheduled runs (macOS launchd)

`com.kicktipp-ai.bot.plist` runs the bot every 6 hours via launchd.

1. Edit the plist and set the correct project path in `ProgramArguments` (the `cd …` line).
2. Copy it into place and load it:

   ```bash
   cp com.kicktipp-ai.bot.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.kicktipp-ai.bot.plist
   ```

Logs are written to `~/Library/Logs/kicktipp-ai.log` (persistent across reboots).
Each run starts with a timestamped header:

```
=== kicktipp-ai run 2026-06-16 22:00:01 ===
Open matches: 8, tippable now: 4
  [Wed 17 Jun 00:00] Irak 1 : 1 Norwegen
  ...
Submitted 4 tips.
```

Follow the log live:

```bash
tail -f ~/Library/Logs/kicktipp-ai.log
```

### Scheduled runs (GitHub Actions)

`.github/workflows/kicktipp-bot.yml` runs the bot on the same 6-hourly schedule
without needing your machine to be on. It commits `data/*.jsonl` back to `main`
after each run, which also feeds the hosted dashboard (see below). See ADR 0009.

Setup:

1. Repo secrets (Settings → Secrets and variables → Actions):
   `KICKTIPP_EMAIL`, `KICKTIPP_PASSWORD`, `KICKTIPP_COMMUNITY`, and
   `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`, run locally under your
   logged-in Pro/Max account — valid for 1 year, keeps billing on your
   subscription instead of the pay-per-token API).
2. Settings → Actions → General → Workflow permissions → "Read and write
   permissions" (needed for the workflow to push the data commit).
3. Trigger a manual run once (Actions tab → "Kicktipp Bot" → Run workflow) to
   confirm it works before relying on the schedule.

A `data/status.json` heartbeat is written on every attempt, success or not —
the dashboard shows a warning banner if the last run failed or is more than
8h old, so a silent failure doesn't go unnoticed.

### Performance tracking

Every submitted tip is appended to `data/tips_history.jsonl` with a `strategy`
label (`random` or `llm`). On each run, `update_scores()` (`tracking.py`)
fetches the by-then-completed match results from Kicktipp and fills in the
real result + points for any tip whose match has since finished, using this
Tipprunde's actual scoring: **4 pts exact score, 3 pts correct goal-difference
(non-draw), 2 pts correct tendency (incl. non-exact draws), 0 pts wrong**.
The log then prints a running average per strategy, e.g.:

```
Scored 6 newly completed match(es).
  [random] 7 pts / 8 matches (avg 0.88)
  [llm] 13 pts / 13 matches (avg 1.00)
```

That's how `random` (the Poisson baseline) and `llm` (Claude with web search)
get compared over time. `random` only has a handful of entries from manual
testing before `llm` became the default strategy in `run.sh`.

When using the `llm` strategy, the full reasoning Claude produced (odds,
injury news, form) is printed to the log right before the final JSON tips —
only the parsed scores get persisted to `tips_history.jsonl`, so the log is
the only place to audit *why* a pick was made.

Each run also snapshots the bookmaker odds (1/X/2) of every still-open match
into `data/odds_history.jsonl` (`odds_history.py`, `record_odds`), upserting each
match's row with the latest odds while it stays open. This runs independently of
`--dry-run` and is best-effort — a failure here never aborts the bot run.

Kicktipp keeps showing the ODDSET odds on the Tippabgabe page for *already played*
Spieltage too, so historical odds can be **backfilled** in one pass:

```bash
uv run python odds_history.py --backfill   # real ODDSET odds for all Spieltage
```

Backfilled rows are tagged `source: "kicktipp-backfill"` and never clobber
forward-captured ones. See ADR 0007.

### Dashboard (localhost)

A zero-dependency local web page that visualises the results:

```bash
# 1. Reconstruct the community standings history (logs in, scrapes once)
uv run python ranking_history.py        # writes data/ranking_history.jsonl

# 2. Serve the dashboard
uv run python dashboard.py              # opens http://localhost:8765
```

It has four parts:

- **Positionsverlauf** — a bump chart of all community members' rank, with a
  slider/▶ to scrub through the season. Each step is a *single match* (not just a
  whole Spieltag): Kicktipp doesn't store historical standings, so this is
  reconstructed retroactively from each Tippübersicht's per-match point columns
  (`<sub class="p">`), accumulated match-by-match. A *Bonusfragen* toggle counts
  the pre-tournament bonus points in or out — with them out you see pure tipping
  rank.
- **Verrückte Tipps** — the *whole community's* tips (all players, not just the
  bot), judged *against the field*: the crowd is the odds. An exact hit almost
  nobody else managed — on a result most players got wrong — ranks highest (gold);
  big wrong tips on results that shocked the field rank as the worst misses (red).
  Each card shows how rare it was (e.g. "nur 1/12 exakt"). Classified by
  tip-vs-result, independent of the community's (non-standard) points scheme.
- **Trophäenschrank** — season-wide awards per player (see ADR 0008).
- **Persönlicher Bereich** (local dashboard only, see below) — every bot tip,
  newest first, with an outcome label and the result colour-coded by how the
  tip fared (exact/diff/tendency/miss). Up top: current rank, total points,
  and hit-rate. Each `llm` tip has an expandable **„Warum?"** panel showing the
  Claude reasoning parsed from the launchd log.

The “↻ Tabelle aktualisieren” button re-runs the scrape live. The server is
stdlib-only (`http.server`) and binds to localhost.

### Hosted dashboard (Vercel)

The community-wide sections (Positionsverlauf, Verrückte Tipps, Trophäenschrank)
are hosted on Vercel so the rest of the Tippkreis can see them — the
**Persönlicher Bereich stays local-only**, dropped structurally rather than
just hidden in the UI (`dashboard_data.build_payload(include_personal=False)`
never computes it, and it can't include the Claude reasoning either way since
that only ever lives in your local launchd log). See ADR 0009.

Setup: connect this repo to a new Vercel project (framework preset "Other", no
build command needed — `vercel.json` handles routing). No secrets required;
`api/data.py` only reads the `data/*.jsonl` files the GitHub Actions workflow
already commits. Every push to `main` (including the bot's own data-refresh
commits) triggers a redeploy.

## Project layout

| File | Purpose |
|------|---------|
| `kicktipp.py` | Kicktipp HTTP client + HTML parsing — vendored from `dernerl/kicktipp-mcp`; port parser fixes back manually |
| `main.py` | CLI entry point for the bot |
| `strategies.py` | Tipping strategies (random / llm) — vendored from `dernerl/kicktipp-mcp` |
| `tracking.py` | Tip history + score tracking (`data/tips_history.jsonl`) |
| `odds_history.py` | Forward-only bookmaker-odds snapshots, upserted per match each run (`data/odds_history.jsonl`) |
| `ranking_history.py` | Reconstructs standings (per Spieltag + per match) and every player's tips (`data/ranking_history.jsonl`, `ranking_steps.jsonl`, `community_tips.jsonl`) |
| `logparse.py` | Extracts llm reasoning + own-rank timeline from the launchd log |
| `dashboard_data.py` | Shared, pure payload-building logic (no HTTP, no live Kicktipp access) |
| `dashboard.py` | Stdlib `http.server` serving the localhost dashboard (full payload incl. personal section) |
| `api/data.py` | Vercel Python Function serving the hosted, community-only payload |
| `web/dashboard.html` | The dashboard UI (vanilla JS + SVG, no build step) |
| `run.sh` | Launcher the launchd job uses for the CLI bot |
| `.github/workflows/kicktipp-bot.yml` | GitHub Actions cron, alternative to launchd (see ADR 0009) |

The MCP server (for Claude Desktop) lives in
[dernerl/kicktipp-mcp](https://github.com/dernerl/kicktipp-mcp), not here.

## License

MIT — see [LICENSE](LICENSE).
