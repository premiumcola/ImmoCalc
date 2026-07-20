"""Mailversand über einen bestehenden Postfach-Zugang (SMTP).

Bewusst kein eigener Mailserver: Abrechnungen kommen von der echten Adresse
des Vermieters. Eine frische Domain ohne SPF/DKIM landet sonst im Spam.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

log = logging.getLogger("immocalc")

# Voreinstellungen gängiger Anbieter — erspart das Nachschlagen der Serverdaten
ANBIETER = {
    "gmx": {"name": "GMX", "server": "mail.gmx.net", "port": 587, "tls": "starttls"},
    "webde": {"name": "WEB.DE", "server": "smtp.web.de", "port": 587, "tls": "starttls"},
    "gmail": {"name": "Gmail", "server": "smtp.gmail.com", "port": 587, "tls": "starttls"},
    "ionos": {"name": "IONOS", "server": "smtp.ionos.de", "port": 587, "tls": "starttls"},
    "mailbox": {"name": "mailbox.org", "server": "smtp.mailbox.org", "port": 587,
                "tls": "starttls"},
    "custom": {"name": "Anderer Anbieter", "server": "", "port": 587, "tls": "starttls"},
}


class MailFehler(RuntimeError):
    pass


@dataclass
class Zugang:
    server: str
    port: int
    benutzer: str
    passwort: str
    absender: str
    absender_name: str = ""
    tls: str = "starttls"          # 'starttls' | 'ssl'

    def _verbindung(self, timeout: float = 20.0):
        kontext = ssl.create_default_context()
        if self.tls == "ssl":
            return smtplib.SMTP_SSL(self.server, self.port, timeout=timeout,
                                    context=kontext)
        smtp = smtplib.SMTP(self.server, self.port, timeout=timeout)
        smtp.starttls(context=kontext)
        return smtp

    def pruefe(self) -> dict:
        """Anmeldung testen, ohne eine Mail zu senden."""
        try:
            with self._verbindung() as smtp:
                smtp.login(self.benutzer, self.passwort)
        except smtplib.SMTPAuthenticationError as e:
            raise MailFehler(
                "Anmeldung abgelehnt — bei GMX muss der Versand über externe "
                "Programme freigeschaltet sein (Einstellungen → POP3/IMAP)."
            ) from e
        except (smtplib.SMTPException, OSError) as e:
            raise MailFehler(f"Mailserver nicht erreichbar: {e}") from e
        return {"ok": True, "server": self.server, "absender": self.absender}

    def sende(self, an: str, betreff: str, text: str,
              anhang: tuple[str, bytes, str] | None = None) -> None:
        """Verschickt eine Mail; `anhang` ist (Dateiname, Inhalt, MIME-Subtyp)."""
        nachricht = EmailMessage()
        nachricht["From"] = formataddr((self.absender_name or "", self.absender))
        nachricht["To"] = an
        nachricht["Subject"] = betreff
        nachricht.set_content(text)
        if anhang:
            name, inhalt, subtyp = anhang
            nachricht.add_attachment(inhalt, maintype="application",
                                     subtype=subtyp, filename=name)
        try:
            with self._verbindung() as smtp:
                smtp.login(self.benutzer, self.passwort)
                smtp.send_message(nachricht)
        except (smtplib.SMTPException, OSError) as e:
            raise MailFehler(f"Versand fehlgeschlagen: {e}") from e
        log.info("Mail an %s versendet", an)
