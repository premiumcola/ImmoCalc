# ImmoCalc auf der eigenen Domain — Schritt für Schritt

Ziel: `https://immocalc.cloud` (oder welche Domain es wird), erreichbar von
überall, ohne einen einzigen offenen Port am Router. Alles Sichtbare für den
Nutzer: Familie + Passwort + Code aus der Authenticator-App. Alles andere
läuft unsichtbar bei Cloudflare.

Reihenfolge einhalten — vor allem Teil D erst nach Teil C, sonst sperrt das
`Secure`-Cookie das Login aus, bevor TLS da ist.

---

## A · Vorbereitung auf dem Unraid (5 Minuten, Terminal)

Diese Sitzung hier hat bewusst keinen Docker-Zugriff — diese Befehle laufen
auf dem echten Unraid-Terminal (WebGUI → Terminal, oder SSH).

1. Backup-Ordner anlegen:
   ```
   mkdir -p /mnt/user/backups/immocalc
   ```
2. Geheimnisse in die Server-Env-Datei (existiert schon, neben dem KI-Schlüssel):
   ```
   nano /mnt/user/appdata/immocalc-live/immocalc.env
   ```
   Drei Zeilen ergänzen. Werte selbst wählen, lang und zufällig — oder auf
   dem Unraid erzeugen lassen mit `openssl rand -base64 30`:
   ```
   BACKUP_PASSWORT=<mind. 20 Zeichen, gut aufheben — ohne es sind die Schnappschüsse wertlos>
   GEHEIMNIS_SCHLUESSEL=<mind. 30 Zeichen, NIE mehr ändern — sonst sind alle gespeicherten Zugangsdaten unlesbar>
   EINLADUNGS_CODE=<ein Wort für die andere Familie, z. B. 16 Zeichen>
   ```
   Danach die Datei abriegeln, damit sie nur root lesen kann:
   ```
   chmod 600 /mnt/user/appdata/immocalc-live/immocalc.env
   ```
   (`COOKIE_SECURE` und `CORS_ORIGINS` kommen erst in Teil D.)

   **Zu `GEHEIMNIS_SCHLUESSEL`:** damit verschlüsselt ImmoCalc die
   gespeicherten Zugangsdaten (Nextcloud, Postfach, KI-Schlüssel, Koofr) und
   die Zwei-Faktor-Geheimnisse in der Datenbank. Beim ersten Start nach dem
   Setzen wandelt die App vorhandene Klartext-Werte automatisch um — im Log
   steht dann `N475 — n Zugangsdaten verschlüsselt`. Diesen Wert zusammen mit
   `BACKUP_PASSWORT` an einem sicheren Ort ausserhalb des Servers notieren.
3. Den aktuellen devBox-Stand holen und den Stack neu aufsetzen — das übernimmt
   das neue Backup-Mount und die Container-Härtung (`cap_drop`):
   ```
   cd /mnt/user/appdata/devbox-src && git pull
   cd immocalc && docker compose pull && docker compose up -d
   docker logs immocalc-api --tail 30
   ```
   Im Log muss `ImmoCalc API bereit` stehen. Danach in der App unter
   Einstellungen → Backups prüfen: die Zeile „Zusätzlich sichert der Betreiber
   jede Nacht …" darf nicht mehr „nicht eingerichtet" sagen.
4. **Kurz gegenprüfen, dass nichts kaputt ist** — über die LAN-Adresse
   `http://192.168.178.10:8091` anmelden. Klappt das, ist alles heil, und du
   kannst in Ruhe weitermachen. (Bis Teil D bleibt diese Adresse nutzbar.)
5. Den Backup-Ordner von Unraid aus zusätzlich woanders hin spiegeln — die
   Nextcloud läuft auf derselben Kiste und zählt nicht als Offsite. Entweder
   über das Unraid-Plugin *Appdata Backup* (Ziel: eine externe Platte oder
   ein Netzlaufwerk) oder per `rclone sync /mnt/user/backups/immocalc
   <ziel>:immocalc` als nächtlicher Cron. Das ist der letzte Baustein, der
   aus „Festplatte kaputt" eine Unannehmlichkeit statt eines Verlusts macht.

## B · Domain und Cloudflare (10 Minuten, Browser)

1. Domain registrieren (`immocalc.cloud`) — beim Registrar deiner Wahl.
2. Cloudflare-Konto anlegen (kostenlos): https://dash.cloudflare.com
   → „Add a site" → Domain eintragen → Free-Plan → Cloudflare zeigt zwei
   Nameserver.
3. Beim Registrar die Nameserver der Domain auf diese beiden Cloudflare-
   Nameserver umstellen. Dauert bis zu ein paar Stunden; Cloudflare schickt
   eine Mail, sobald die Zone „active" ist. Bis dahin kannst du Teil C schon
   vorbereiten.
