# ADR 0011: Bonusfragen im Positionsverlauf zum Zeitpunkt ihrer Auflösung statt komplett am Start

**Date:** 2026-07-04
**Status:** Accepted

---

## Context

ADR 0002 (Positionsverlauf-Rekonstruktion) ging davon aus: „Bonus wird komplett
vor Spieltag 1 gutgeschrieben (danach konstant)" und rechnete ihn einmalig aus
Spieltag 1 (`total − Σ per_match`) zurück.

Das stimmt nicht für alle Bonusfragen. „Gruppensieger" steht z.B. erst fest,
wenn die Gruppenphase abgeschlossen ist. Im aktuellen Datenstand (WM 2026,
48 Teams) zeigte sich das an zwei Stellen:

1. **Sprung beim Übergang zur K.o.-Phase.** `ranking_steps.jsonl` stimmte bis
   Spieltag 10 exakt mit den von Kicktipp gemeldeten Gesamtpunkten überein,
   sprang dann aber unerklärt:
   ```
   Spieltag 10 → 11 (Sechzehntelfinale): Josia 163 → 206  (+43, ohne gespieltes Match)
   ```
2. **Der eigentliche Kern des Problems** (vom User anhand des Positionsverlaufs
   bemerkt: mit Bonus eingerechnet lag `dernerl` von Spieltag 1 an durchgehend
   auf Platz 12, ohne Bonus deutlich besser — und er erinnerte sich, in der
   echten Kicktipp-App früh gut platziert gewesen zu sein). Grund: Kicktipps
   `Gesamtpunkte`-Spalte auf **jeder** per-Spieltag-Tippübersichtsseite
   (auch der von Spieltag 1) enthält den **aktuellen** Bonus-Stand, nicht
   den zum historischen Zeitpunkt tatsächlich bekannten. Verifiziert über die
   separate Bonus-Ansicht (`tippuebersicht?bonus=true`), die pro Bonusfrage
   die bereits feststehende Antwort zeigt: der komplette "B"-Wert, der
   scheinbar schon auf Spieltag 1 vorhanden war (z.B. 44 Punkte bei Josia,
   28 bei dernerl), bestand zu 100 % aus korrekt getippten Gruppensiegern —
   unmöglich nach nur einem Spieltag bekannt. Kicktipp rechnet diesen Wert
   rückwirkend in jede Spieltag-Seite ein, statt ihn zeitlich einzufrieren.

## Decision

Zwei Ebenen der Korrektur in `ranking_history.py`:

**1. Generischer Abgleich pro Spieltag** (`build_step_rows`): für jeden
Spieltag wird geprüft, ob der gemeldete `total` zur laufenden Summe passt:

```
newly_resolved = total − running_total_bisher − Σ per_match(dieser Spieltag)
```

Ist die Differenz ≠ 0, bekommt sie einen eigenen Timeline-Step
(`match_index = -1`, kein Match angehängt), datiert auf den Spieltag, an dem
sie erstmals sichtbar wird. Das fängt Bonus-Ereignisse ab, die tatsächlich an
ein bestimmtes Runden-Ende gekoppelt sind (z.B. die gestaffelten
Halbfinale-Tipp-Punkte, die exakt beim Erreichen von Sechzehntelfinale/
Achtelfinale auftauchen — real, nicht rückwirkend verzerrt).

**2. Gezielte Korrektur für den Gruppensieger-Bonus**, der (siehe oben)
*nicht* rundenspezifisch, sondern rückwirkend auf jeder Seite erscheint: eine
neue Funktion `KicktippClient.fetch_bonus_ranking()` liest die Bonus-Tippüber­
sicht — sie zeigt pro Bonusfrage (Spalten wie „Gr A", „Gr B", …, „WM", „Tor",
„HF") die bereits bekannte richtige Antwort (oder „---", falls offen) sowie
pro Spieler die dafür vergebenen Punkte. `compute_group_bonus()` summiert
daraus die Punkte aus **bereits entschiedenen** „Gr *"-Fragen je Spieler.

