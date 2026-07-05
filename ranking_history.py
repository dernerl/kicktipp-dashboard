"""Reconstruct the community standings — per Spieltag *and* per single match.

Kicktipp never persists historical standings, but each per-Spieltag Tippübersicht
page carries every player's cumulative Gesamtpunkte plus the points they earned in
each individual match.  From that we rebuild two views and write them to data/:

  * ranking_history.jsonl — one row per (Spieltag × player): the standing after
    that Spieltag.  Used for the personal section's "current rank".
  * ranking_steps.jsonl   — one row per (step × player), where a *step* is the
    state after a single match (plus a step 0 for the pre-tournament bonus
    questions).  This is what lets the dashboard scrub the table forward
    match-by-match instead of only once per Spieltag.

Both are derived from a single scrape pass and the file is rewritten each run.

    uv run python ranking_history.py
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from kicktipp import BonusRanking, KicktippClient, SpieltagDetail

_GROUP_STAGE_LABEL = re.compile(r"^\d+\.\s*Spieltag$")

DATA_DIR = Path(__file__).parent / "data"
HISTORY_PATH = DATA_DIR / "ranking_history.jsonl"
STEPS_PATH = DATA_DIR / "ranking_steps.jsonl"
COMMUNITY_TIPS_PATH = DATA_DIR / "community_tips.jsonl"
COMMUNITY_NAME_PATH = DATA_DIR / "community_name.json"


def _ranked(totals: dict[str, int]) -> dict[str, int]:
    """Standard competition ranking (1,2,2,4) by points desc, as Kicktipp does."""
    ranks = {}
    for player, pts in totals.items():
        ranks[player] = 1 + sum(1 for o in totals.values() if o > pts)
    return ranks


def build_history_rows(details: list[SpieltagDetail]) -> list[dict]:
    rows = []
    for d in details:
        for p in d.players:
            rows.append({
                "spieltag_index": d.spieltag_index,
                "spieltag_label": d.spieltag_label,
                "rank": p.rank,
                "player": p.player,
                "points": p.total,
                "is_self": p.is_self,
            })
    return rows


def compute_group_bonus(bonus_ranking: BonusRanking) -> dict[str, int]:
    """Per-player points from already-decided "Wer gewinnt die Gruppe X?" questions.

    Kicktipp's Bonus tab shows one column per Bonusfrage, each labelled (e.g.
    "Gr A") with the real-world answer once known ("---" while still open).
    We only trust questions that are actually resolved — this is what lets
    build_step_rows tell "genuinely decided" Gruppensieger points apart from
    Bonusfragen that just haven't resolved yet.
    """
    group_idx = [q.index for q in bonus_ranking.questions if q.label.startswith("Gr") and q.resolved]
    return {p.player: sum(p.per_question[i] for i in group_idx) for p in bonus_ranking.players}


def build_step_rows(details: list[SpieltagDetail], group_bonus: dict[str, int] | None = None) -> list[dict]:
    """Expand the per-match points into a cumulative, ranked timeline.

    Gesamtpunkte = bonus + Σ match points. Bonus questions don't all resolve
    at the same time — e.g. "Gruppensieger" only becomes known once the group
    stage finishes. But Kicktipp's per-Spieltag "Gesamtpunkte" doesn't freeze
    the bonus component to what was actually known back then: the *current*
    Gruppensieger bonus leaks into every group-stage Spieltag's total,
    including Spieltag 1, long before the group stage was actually decided.
    (Verified: identical bonus value shows up unchanged on Spieltag 1 through
    the last group Spieltag, and rechecking against the Bonus tab's per-question
    breakdown shows that value is 100% Gruppensieger points that couldn't
    possibly be known that early.)

    So during the group stage we subtract `group_bonus` (the Gruppensieger
    total we independently know is *actually* resolved, from
    `compute_group_bonus`) out of each Spieltag's reported total before
    reconciling — cancelling the leak — and stop subtracting the moment we
    reach the first non-group-stage round, letting it surface there as its
    own step instead. Any other still-open Bonusfrage (Torschützenteam,
    Halbfinale-Tipp, Weltmeister) is 0 until it resolves and isn't specially
    handled — same caveat, deal with it once it actually happens.
    """
    details = sorted(details, key=lambda d: d.spieltag_index)
    if not details:
        return []

    group_bonus = group_bonus or {}
    first = details[0]
    is_self = {p.player: p.is_self for d in details for p in d.players}
    running = {p.player: 0 for p in first.players}
    bonus = {p.player: 0 for p in first.players}

    rows: list[dict] = []

    def emit(ordinal, st_idx, st_label, match_index, match):
        totals = dict(running)
        ranks = _ranked(totals)
        for player, pts in totals.items():
            rows.append({
                "ordinal": ordinal,
                "spieltag_index": st_idx,
                "spieltag_label": st_label,
                "match_index": match_index,
                "home": match["home"] if match else None,
                "away": match["away"] if match else None,
                "result": (f"{match['home_goals']}:{match['away_goals']}"
                           if match and match["home_goals"] is not None else None),
                "player": player,
                "points": pts,
                "bonus": bonus.get(player, 0),
                "rank": ranks[player],
                "is_self": is_self.get(player, False),
            })

    # Step 0: standings from whichever Bonusfragen had genuinely resolved
    # before Spieltag 1 (normally none, for a Gruppensieger-style bonus).
    ordinal = 0
    emit(ordinal, 0, "Bonusfragen", -1, None)

    for d in details:
        is_group_stage = bool(_GROUP_STAGE_LABEL.match(d.spieltag_label))
        newly_resolved = {
            p.player: p.total - running.get(p.player, 0) - sum(p.per_match)
            for p in d.players
        }
        if is_group_stage:
            for player in newly_resolved:
                newly_resolved[player] -= group_bonus.get(player, 0)
        if any(delta for delta in newly_resolved.values()):
            for player, delta in newly_resolved.items():
                running[player] = running.get(player, 0) + delta
                bonus[player] = bonus.get(player, 0) + delta
            ordinal += 1
            emit(ordinal, d.spieltag_index, d.spieltag_label, -1, None)

        for mi, match in enumerate(d.matches):
            if match["home_goals"] is None:        # not played yet → no step
                continue
            for p in d.players:
                if mi < len(p.per_match):
                    running[p.player] = running.get(p.player, 0) + p.per_match[mi]
            ordinal += 1
            emit(ordinal, d.spieltag_index, d.spieltag_label, mi, match)

    return rows


def build_community_tips(details: list[SpieltagDetail]) -> list[dict]:
    """Every player's tip for every finished match, with the Kicktipp points.

    Powers the community-wide "verrückte Tipps" view (all 12 players, not just
    the bot).  Matches without a result and players who didn't tip are skipped.
    """
    rows = []
    for d in details:
        for mi, match in enumerate(d.matches):
            if match["home_goals"] is None:
                continue
            for p in d.players:
                tip = p.per_match_tips[mi] if mi < len(p.per_match_tips) else None
                if tip is None:
                    continue
                rows.append({
                    "spieltag_index": d.spieltag_index,
                    "spieltag_label": d.spieltag_label,
                    "home": match["home"],
                    "away": match["away"],
                    "home_goals": match["home_goals"],
                    "away_goals": match["away_goals"],
                    "player": p.player,
                    "is_self": p.is_self,
                    "home_tip": tip[0],
                    "away_tip": tip[1],
                    "points": p.per_match[mi] if mi < len(p.per_match) else 0,
                })
    return rows


def build_ranking_history(client: KicktippClient) -> tuple[int, int, int]:
    details = client.fetch_spieltag_details()
    DATA_DIR.mkdir(exist_ok=True)

    try:
        group_bonus = compute_group_bonus(client.fetch_bonus_ranking())
    except Exception as exc:
        print(f"Warning: could not fetch Bonus ranking ({exc}); Gruppensieger bonus timing will be approximate")
        group_bonus = {}

    def _write(path, rows):
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    history = build_history_rows(details)
    steps = build_step_rows(details, group_bonus)
    community = build_community_tips(details)
    _write(HISTORY_PATH, history)
    _write(STEPS_PATH, steps)
    _write(COMMUNITY_TIPS_PATH, community)
    COMMUNITY_NAME_PATH.write_text(
        json.dumps({"name": client.fetch_community_name()}, ensure_ascii=False), encoding="utf-8"
    )

    return len(history), len(steps), len(community)


def main() -> None:
    load_dotenv()
    email = os.environ.get("KICKTIPP_EMAIL")
    password = os.environ.get("KICKTIPP_PASSWORD")
    community = os.environ.get("KICKTIPP_COMMUNITY")
    missing = [k for k, v in (
        ("KICKTIPP_EMAIL", email),
        ("KICKTIPP_PASSWORD", password),
        ("KICKTIPP_COMMUNITY", community),
    ) if not v]
    if missing:
        raise SystemExit(f"Missing env vars: {', '.join(missing)} (see .env.example)")

    client = KicktippClient(email, password, community)
    client.login()
    n_hist, n_steps, n_comm = build_ranking_history(client)
    n_ordinals = len({json.loads(l)["ordinal"]
                      for l in STEPS_PATH.read_text(encoding="utf-8").splitlines() if l.strip()})
    print(f"Wrote {n_hist} Spieltag rows → {HISTORY_PATH.name}")
    print(f"Wrote {n_steps} step rows across {n_ordinals} match-steps → {STEPS_PATH.name}")
    print(f"Wrote {n_comm} community tips → {COMMUNITY_TIPS_PATH.name}")


if __name__ == "__main__":
    main()
