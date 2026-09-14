# N469 #6 — Sicherheits-Header. Als Include, weil nginx `add_header` NICHT
# vererbt, sobald ein location-Block selbst ein `add_header` traegt: jede
# Location mit eigenem Cache-Control-Header wuerde diese Zeilen sonst still
# verlieren. Deshalb wird die Datei im server-Block UND in jeder solchen
# Location eingebunden (siehe default.conf.template).
#
# Kein Script-CSP: die Seiten tragen ihr Modul-Skript und ihre Styles inline
# und laden Google Fonts — eine Script-Richtlinie braeuchte Nonces in jeder
# Seite und wuerde ohne sie alles still abschalten. `frame-ancestors`,
# `base-uri` und `form-action` brechen nichts und schliessen Clickjacking
# sowie Formular-Umleitung.
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header X-Frame-Options "DENY" always;
add_header Content-Security-Policy "frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
add_header Permissions-Policy "camera=(self), microphone=(), geolocation=(), payment=()" always;
# Browser werten HSTS nur ueber HTTPS aus — im Heimnetz ueber http:// ist die
# Zeile wirkungslos, hinter Cloudflare (TLS am Edge) ein Jahr Pflicht-HTTPS.
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
