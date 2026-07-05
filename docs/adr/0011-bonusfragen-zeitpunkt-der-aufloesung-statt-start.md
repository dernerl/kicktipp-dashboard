# ADR 0011: Bonus nur am aktuellen Rand des Positionsverlaufs, nicht als Zeitpunkt in der Timeline

**Date:** 2026-07-04
**Status:** Accepted

---

## Context

ADR 0002 (Positionsverlauf-Rekonstruktion) ging davon aus: „Bonus wird komplett
vor Spieltag 1 gutgeschrieben (danach konstant)" und rechnete ihn einmalig aus
Spieltag 1 (`total − Σ per_match`) zurück. Das stimmt nicht: Kicktipps
`Gesamtpunkte`-Spalte auf **jeder** per-Spieltag-Tippübersichtsseite (auch der
von Spieltag 1) enthält den zum Scrape-Zeitpunkt **aktuellen** Bonus-Stand,
nicht den zum historischen Zeitpunkt tatsächlich bekannten. Sichtbar wurde das
am Positionsverlauf selbst: mit Bonus eingerechnet lag `dernerl` von Spieltag 1
an durchgehend auf Platz 12, ohne Bonus deutlich besser — obwohl der
Gruppensieger-Bonus (der komplette „B"-Wert bestand nachweislich zu 100 % aus
korrekt getippten Gruppensiegern) unmöglich schon nach einem Spieltag bekannt
sein konnte.

**Erster Versuch (verworfen):** Bonus während der Gruppenphase aus dem
gemeldeten `total` explizit herausrechnen und erst beim ersten K.o.-Spieltag
gesammelt als ein Schritt gutschreiben. Zwei Probleme zeigten sich in der
Praxis:

1. **Grafischer Bug:** ohne echte Spiele zwischen Sechzehntelfinale und
   Achtelfinale lagen deren beide Bonus-Schritte auf der x-Achse fast
   übereinander — die "ST11"/"ST12"-Beschriftungen überlappten sich sichtbar.
2. **Fachlich ungenau:** die 12 Gruppen werden nicht alle gleichzeitig
   entschieden — Gruppe A kann Tage vor Gruppe D feststehen, je nachdem wann
   ihre Spiele im Spielplan liegen. Ein einziger gebündelter Schritt für „den
   Gruppensieger-Bonus" beim Übergang zur K.o.-Phase behauptet einen exakten
   Zeitpunkt, den es so nicht gab (vom User anhand seiner eigenen
   Tippabgabe-Seite bestätigt: die einzelnen Gruppen waren nachweislich an
   unterschiedlichen Tagen entschieden).

Eine wirklich korrekte pro-Gruppe-Zeitpunktbestimmung würde die Team-Gruppen-
Zuordnung aus dem Spielplan rekonstruieren (z.B. über Kicktipp-interne
Abkürzungscodes, die nicht direkt mit den vollen Teamnamen im Spielplan
übereinstimmen) — unverhältnismäßig komplex für den Nutzen, und vom User
explizit als nicht nötig zurückgewiesen.

## Decision

Radikal vereinfacht: der scrubbare Positionsverlauf (`ranking_steps.jsonl`)
wird ausschließlich aus **Spielpunkten** aufgebaut — keine Bonus-Rekonstruktion
unterwegs, kein Versuch, einen Auflösungszeitpunkt zu erraten. Jeder
Zeitschritt ist exakt so, wie die Tabelle nach diesem einen Spiel aussehen
würde, wenn es überhaupt keine Bonusfragen gäbe.

Der aktuell bereits bekannte Bonus (`letzter gemeldeter Gesamtstand − Σ reine
Spielpunkte`) wird **einmalig** dem letzten Schritt (dem zuletzt tatsächlich
gespielten Match) zugeschlagen — als „aktueller Stand inklusive Bonus" statt
als eigenes Ereignis mit eigenem Zeitpunkt in der Timeline.

Der „Bonusfragen einrechnen"-Toggle im Dashboard bleibt bestehen und wirkt
jetzt spürbar nur auf den letzten Punkt: mit Toggle sieht man den aktuellen
Stand inkl. Bonus, ohne Toggle den reinen Spielpunkte-Stand — beides über die
gesamte übrige Historie identisch (weil dort schlicht kein Bonus bekannt war).

`kicktipp.py`s `fetch_bonus_ranking()`/`parse_bonus_ranking()` (aus dem ersten
Versuch, um die Gruppensieger-Punkte separat auszulesen) wurden wieder
entfernt — ungenutzter Code für einen verworfenen Ansatz.

## Consequences

**Positiv:**
- Keine falschen Zeitpunkt-Behauptungen mehr: die Timeline zeigt nur, was sie
  sicher weiß (Spielpunkte je Match), der Bonus wird nur dort gezeigt, wo er
  unstrittig ist (jetzt, am aktuellen Rand).
- Grafischer Bug automatisch behoben — keine künstlichen Zusatzschritte mehr,
  die eng beieinanderliegen können.
- Deutlich weniger Code (kein Bonus-Tab-Scraping, keine Gruppenphasen-Erkennung
  per Label-Regex).

**Negativ / Trade-offs:**
- Der Toggle wirkt jetzt nur auf den letzten Punkt, nicht über die ganze
  Historie — wer erwartet, dass „Bonusfragen einrechnen" die komplette Linie
  verändert, sieht mitten in der Saison keinen Unterschied mehr. Das ist so
  gewollt (der Unterschied existiert historisch schlicht noch nicht), aber
  optisch weniger eindrücklich als der (fachlich falsche) alte Verlauf.
- Kein Versuch mehr, *irgendeinen* Bonus-Zeitpunkt zu zeigen, auch nicht
  näherungsweise — wer wissen will, wann welche Gruppe feststand, muss selbst
  in Kicktipp nachschauen.

## Considered Alternatives

| Option | Bewertet als |
|--------|--------------|
| Bonus komplett bei Step 0 (ADR 0002, Ursprungszustand) | Falsch, optisch besonders auffällig (Positionsverlauf "friert" auf falschem Platz ein) |
| Gruppensieger-Bonus gesammelt beim ersten K.o.-Spieltag (erster Fix-Versuch) | Grafischer Bug (überlappende Achsenbeschriftung) + fachlich ungenau, da Gruppen nicht gleichzeitig entschieden werden |
| Pro Gruppe exakten Auflösungs-Spieltag aus Team-Zugehörigkeit rekonstruieren | Genauer, aber Kicktipps Bonus-Ansicht nutzt Abkürzungscodes ohne direkte Zuordnung zu den vollen Teamnamen im Spielplan; unverhältnismäßiger Aufwand für den Nutzen |
| So lassen wie hier: Bonus nur am aktuellen Rand | Gewählt — ehrlich über das, was wir wissen, ohne Genauigkeit vorzutäuschen |
