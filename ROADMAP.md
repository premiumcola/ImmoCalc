# ImmoCalc — Roadmap

## ✅ Erledigt
- Frontend-Mockups (App, Onboarding-Wizard, Logo-Auswahl), Design-System
- Fachkonzept (Rechenlogik + Verteilerschlüssel), ER-Diagramm
- Deploy jFlow-Stil (LIVE/DEV, .env, deploy.sh, Unraid)
- **Backend**: FastAPI + SQLite, Datenmodell, Seed der 2 echten Objekte
- **Rechen-Engine** + Tests gegen die Excel-Zahlen (Interpolation, Rest-Zähler,
  Verteilung, Bewohnermonate, §35a, Abrechnung) — grün
- **Frontend↔API** verdrahtet (`/api`-Proxy, Live-Daten-Seite `status.html`)
- Selfcheck-Harness (Playwright) für den Agenten

## ▶ Als Nächstes (Kern)
1. **Anteile in der Engine berechnen** statt im Seed vorgeben:
   aus Verteilerschlüssel + Zählern/Ablesungen + Bewohnermonaten + Fläche.
2. **Schreib-Endpunkte** (POST/PUT/DELETE) für Objekte/Zeiträume/Positionen;
   Frontend-Formulare anbinden (Onboarding schreibt echte Objekte).
3. **Beleg-Upload** + PDF-Anhang an Position (Datei speichern unter `/data`).
4. **OCR-Worker** `immocalc-ocr` (eigener Service): Betrag/Datum/Lieferant/
   Kostenart-Vorschlag; Prüf-/Bestätigen-Schritt.
5. **PDF-Worker** `immocalc-pdf`: Abrechnung je Partei als PDF (inkl. §35a,
   Vorjahresvergleich).
6. **Zähler & Ablesungen**-CRUD inkl. Interpolation + virtuelle Zähler in der UI.

## ⏭ Betrieb & Ausbau
- **Excel-Import** der Altdaten (die 2 xlsx) → Historie + zusätzliche Testfixtures
- **Auth/Login** (echte Mieterdaten) + **DB-Backups** (Unraid)
- **Fristen-Monitoring** § 556 mit Benachrichtigung
- **Audit/Historie** (final vs. vorläufig, Änderungsverlauf)
- **Export** (Excel/CSV), später **Mieter-Portal**, **Mail-Versand**,
  **Verbrauchs-Dashboards** über Jahre
