# MIGRATION.md — ImmoCalc auf dem plexdice-Muster

**Stand: umgestellt seit 23.08.2026, mit zwei bewusst offenen Punkten**
(Datenordner-Umzug, leerer API-Schlüssel — beide unten).

Die Kette läuft: ein Repo → GitHub Actions baut nach jedem Push und nächtlich
→ `ghcr.io/premiumcola/immocalc-{api,dashboard}` → Watchtower auf dem Unraid
pollt und rollt aus. Auf dem Server wird nichts gebaut.

Nachgewiesen am 24.08.2026: `docker inspect` zeigt beide Container auf
`ghcr.io/premiumcola/immocalc-*:latest` mit `watchtower.enable=true`, und der
Healthcheck-Fix `d25be32` kam **per Watchtower von selbst** auf das laufende
System — ohne Handanlegen. Damit ist die Kette nicht nur eingerichtet, sondern
im Betrieb bewiesen.

---

## Wo die laufende Definition liegt — nicht hier

Das Umschalten geschah **über eine separate Compose-Datei im devBox-Repo**,
nicht über eine Datei dieses Repos:

```
premiumcola/devBox  →  immocalc/docker-compose.yml     ← das läuft
```

Sie wurde am 23.08. aus `docker inspect` des damals laufenden Containers
gebaut, nicht aus diesem Repo kopiert. Die frühere `docker-compose.ghcr.yml`
hier war ein **Entwurf, der nie live war** — sie ist deshalb gelöscht, damit
niemand sie künftig für die Quelle der Wahrheit hält.

Das `docker-compose.yml` in diesem Repo ist seither eine **Abbildung** der
laufenden Datei für Entwicklung und Nachschlagen. Weichen beide voneinander
ab, **gilt die Datei im devBox-Repo**. Wer die laufende Umgebung ändern will,
ändert sie dort.

## Offene Punkte — bewusst, nicht vergessen

### 1. Der Datenordner ist noch der alte

| | Pfad |
|---|---|
| **In Benutzung** | `/mnt/user/appdata/immocalc-live/data` |
| Ziel (irgendwann) | `/mnt/user/appdata/immocalc/data` |

Bewusst **nicht** mit dem Umschalten zusammengelegt: zwei riskante Schritte
gleichzeitig hätten im Fehlerfall nicht mehr auseinanderzuhalten sein können.
Der Umzug ist eine eigene Entscheidung und steht weiterhin aus.

Wenn er kommt — SQLite verträgt kein Kopieren bei laufendem Schreibzugriff:

```bash
docker compose down
mkdir -p /mnt/user/appdata/immocalc/data
rsync -a /mnt/user/appdata/immocalc-live/data/ /mnt/user/appdata/immocalc/data/
# Pfad in der devBox-Compose ändern, dann:
docker compose up -d
```

Die alten Dateien unter `immocalc-live/` bleiben als Sicherheitsnetz liegen.
Zu ändern ist der Pfad an **zwei** Stellen: der laufenden Datei im devBox-Repo
und der Abbildung hier.

### 2. Der Anthropic-Schlüssel ist leer

`/mnt/user/appdata/immocalc-live/immocalc.env` existiert und wird über
`env_file` eingebunden — der Schlüssel darin ist aber **leer**. Die
KI-Beleg-Auslese (CCLXVIII) läuft damit aktuell ins Leere; alles andere
funktioniert unverändert, die regelbasierte Erkennung trägt Datum und Betrag
weiter allein.

Zum Befüllen: Wert in diese Datei eintragen, dann `docker compose up -d`
(Neustart des api-Containers). Die Datei liegt nur auf dem Server und wird nie
versioniert — im Repo steht der Schlüssel an **keiner** Stelle.

## Was das Frontend betrifft

**Der `./public`-Bind-Mount ist weg.** Die Container servierten vorher direkt
aus `/mnt/cache-ssd/appdata/devbox/home/projects/ImmoCalc/public` — die
Produktion las also aus dem Arbeitsordner der Entwicklungsumgebung. Genau das
sollte die Trennung beenden.

Folge für die tägliche Arbeit: **eine Änderung an `public/` ist nicht mehr
sofort live.** Sie braucht Push → CI-Build → Watchtower (pollt alle 5 Minuten).
Wer das beim Entwickeln nicht will, holt sich den Mount lokal zurück:

```bash
cp docker-compose.override.yml.example docker-compose.override.yml
docker compose up -d
```

Die Override-Datei ist in `.gitignore` und kann so nie versehentlich auf den
Server gelangen.

## Aufgeräumt (25.08.2026)

- `api/Dockerfile`, `dashboard/Dockerfile` — tot. Gebaut wird ausschließlich
  `services/{api,dashboard}/Dockerfile` (siehe `.github/workflows/build.yml`).
  Das alte `dashboard/Dockerfile` trug denselben Healthcheck-Fehler wie
  `d25be32` ihn behoben hat, nur eben in der Datei, die niemand mehr baut —
  zwei Wahrheiten für dasselbe Image.
- `docker-compose.ghcr.yml` — der nie live gewesene Entwurf (siehe oben).
- Das ImmoCalc-eigene `docker-compose.yml` mit `build:` — war bis zum 24.08.
  noch der Notfall-Rückweg, weil der Cron `immo-auto` (alle 2 Minuten, im
  alten Devbox-Home-Pfad) genau diese Datei erneut deployt hat, sobald sich
  dort etwas änderte. Der Cron ist entfernt, die Datei damit wirklich verwaist
  — sie ist jetzt die `image:`-Abbildung, kein zweiter Deploy-Weg mehr.

## Wenn etwas klemmt

Zurück auf einen älteren Stand geht über das Image-Tag, nicht über einen
Rebuild: in der devBox-Compose `:latest` durch ein Kurz-SHA-Tag ersetzen (die
CI vergibt eines je Build, siehe Packages-Tab am Repo), dann
`docker compose up -d`. Genau dafür ist das Frontend jetzt im Image statt im
Arbeitsordner — vorher gab es zu einem kaputten Frontend-Stand überhaupt
keinen Rückweg.
