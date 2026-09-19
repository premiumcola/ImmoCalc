# ImmoCalc auf der eigenen Domain — Schritt für Schritt

Ziel: `https://immocalc.cloud` (oder welche Domain es wird), erreichbar von
überall, ohne einen einzigen offenen Port am Router. Alles Sichtbare für den
Nutzer: Familie + Passwort + Code aus der Authenticator-App. Alles andere
läuft unsichtbar bei Cloudflare.

**Reihenfolge — wichtiger als die Buchstaben.** Die Teile sind alphabetisch
benannt, abgearbeitet werden sie aber so:

    A  →  F  →  C  →  D  →  E
    ↑     ↑     ↑     ↑     ↑
    │     │     │     │     └─ Filter (geht nur, wenn die Domain steht)
    │     │     │     └─────── Cookie (NUR nach nachweislich laufendem Tunnel)
    │     │     └───────────── Tunnel: ab hier ist die App im Internet
    │     └─────────────────── 2FA + Backup — NOCH im Heimnetz, vor dem Live-Gang
    └───────────────────────── Server vorbereiten

(Teil B, Domain und Cloudflare, ist am 16.09. bereits erledigt.)

Der Grund für **F vor C**: das Konto absichern, solange die App nur im
Heimnetz hängt. Zwei-Faktor und Backup einzurichten, während die Seite schon
öffentlich erreichbar ist, dreht die Reihenfolge genau falsch herum — und
wenn beim Einrichten etwas hakt, merkst du es ohne Publikum.

Und **D erst nach C**, sonst sperrt das `Secure`-Cookie das Login aus, bevor
TLS überhaupt da ist.

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

   **`ADMIN_FAMILIE` brauchst du nicht** (N501): ohne die Angabe wird die
   zuerst angelegte Familie zum Administratorkonto — das ist `Heidenreich`.
   Gesetzt wird das beim Start einmal und danach nie wieder umgehängt, auch
   wenn die Variable später anders lautet.

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

## F · Konto absichern — VOR dem Tunnel, noch im Heimnetz

> Nicht am Ende, sondern direkt nach Teil A: über
> `http://192.168.178.10:8091`, solange von aussen noch niemand drankommt.
> Punkt 1 lautet dann `http://192.168.178.10:8091` statt der Domain.

1. `https://immocalc.cloud` → Familie `Heidenreich` + Passwort → anmelden.
   (Das E-Mail-Feld bleibt leer, solange an deinem Zugang keine Adresse
   hinterlegt ist — siehe Punkt 4.)
2. Einstellungen → **Zwei-Faktor-Anmeldung** → einrichten (Google
   Authenticator: „+" → „Einrichtungsschlüssel eingeben" oder den QR-Code
   scannen). Die Wiederherstellungscodes aufschreiben — ohne sie kommst du
   ohne das Handy nicht mehr hinein.
3. Einstellungen → **Backups** → Backup-Passwort setzen, Rhythmus täglich,
   Ziel WebDAV (Koofr-Konto unter https://koofr.eu anlegen, dort Einstellungen
   → Passwort → App-Passwort erzeugen) → „Jetzt sichern" einmal drücken und
   in Koofr nachsehen, dass die Datei unter `ImmoCalc-Backups/` liegt.
4. **Neu (N501):** Einstellungen → **E-Mail-Adresse** → deine Adresse
   eintragen. Ab diesem Moment gehört sie zur Anmeldung: Familienname +
   E-Mail + Passwort. Sie ist später der Weg zurück, wenn das Passwort
   einmal weg ist. Merke dir, welche Schreibweise du genommen hast — geprüft
   wird ohne Rücksicht auf Gross-/Kleinschreibung, aber sie muss stimmen.
5. Der anderen Familie die Domain und den `EINLADUNGS_CODE` geben — sie legt
   sich über „Neue Familie anlegen" selbst an.

   **Neu (N502):** direkt nach dem Anlegen landet sie auf der Seite
   „Zwei-Faktor-Anmeldung einrichten" und kommt da nicht heraus, bevor sie
   eingerichtet hat. Bis dahin kann sie **nichts anlegen und nichts ändern**
   — Lesen geht, Schreiben nicht. Das ist so gewollt; sag ihr, dass sie eine
   Authenticator-App bereithalten soll, bevor sie anfängt.

## Was noch fehlt (Stand 19.09.2026)

Online gehen kannst du jetzt. Vom Einladungssystem, das du beschrieben hast,
sind aber erst zwei von fünf Stücken gebaut:

| | |
|---|---|
| ✅ E-Mail am Zugang, letzter Login, Administratorkonto | N501 |
| ✅ Zwei-Faktor-Zwang: ohne zweiten Faktor entsteht nichts | N502 |
| ⬜ Einladungen, die **du** je Person ausstellst und die per Mail gehen | offen |
| ⬜ Nutzerübersicht im Administratorkonto (letzte Logins, Anzahl Objekte) | offen |
| ⬜ Passwort zurücksetzen per Mail **plus** zweitem Faktor | offen |

Praktisch heisst das: **`EINLADUNGS_CODE` ist heute EIN gemeinsames Wort für
alle**, kein Link je Person. Wer ihn hat, kann sich eine Familie anlegen.
Für zwei Familien, die einander kennen, reicht das; ab der dritten willst du
die echten Einladungen. Wenn du den Code weitergibst, dann einzeln und nicht
über einen Kanal, der ihn dauerhaft aufbewahrt — und ändere ihn, sobald alle
drin sind (in der env-Datei, dann `docker compose up -d`).

Ebenso: ein vergessenes Passwort kannst du heute nur über die Datenbank
zurücksetzen, nicht über die Oberfläche. Solange nur ihr zwei drin seid, ist
das verkraftbar.

## Wenn etwas schiefgeht

- **Tunnel „Healthy", aber die Seite lädt nicht:** Public Hostname prüft —
  Service muss `http://dashboard:80` sein (Container-Name im Compose-Netz).
- **Login sagt „nicht angemeldet" in Endlosschleife:** `COOKIE_SECURE` steht
  auf true, aber du bist über `http://` unterwegs — Domain benutzen.
- **„Familie oder Passwort falsch", obwohl beides stimmt:** an dem Zugang ist
  eine E-Mail-Adresse hinterlegt (N501), und das Feld war leer oder enthielt
  eine andere. Die Meldung ist mit Absicht für beide Fälle dieselbe — von
  aussen soll niemand erkennen, welche Angabe nicht passte.
- **Es landet alles auf „Zwei-Faktor-Anmeldung einrichten":** genau so soll
  es sein (N502). Ohne bestätigten zweiten Faktor lässt sich nichts anlegen
  oder ändern; der Weg hinaus führt nur durch das Einrichten — oder über
  „Abmelden" ganz unten auf der Seite.
- **Zurück auf Anfang:** `docker compose down`, Compose-Änderungen
  rückgängig, `docker compose up -d`. Die Datenbank fasst nichts davon an.
- **Komplett neu aufsetzen:** leeres `/data`, Container starten, auf der
  Anmeldeseite „Backup wiederherstellen" → jüngster Schnappschuss +
  `BACKUP_PASSWORT`.