`build_step_rows` zieht diesen Wert während der gesamten Gruppenphase
(Spieltag-Label passt auf `^\d+\.\s*Spieltag$`) vom generischen Abgleich ab —
und hebt den Abzug ab dem ersten K.o.-Spieltag wieder auf, sodass der Bonus
dort in einem Schritt sichtbar wird. Alle anderen, noch offenen Bonusfragen
(Torschützenteam, Weltmeister) tragen aktuell 0 bei und werden nicht
gesondert behandelt — sollten sie später auflösen, gilt für sie dieselbe
Einschränkung (siehe Trade-offs).

Frontend (`web/dashboard.html`): der „Bonusfragen einrechnen"-Toggle filtert
per `match_index !== -1` statt nur `spieltag_index !== 0`, damit auch später
aufgelöste Bonusfragen korrekt mit ausgeblendet werden. `stepLabel()` zeigt für
diese Steps `Bonusfragen · <Spieltag-Label>` statt fälschlich `N. Spieltag`.

## Consequences

**Positiv:**
- Der Positionsverlauf zeigt Bonuspunkte zu dem Zeitpunkt, zu dem sie
  tatsächlich feststehen — nicht rückwirkend auf Turnierstart projiziert.
  Verifiziert: die Differenz zwischen Rekonstruktion und Kicktipp-Gesamtstand
  während der Gruppenphase entspricht jetzt exakt dem noch nicht fälligen
  Gruppensieger-Bonus (nicht mehr 0, wie fälschlich vorher angenommen); ab dem
  ersten K.o.-Spieltag ist die Differenz wieder exakt 0.
- Selbstkorrigierend für alle *rundengebundenen* Bonus-Ereignisse (Schritt 1):
  jede sonstige Diskrepanz wird automatisch als eigener Bonus-Step sichtbar.

**Negativ / Trade-offs:**
- Die Gruppensieger-Korrektur ist an das Label-Muster „N. Spieltag" für die
  Gruppenphase gekoppelt — funktioniert für Turniere mit klassischer
  Gruppenphase + K.o.-Runden (WM/EM), nicht allgemein für reine
  Rundenwettbewerbe ohne K.o.-Phase (dort gibt es aber auch kein
  „Gruppensieger"-Bonuskonzept).
- Torschützenteam/Weltmeister-Bonus wird nicht vorab korrigiert, da aktuell
  0 (unentschieden). Löst sich das später auf, dürfte derselbe
  Rückwirkungs-Effekt auftreten (Kicktipp rechnet es vermutlich ebenso
  rückwirkend in alle Seiten ein) — dann braucht es dieselbe Behandlung wie
  für die Gruppensieger-Fragen, aktuell nicht implementiert (kein Bedarf,
  solange der Wert 0 ist).
- Ein zusätzlicher HTTP-Request pro Lauf (`tippuebersicht?bonus=true`).
  Schlägt der Request fehl, fällt der Code auf `group_bonus = {}` zurück
  (Warnung statt Absturz) — dann verhält sich die Rekonstruktion wie vor
  dieser gezielten Korrektur.

## Considered Alternatives

| Option | Bewertet als |
|--------|--------------|
| So lassen (ADR 0002), Bonus komplett bei Step 0 | Falsch, sobald eine Bonusfrage nach Spieltag 1 auflöst — der beobachtete Fall, und optisch besonders auffällig (Positionsverlauf "friert" auf falschem Platz ein) |
| Nur den generischen Pro-Spieltag-Abgleich (Schritt 1) | Fängt rundengebundene Sprünge (Se/Ac) korrekt ab, aber nicht den rückwirkend in *jede* Seite eingerechneten Gruppensieger-Bonus — genau das ursprüngliche Problem hätte weiterbestanden |
| Bonus-Sprung ignorieren (nur Endstand stimmt) | Verlauf sähe vor dem Sprung systematisch falsch aus relativ zum finalen Rang |
