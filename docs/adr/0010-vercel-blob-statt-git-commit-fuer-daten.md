# ADR 0010: Private Vercel Blob statt Git-Commit für Laufzeitdaten

**Date:** 2026-07-04
**Status:** Accepted — supersedes den Git-Commit-Teil von ADR 0009

---

## Context

ADR 0009 hatte `data/*.jsonl` (+ `status.json`) direkt in dieses Repo committen
lassen (Muster aus `dernerl/my-awesome-categorized-stars`/`CodeSite`) — einfach,
keine neue Abhängigkeit, kein neues Secret.

Das hat sich als falsch herausgestellt, sobald das Repo **öffentlich** ist: die
echten Tippkreis-Daten (Spielernamen, Tipps, Tabellenstände) lagen dadurch für
mehrere Stunden öffentlich in der Git-Historie, bevor das bemerkt wurde. Das
Repo wurde daraufhin auf privat gestellt und die Historie per `git filter-repo`
bereinigt (destruktiver Force-Push, einmalig).

Das eigentliche Ziel — dieses Repo perspektivisch als **Template für andere
Kicktipp-Tippkreise** freigeben zu können — lässt sich mit "Daten im selben
Git-Repo" grundsätzlich nicht ohne Kompromiss lösen: Git-Sichtbarkeit ist
Repo-weit, nicht pro Branch. Ein separater `data`-Branch (ursprünglich als
Idee diskutiert) hätte das Problem nicht gelöst — auch ein Branch in einem
öffentlichen Repo ist öffentlich klonbar.

## Decision

Laufzeitdaten (`data/*.jsonl`, `data/status.json`) werden **nicht mehr
committet**, sondern in einen **privaten Vercel-Blob-Store** hochgeladen:

- Der GitHub-Actions-Workflow installiert die Vercel-CLI und lädt nach jedem
  Lauf jede vorhandene `data/*.jsonl`-Datei (+ `status.json`) per
  `vercel blob put ... --access private --allow-overwrite --rw-token
  $BLOB_READ_WRITE_TOKEN --store-id $BLOB_STORE_ID` hoch — non-interaktiv,
  ohne `vercel link`, mit zwei neuen Secrets (`BLOB_READ_WRITE_TOKEN`,
  `BLOB_STORE_ID`).
- `dashboard_data.py` liest Daten über `_read_data_file()`: wenn
  `BLOB_STORE_ID`/`BLOB_READ_WRITE_TOKEN` als Env-Vars gesetzt sind (gehostetes
  Vercel-Deployment), per authentifiziertem HTTP-GET auf
  `https://<store-id>.private.blob.vercel-storage.com/data/<name>` (Header
  `Authorization: Bearer <token>`, stdlib `urllib`, keine neue Abhängigkeit).
  Sonst (lokale Entwicklung) unverändert lokale Dateien unter `data/`.
- **Private** Vercel-Blobs sind nicht über eine öffentliche URL erreichbar,
  im Unterschied zu Public-Blobs (bei denen nur die URL selbst unerraten ist —
  dieselbe Schwäche wie ein "geheimes" GitHub-Gist). Nur wer den Token hat,
  kommt an die Daten.
- `data/` ist wieder vollständig `.gitignore`t — dieses Repo enthält damit
  strukturell **nie wieder** echte Tippkreis-Daten, egal ob public oder
  privat.

## Consequences

**Positiv:**
- Der Code (`kicktipp-dashboard`) kann jetzt gefahrlos wieder öffentlich
  gemacht und als Template für andere Tippkreise verwendet werden — es gibt
  keine Daten mehr, die dabei versehentlich mitkopiert werden könnten.
- Zugriffsschutz ist echte Authentifizierung (Token), nicht Verschleierung
  (unerratene URL) oder Repo-Sichtbarkeit.
- Jeder Fork/Template-Nutzer richtet einfach seinen eigenen Blob-Store +
  eigene Secrets ein — keine Kollision mit fremden Daten möglich, by design.

**Negativ / Trade-offs:**
- Zwei neue Secrets (`BLOB_READ_WRITE_TOKEN`, `BLOB_STORE_ID`) statt der
  Standard-`GITHUB_TOKEN`-Berechtigung von vorher — etwas mehr Setup-Aufwand.
- Der Workflow braucht jetzt auch die Vercel-CLI (npm-Install), zusätzlich zur
  Claude-Code-CLI.
- `dashboard.py` (lokal) und `api/data.py` (gehostet) laufen jetzt auf leicht
  unterschiedlichen Datenpfaden (Datei vs. HTTP) — vertretbar, weil beide
  hinter derselben `_read_data_file()`-Funktion verborgen sind und lokal exakt
  das alte, unveränderte Verhalten bleibt.
- Ungetestet ohne echtes Vercel-Projekt zum Zeitpunkt dieser ADR — CLI-Flags
  (`vercel blob put ...`) müssen beim ersten echten Lauf verifiziert werden.

## Lesson

"Wir committen das einfach ins Repo, das hat bei unseren anderen Projekten
auch funktioniert" war die falsche Verallgemeinerung — bei `CodeSite`/
`my-awesome-categorized-stars` gab es keine personenbezogenen Daten Dritter
im Spiel. Ein Muster, das für ein Szenario passt, passt nicht automatisch für
ein anderes mit anderer Datensensibilität — das hätte schon beim ersten Public-Schalten
mitgedacht werden müssen, nicht erst danach.
