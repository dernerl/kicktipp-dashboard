# ADR 0009: Cron auf GitHub Actions, Dashboard-Hosting auf Vercel

**Date:** 2026-07-03
**Status:** Accepted

---

## Context

Bot und Dashboard liefen bisher ausschließlich lokal: launchd triggert `main.py`
alle 6h, `dashboard.py` läuft nur, wenn der Mac läuft und jemand es startet. Das
hat zwei Probleme: der Bot fällt aus, wenn der Rechner aus/im Schlaf ist, und das
Dashboard ist für die Community nicht erreichbar.

Zwei eigene, bereits produktiv laufende Repos liefern das Muster dafür:

- `dernerl/my-awesome-categorized-stars` — GitHub-Actions-Cron, der generierte
  Daten direkt per `git add -A && commit && push` auf `main` zurückschreibt.
- `dernerl/CodeSite` — dieselbe Commit-zurück-Mechanik, aber der Push selbst
  triggert automatisch ein Vercel-Redeploy (Vercels Git-Integration).

Ein Blick in die Run-History von `my-awesome-categorized-stars` zeigt aber auch die
Falle: der Claude-Workflow dort lief **30 Tage in Folge mit `failure`**, ohne dass es
auffiel — der Scheduler selbst ist zuverlässig, das Script scheiterte still. Für
kicktipp-mcp ist das ein größeres Risiko als bei einer Portfolio-Seite: ein stiller
Fehlschlag bedeutet nicht "Dashboard veraltet", sondern "Tipps für ein Spieltag
wurden nicht abgegeben".

Zusätzliche Anforderung: der Dashboard-„Persönlicher Bereich" zeigt die eigene
LLM-Strategie (Claudes Begründung je Tipp) — das soll die Community nicht sehen,
wenn das Dashboard öffentlich gehostet wird.

## Decision

**Cron → GitHub Actions** (`.github/workflows/kicktipp-bot.yml`, ersetzt
`com.kicktipp-ai.bot.plist`):
- `on: schedule` (alle 6h) + `workflow_dispatch`, `permissions: contents: write`.
- `llm`-Strategie bleibt auf dem Claude-Pro/Max-Abo statt Pay-per-Token-API:
  `claude setup-token` (einmalig, lokal, 1 Jahr gültig) → Secret
  `CLAUDE_CODE_OAUTH_TOKEN`, injiziert als Env-Var für die Claude Code CLI im Runner.
- Nach dem Lauf: `data/*.jsonl` wird per `git add -A && commit && push` auf `main`
  zurückgeschrieben (Muster aus `my-awesome-categorized-stars`, kein eigener
  `data`-Branch — unnötige Komplexität).
- **Cron-Heartbeat**: ein expliziter, immer geschriebener (`if: always()`)
  `data/status.json` mit `{last_attempt_at, ok}` — unabhängig davon, ob überhaupt
  neue Tipp-/Odds-Daten anfielen. Löst genau das 30-Tage-Stillstand-Problem: das
  Dashboard zeigt ein Warn-Banner, sobald der letzte Versuch fehlgeschlagen oder
  älter als 8h ist, statt sich auf GitHub-E-Mail-Benachrichtigungen zu verlassen.

**Dashboard-Hosting → Vercel** statt GitHub Pages:
- `dashboard.py`s `/api/data`-Route war bereits eine reine, deterministische
  Funktion über `data/*.jsonl` (kein Live-Kicktipp-Zugriff) — ausgelagert nach
  `dashboard_data.py`, importiert von `dashboard.py` (lokal) **und** der neuen
  `api/data.py` (Vercel Python Function, `class handler(BaseHTTPRequestHandler)`).
- `/api/refresh` (Live-Login bei Kicktipp) bleibt lokal-only — passt nicht zu
  einem Serverless-Host und ist auf der gehosteten Instanz auch nicht nötig, da
  die Daten durch den Cron ohnehin periodisch aktuell sind.
- Vercel statt GitHub Pages, weil: (a) Repo-Sichtbarkeit unabhängig vom Hosting
  bleibt (GH Pages im Free-Tier bräuchte ein öffentliches Repo), (b) derselbe
  "Push auf `main` löst Redeploy aus"-Mechanismus wie bei `CodeSite` funktioniert
  identisch, (c) Deployment Protection/Passwortschutz möglich, unabhängig von
  Repo-Sichtbarkeit.

**Persönlicher Bereich bleibt strukturell lokal**, nicht nur per UI ausgeblendet:
- `build_payload(include_personal: bool)` in `dashboard_data.py` — bei `False`
  (Vercel) werden `tips`, `summary` und die Log-Rekonstruktion (Reasoning,
  Rang-Verlauf) gar nicht erst berechnet, nicht nur im Frontend versteckt.
- Ohnehin strukturell sicher: `logparse.parse_log()` liest
  `~/Library/Logs/kicktipp-ai.log` — eine Datei, die außerhalb des eigenen Macs
  nie existiert und bei `if not p.exists()` bereits leer zurückgibt. Die
  Begründung kann auf Vercel also gar nicht auftauchen, unabhängig vom Flag.
- Frontend (`web/dashboard.html`) rendert `sectionPersonal()` und den
  „Tabelle aktualisieren"-Button nur, wenn `DATA.local === true`.

## Consequences

**Positiv:**
- Bot läuft unabhängig davon, ob der eigene Mac an ist.
- Dashboard ist öffentlich erreichbar, ohne dass die eigene Tipp-Strategie
  exponiert wird.
- Kein Auth-System nötig für den Personal-Bereich — die Trennung ist strukturell.
- Kein neuer Python-Dependency für `api/data.py` (eigene `api/requirements.txt`,
  damit Vercel nicht die Bot/MCP-Dependencies aus dem Root-`requirements.txt`
  mitzieht).

**Negativ / Trade-offs:**
- `CLAUDE_CODE_OAUTH_TOKEN` muss einmal jährlich manuell erneuert werden
  (`claude setup-token`, lokal, unter dem eingeloggten Pro/Max-Account).
- `data/` ist jetzt **teilweise** kein "nie committen" mehr — das widerspricht der
  bisherigen Konvention in `CLAUDE.md` (die Kicktipp-Rohdaten-Rekonstruktion
  bleibt unverändert regenerierbar, aber `data/*.jsonl` wird jetzt zusätzlich als
  Persistenzschicht für den Cron committet). `CLAUDE.md` entsprechend aktualisiert.
- Vercels Python-Runtime-Konvention (`api/*.py` → `class handler(BaseHTTPRequestHandler)`)
  ist nach aktueller Doku (Stand Mai 2026) korrekt umgesetzt, aber ungetestet ohne
  echtes Vercel-Projekt — muss beim ersten Deploy verifiziert werden.
- Zwei separate Logins pro Lauf (Bot-Login in `main.py`, zweiter Login in
  `ranking_history.py`) statt einem — bewusst in Kauf genommen, um beide Skripte
  unverändert zu lassen statt sie zu einer Session zu verschmelzen.

## Lesson

Ein Scheduler, der zuverlässig feuert, ist nicht dasselbe wie ein zuverlässiger
Job — das zeigt die eigene Run-History in `my-awesome-categorized-stars` (30
Tage `failure` ohne Bemerken). Sichtbarkeit für Fehlschläge gehört von Anfang an
in den Plan, nicht als Nachgedanke, sobald es tatsächlich einmal lautlos
schiefgeht.
