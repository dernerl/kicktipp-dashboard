"""Shared payload-building logic for the dashboard.

Used by both the local dev server (``dashboard.py``, full payload incl. the
personal section) and the hosted read-only deployment (``api/data.py`` on
Vercel, community-only — see ADR 0009). Pure functions only: no live Kicktipp
access, no import-time side effects, so it's safe to import from a serverless
function. Reading data does use HTTP when BLOB_STORE_ID/BLOB_READ_WRITE_TOKEN
are set (hosted deployment, see ADR 0010) — locally those are unset, so it
falls back to plain files under data/, unchanged.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from logparse import parse_log

ROOT = Path(__file__).parent

TIPS_PATH = "tips_history.jsonl"
RANKING_PATH = "ranking_history.jsonl"
STEPS_PATH = "ranking_steps.jsonl"
COMMUNITY_TIPS_PATH = "community_tips.jsonl"
ODDS_PATH = "odds_history.jsonl"
STATUS_PATH = "status.json"

BLOB_STORE_ID = os.environ.get("BLOB_STORE_ID")
BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN")


def _fetch_blob(name: str) -> str | None:
    """Fetch a private Vercel Blob's raw text, or None if Blob isn't configured.

    Returns "" (not None) for a 404 — the file just hasn't been written yet by
    the first bot run, which isn't an error.
    """
    if not (BLOB_STORE_ID and BLOB_READ_WRITE_TOKEN):
        return None
    url = f"https://{BLOB_STORE_ID}.private.blob.vercel-storage.com/data/{name}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {BLOB_READ_WRITE_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return ""
        raise


def _read_data_file(name: str) -> str:
    blob_text = _fetch_blob(name)
    if blob_text is not None:
        return blob_text
    path = ROOT / "data" / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _read_jsonl(name: str) -> list[dict]:
    text = _read_data_file(name)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _read_status() -> dict | None:
    """Cron heartbeat written by the GitHub Actions workflow (ADR 0009/0010).

    Missing until the workflow has run at least once — that's fine, the
    frontend just skips the staleness banner when this is null.
    """
    text = _read_data_file(STATUS_PATH)
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


def _enrich_tip(t: dict) -> dict:
    """Add came-true status + a 'craziness' score used for highlighting.

    Status is derived from tip-vs-result (scoring-independent), so it stays
    correct regardless of the community's point scheme:
      "exact"    — tip == result
      "diff"     — right tendency, right goal-difference, non-draw  (→ 3 pts)
      "tendency" — right tendency, but diff wrong or both sides drew (→ 2 pts)
      "miss"     — wrong tendency                                    (→ 0 pts)
      "open"     — no result yet
    """
    h_tip, a_tip = t["home_tip"], t["away_tip"]
    h_res, a_res = t.get("home_result"), t.get("away_result")

    t = dict(t)
    if h_res is None or a_res is None:
        t["status"] = "open"
        t["craziness"] = 0
        return t

    gd_tip = h_tip - a_tip
    gd_res = h_res - a_res
    total_res = h_res + a_res
    tend_tip = _sign(gd_tip)
    tend_res = _sign(gd_res)

    if h_tip == h_res and a_tip == a_res:
        t["status"] = "exact"
        # Nailing a lopsided, high-scoring line exactly is the wildest outcome.
        t["craziness"] = total_res + 2 * abs(gd_res)
    elif tend_tip != tend_res:
        t["status"] = "miss"
        # How far off, weighted up when the tendency was backwards.
        error = abs(h_tip - h_res) + abs(a_tip - a_res)
        backwards = tend_tip != 0 and tend_res != 0  # both non-draw, opposite signs
        t["craziness"] = error + (3 if backwards else 0)
        t["backwards"] = backwards
    elif gd_tip == gd_res and gd_res != 0:
        t["status"] = "diff"
        t["craziness"] = 0
    else:
        # Right tendency but wrong difference — includes non-exact draws (diff==0).
        t["status"] = "tendency"
        t["craziness"] = 0
    return t


def _wucht(t: dict) -> int:
    """How lopsided/high-scoring the actual result was (tiebreaker only)."""
    return (t["home_goals"] + t["away_goals"]) + 2 * abs(t["home_goals"] - t["away_goals"])


def _load_odds() -> dict[tuple, dict]:
    """Load odds_history.jsonl → dict keyed by (spieltag_index, home_team, away_team).

    When multiple snapshots exist for the same game the last one wins (forward-only
    updates, latest snapshot is most accurate pre-kickoff odds).
    """
    odds: dict[tuple, dict] = {}
    for row in _read_jsonl(ODDS_PATH):
        key = (row["spieltag_index"], row["home_team"], row["away_team"])
        odds[key] = row
    return odds


def _implied_probs(
    odds_home: float, odds_draw: float, odds_away: float
) -> tuple[float, float, float]:
    """Return overround-normalised implied probabilities (home, draw, away)."""
    inv_h, inv_d, inv_a = 1 / odds_home, 1 / odds_draw, 1 / odds_away
    s = inv_h + inv_d + inv_a
    return inv_h / s, inv_d / s, inv_a / s


def _tendency_prob(probs: tuple[float, float, float], tendency_sign: int) -> float:
    """Probability for the given tendency sign (+1=home win, 0=draw, -1=away win)."""
    p_home, p_draw, p_away = probs
    if tendency_sign > 0:
        return p_home
    elif tendency_sign == 0:
        return p_draw
    else:
        return p_away


def _score_crazy_row(
    t: dict,
    n: int,
    n_exact: int,
    n_tend: int,
    odds_entry: dict | None,
) -> dict | None:
    """Score one community-tip row for craziness.

    Returns an enriched dict with ``status``, ``craziness``, ``odds_based`` (and
    optionally ``outcome_odds``, ``p``) — or ``None`` when the row is neither an
    exact hit nor a tendency miss.

    Both Wahnsinns-Treffer and Komplett-daneben scores are on a ~0..2 scale so
    the two columns are sortable together and comparable with the odds-based path.

    Wahnsinns-Treffer:
        exact_rarity  = (n - n_exact) / n
        tend_unlikely = 1 - p(result_tendency)   [odds] or (n - n_tend) / n  [field]
        craziness     = tend_unlikely + exact_rarity

    Komplett daneben:
        error_norm = min(|tip - result|_sum, 6) / 6
        boldness   = p(tipped_tendency)           [odds] or (n - n_tend) / n  [field]
        craziness  = boldness + error_norm
    """
    h, a = t["home_goals"], t["away_goals"]
    ht, at = t["home_tip"], t["away_tip"]
    res_sign = _sign(h - a)
    tip_sign = _sign(ht - at)

    # Parse odds only when all three values are present and strictly positive.
    probs: tuple[float, float, float] | None = None
    if odds_entry:
        oh = odds_entry.get("odds_home")
        od = odds_entry.get("odds_draw")
        oa = odds_entry.get("odds_away")
        if oh and od and oa and oh > 0 and od > 0 and oa > 0:
            probs = _implied_probs(oh, od, oa)

    exact_rarity = (n - n_exact) / n
    stats = {"n_players": n, "n_exact": n_exact, "n_tend": n_tend, "odds_based": probs is not None}

    if ht == h and at == a:
        # ── Wahnsinns-Treffer ──────────────────────────────────────────────
        if probs is not None:
            tend_unlikely = 1.0 - _tendency_prob(probs, res_sign)
            if res_sign > 0:
                outcome_odds = odds_entry["odds_home"]  # type: ignore[index]
            elif res_sign == 0:
                outcome_odds = odds_entry["odds_draw"]  # type: ignore[index]
            else:
                outcome_odds = odds_entry["odds_away"]  # type: ignore[index]
        else:
            tend_unlikely = (n - n_tend) / n
            outcome_odds = None

        craziness = tend_unlikely + exact_rarity
        row = {**t, "status": "exact", "craziness": craziness, **stats}
        if probs is not None:
            row["outcome_odds"] = round(outcome_odds, 2)
            row["p"] = round(_tendency_prob(probs, res_sign), 3)
        return row

    elif tip_sign != res_sign:
        # ── Komplett daneben ───────────────────────────────────────────────
        error = abs(ht - h) + abs(at - a)
        error_norm = min(error, 6) / 6

        if probs is not None:
            boldness = _tendency_prob(probs, tip_sign)
            if tip_sign > 0:
                outcome_odds = odds_entry["odds_home"]  # type: ignore[index]
            elif tip_sign == 0:
                outcome_odds = odds_entry["odds_draw"]  # type: ignore[index]
            else:
                outcome_odds = odds_entry["odds_away"]  # type: ignore[index]
        else:
            boldness = (n - n_tend) / n
            outcome_odds = None

        craziness = boldness + error_norm
        row = {**t, "status": "miss", "craziness": craziness, **stats}
        if probs is not None:
            row["outcome_odds"] = round(outcome_odds, 2)
            row["p"] = round(_tendency_prob(probs, tip_sign), 3)
        return row

    return None


def build_crazy() -> dict:
    """Community-wide crazy tips — hybrid: Buchmacher-Quoten wo vorhanden, sonst Tippkreis.

    Joined über (spieltag_index, home, away) = (spieltag_index, home_team, away_team).
    Beide Pfade liefern Craziness ~0..2 → gemeinsam sortierbar.
    """
    rows = _read_jsonl(COMMUNITY_TIPS_PATH)
    odds_map = _load_odds()

    by_match: dict[tuple, list[dict]] = {}
    for t in rows:
        by_match.setdefault((t["spieltag_index"], t["home"], t["away"]), []).append(t)

    exact, miss = [], []
    for (st_idx, home, away), tips in by_match.items():
        n = len(tips)
        h, a = tips[0]["home_goals"], tips[0]["away_goals"]
        res_sign = _sign(h - a)
        n_exact = sum(1 for t in tips if t["home_tip"] == h and t["away_tip"] == a)
        n_tend = sum(1 for t in tips if _sign(t["home_tip"] - t["away_tip"]) == res_sign)

        # Join with odds (key: spieltag_index, home_team, away_team == home, away in community_tips)
        odds_entry = odds_map.get((st_idx, home, away))

        for t in tips:
            scored = _score_crazy_row(t, n, n_exact, n_tend, odds_entry)
            if scored is None:
                continue
            if scored["status"] == "exact":
                exact.append(scored)
            else:
                miss.append(scored)

    exact.sort(key=lambda r: (-r["craziness"], -_wucht(r), r["n_exact"]))
    miss.sort(key=lambda r: (-r["craziness"], -_wucht(r)))

    def _distinct(rows: list[dict]) -> list[dict]:
        # one card per match (the craziest tip) so a shock game doesn't flood the section
        seen: set[tuple] = set()
        out: list[dict] = []
        for r in rows:
            key = (r["spieltag_index"], r["home"], r["away"])
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
        return out[:8]

    return {"exact": _distinct(exact), "miss": _distinct(miss)}


def build_timeline() -> list[dict]:
    """Group the per-(step × player) rows into one entry per match-step."""
    by_ord: dict[int, list[dict]] = {}
    for r in _read_jsonl(STEPS_PATH):
        by_ord.setdefault(r["ordinal"], []).append(r)
    timeline = []
    for ordv in sorted(by_ord):
        rows = by_ord[ordv]
        meta = rows[0]
        timeline.append({
            "ordinal": ordv,
            "spieltag_index": meta["spieltag_index"],
            "spieltag_label": meta["spieltag_label"],
            "match_index": meta["match_index"],
            "home": meta["home"], "away": meta["away"], "result": meta["result"],
            "standings": sorted(
                ({"player": r["player"], "rank": r["rank"], "points": r["points"],
                  "bonus": r.get("bonus", 0), "is_self": r["is_self"]} for r in rows),
                key=lambda x: x["rank"]),
        })
    return timeline


def build_payload(include_personal: bool = True) -> dict:
    """Build the dashboard's JSON payload.

    ``include_personal=False`` (used by the hosted Vercel deployment, see
    ADR 0009) drops the bot's own tips and the Claude-reasoning/rank-trajectory
    log data — the rest of the community can't see your strategy. Locally,
    the Claude reasoning is only ever available in the first place because
    ``parse_log`` reads ``~/Library/Logs/kicktipp-ai.log``, a file that never
    exists outside your machine, so it's harmless to still call it here.
    """
    # Lazy import breaks the awards <-> dashboard_data import cycle (awards reuses
    # our craziness helpers; we only need build_awards at request time).
    from awards import build_awards

    payload = {
        "local": include_personal,
        "ranking_history": _read_jsonl(RANKING_PATH),
        "timeline": build_timeline(),
        "crazy": build_crazy(),
        "awards": build_awards(),
        "status": _read_status(),
    }

    if not include_personal:
        return payload

    tips = [_enrich_tip(t) for t in _read_jsonl(TIPS_PATH)]
    log = parse_log()

    # Attach reasoning to llm tips by (home|away).
    rb = log["reasoning_by_match"]
    for t in tips:
        if t["strategy"] == "llm":
            r = rb.get(f"{t['home_team']}|{t['away_team']}")
            if r:
                t["reasoning"] = r["text"]
                t["reasoning_run"] = r["run"]

    # Per-strategy summary (matches the bot's own log line).
    summary: dict[str, dict] = {}
    for t in tips:
        if t.get("points") is None:
            continue
        s = summary.setdefault(t["strategy"], {"matches": 0, "points": 0})
        s["matches"] += 1
        s["points"] += t["points"]
    for s in summary.values():
        s["avg"] = round(s["points"] / s["matches"], 2) if s["matches"] else 0

    payload["tips"] = tips
    payload["summary"] = summary
    payload["standings_timeline"] = log["standings_timeline"]
    return payload
