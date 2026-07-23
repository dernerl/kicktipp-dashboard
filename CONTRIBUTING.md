# Contributing

This repo is meant to be **used as a template**, not run as a shared
instance — fork or "Use this template", plug in your own Kicktipp
credentials and community, deploy your own copy. There's no central
production instance to keep backwards-compatible.

PRs are welcome for anything that benefits every fork: bug fixes, parsing
fixes, new dashboard sections, new tipping strategies. Please avoid PRs that
hardcode assumptions specific to one Tippkreis (community slug, scoring
scheme, player names) — see `docs/adr/0005-punktesystem-4-3-2-0.md` for how
the non-standard scoring is kept configurable-in-spirit via `tracking._points`.

## Before opening a PR

- No automated test suite — verify manually:
  ```bash
  uv run python -m py_compile *.py api/*.py   # syntax sanity check
  uv run python main.py --strategy random --dry-run
  uv run python dashboard.py                  # eyeball the change at localhost:8765
  ```
- `kicktipp.py` and `strategies.py` are vendored from
  [dernerl/kicktipp-mcp](https://github.com/dernerl/kicktipp-mcp). If your fix
  touches Kicktipp HTML parsing or the tipping strategies, consider whether it
  belongs upstream there too (no automated sync between the two repos).
- Non-trivial decisions get an ADR (Nygard format) in `docs/adr/` — see the
  existing ones for the expected shape.
- `data/` and anyone's real Tippkreis data must never end up committed — see
  ADR 0010. If you touch the payload-building code (`dashboard_data.py`,
  `awards.py`), double check nothing player-identifying leaks into the
  `include_personal=False` / hosted path.

## Reporting issues

Open a GitHub issue. Include what you ran, what you expected, what happened —
scraping bugs are much easier to fix with a copy of the relevant HTML
(`--debug-html` on `main.py`) or the failing Kicktipp page structure.