4. Sobald aktiv, in der Zone unter **SSL/TLS**:
   - Encryption mode: **Full** (nicht „Flexible")
   - **Edge Certificates → Always Use HTTPS: On**

## C · Der Tunnel (10 Minuten, Browser + einmal Terminal)

1. Cloudflare-Dashboard → **Zero Trust** (links, „Zero Trust" — beim ersten
   Mal einen Team-Namen vergeben, Free-Plan wählen).
2. **Networks → Tunnels → Create a tunnel → Cloudflared** → Name `immocalc`.
3. Connector: **Docker** wählen. Cloudflare zeigt einen langen Befehl mit
   `--token eyJ…`. Nur den Token kopieren (alles nach `--token`).
4. Auf dem Unraid-Terminal den Token in eine eigene Datei legen (nie ins Repo):
   ```
   printf 'TUNNEL_TOKEN=%s\n' '<hier den Token einfügen>' > /mnt/user/appdata/immocalc-live/cloudflared.env
   chmod 600 /mnt/user/appdata/immocalc-live/cloudflared.env
   ```
5. In `/mnt/user/appdata/devbox-src/immocalc/docker-compose.yml` den
   vorbereiteten Block `cloudflared:` **einkommentieren** (steht ganz unten,
   jede Zeile beginnt mit `# `), dann:
   ```
   cd /mnt/user/appdata/devbox-src/immocalc && docker compose up -d
   docker logs immocalc-cloudflared --tail 20
   ```
   Im Log: `Registered tunnel connection` — dann steht der Tunnel. Im
   Cloudflare-Dashboard springt der Connector auf „Healthy".
6. Zurück im Dashboard, Tab **Public Hostname → Add a public hostname**:
   - Subdomain: leer · Domain: `immocalc.cloud` · Path: leer
   - Service: Type **HTTP**, URL **`dashboard:80`**
   Das ist die **einzige** Regel. Nichts anderes wird veröffentlicht — genau
   das „nur diese eine App verbinden".
7. Test vom Handy über **Mobilfunk** (WLAN aus): `https://immocalc.cloud`
   muss die Anmeldeseite zeigen.

## D · Cookie scharf schalten (2 Minuten, Terminal) — ERST JETZT

Erst wenn Teil C funktioniert. In der Compose-Datei beim Service `api` die
beiden vorbereiteten Zeilen einkommentieren:
```
COOKIE_SECURE: "true"
CORS_ORIGINS: "https://immocalc.cloud"
```
dann `docker compose up -d`. Ab jetzt: **immer über die Domain anmelden**,
auch zuhause — die alte Adresse `http://192.168.178.10:8091` funktioniert
für das Login danach nicht mehr (so entschieden: eine Adresse überall).

## E · Die unsichtbaren Schichten (10 Minuten, Browser, alles kostenlos)

In der Cloudflare-Zone `immocalc.cloud`:

1. **Security → WAF → Custom rules → Create rule** „Nur Deutschland":
   - Field `Country` · Operator `does not equal` · Value `Germany`
   - Action **Block**. Deploy.
   → Im Urlaub im Ausland: diese Regel kurz auf „Disabled" stellen.
2. **Security → WAF → Rate limiting rules → Create rule** „Login-Bremse":
   - Field `URI Path` · Operator `starts with` · Value `/api/auth/`
   - Rate: **10 requests / 1 minute**, same IP · Action **Block** für 10 Minuten.
3. **Security → Bots → Bot Fight Mode: On**.
4. **Security → Settings → Security Level: Medium** (Standard reicht).

Damit hämmert nichts mehr bis zur Anmeldeseite durch, und was durchkommt,
scheitert am Code aus der App.

## F · Erster Login und Nutzer

1. `https://immocalc.cloud` → Familie `Heidenreich` + Passwort → anmelden.
2. Einstellungen → **Zwei-Faktor-Anmeldung** → einrichten (Google
   Authenticator: „+" → „Einrichtungsschlüssel eingeben"). Die
   Wiederherstellungscodes aufschreiben.
3. Einstellungen → **Backups** → Backup-Passwort setzen, Rhythmus täglich,
   Ziel WebDAV (Koofr-Konto unter https://koofr.eu anlegen, dort Einstellungen
   → Passwort → App-Passwort erzeugen) → „Jetzt sichern" einmal drücken und
   in Koofr nachsehen, dass die Datei unter `ImmoCalc-Backups/` liegt.
4. Der anderen Familie die Domain und den `EINLADUNGS_CODE` geben — sie legt
   sich über „Neue Familie anlegen" selbst an und richtet 2FA + Backup ein.

## Wenn etwas schiefgeht

- **Tunnel „Healthy", aber die Seite lädt nicht:** Public Hostname prüft —
  Service muss `http://dashboard:80` sein (Container-Name im Compose-Netz).
- **Login sagt „nicht angemeldet" in Endlosschleife:** `COOKIE_SECURE` steht
  auf true, aber du bist über `http://` unterwegs — Domain benutzen.
- **Zurück auf Anfang:** `docker compose down`, Compose-Änderungen
  rückgängig, `docker compose up -d`. Die Datenbank fasst nichts davon an.
- **Komplett neu aufsetzen:** leeres `/data`, Container starten, auf der
  Anmeldeseite „Backup wiederherstellen" → jüngster Schnappschuss +
  `BACKUP_PASSWORT`.
