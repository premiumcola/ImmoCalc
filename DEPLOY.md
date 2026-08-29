# DEPLOY.md — überholt

Dieses Dokument beschrieb den alten Weg: Repo auf den Unraid klonen, dort mit
`./deploy.sh` bauen, `public/` live in den Container mounten. **So läuft es
seit dem 23.08.2026 nicht mehr**, und die Anleitung stehen zu lassen hieße,
zwei Dateien behaupten Verschiedenes.

Der heutige Weg — auf dem Server wird nichts mehr gebaut oder geklont:

```
git push  →  GitHub Actions baut  →  ghcr.io  →  Watchtower rollt aus (~5 min)
```

- **Stand, offene Punkte, Rückweg:** `MIGRATION.md`
- **Entwicklungsschleife und Überblick:** `README.md`
- **Die laufende Stack-Definition** liegt in `premiumcola/devBox` →
  `immocalc/docker-compose.yml`, nicht in diesem Repo.

`deploy.sh` ist aus derselben Zeit und ebenfalls kein Deploy-Weg mehr.
