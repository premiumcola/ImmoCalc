"""Mailversand über einen bestehenden Postfach-Zugang (SMTP).

Bewusst kein eigener Mailserver: Abrechnungen kommen von der echten Adresse
des Vermieters. Eine frische Domain ohne SPF/DKIM landet sonst im Spam.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from collections.abc import Callable, Iterator
from contextlib import contextmanager
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

    @contextmanager
    def verbindung_offen(self, timeout: float = 20.0) -> Iterator[smtplib.SMTP]:
        """Eine angemeldete Verbindung für einen ganzen Versandlauf.

        `sende()` baute je Mail eine eigene Verbindung samt Login auf. Beim
        Sammelversand eines Hauses mit zwölf Einheiten (Ehepaare zählen doppelt)
        sind das über zwanzig Anmeldungen in Folge — GMX und Web.de werten das
        als Missbrauch, drosseln ab, und der Lauf kippt mitten drin mit
        SMTPAuthenticationError oder „421 too many connections". Die Hälfte der
        Mieter hat dann ihre Abrechnung, die andere nicht. Ein Login pro Lauf
        statt eines pro Empfänger.
        """
        try:
            smtp = self._verbindung(timeout)
            smtp.login(self.benutzer, self.passwort)
        except smtplib.SMTPAuthenticationError as e:
            raise MailFehler(
                "Anmeldung abgelehnt — bei GMX muss der Versand über externe "
                "Programme freigeschaltet sein (Einstellungen → POP3/IMAP)."
            ) from e
        except (smtplib.SMTPException, OSError) as e:
            raise MailFehler(f"Mailserver nicht erreichbar: {e}") from e
        try:
            yield smtp
        finally:
            # Ein Server, der die Verbindung vor dem QUIT kappt, darf einen
            # sonst gelungenen Lauf nicht nachträglich zum Fehler machen.
            try:
                smtp.quit()
            except (smtplib.SMTPException, OSError):
                pass
            finally:
                smtp.close()

    def pruefe(self) -> dict:
        """Anmeldung testen, ohne eine Mail zu senden."""
        with self.verbindung_offen():
            pass
        return {"ok": True, "server": self.server, "absender": self.absender}

    def sende(self, an: str, betreff: str, text: str,
              anhang: tuple[str, bytes, str] | None = None,
              smtp: smtplib.SMTP | None = None) -> None:
        """Verschickt eine Mail; `anhang` ist (Dateiname, Inhalt, MIME-Subtyp).

        `smtp` ist eine offene Verbindung aus `verbindung_offen()`. Fehlt sie,
        öffnet `sende` wie bisher selbst eine — die Einzelaufrufer (Testmail,
        Strom, Tankstelle) bleiben damit unverändert.
        """
        an = (an or "").strip()
        if not an:
            raise MailFehler("Keine Empfängeradresse angegeben.")
        # Der Aufbau der Nachricht gehört mit in den Fehlerfang: eine kopierte
        # Adresse mit Zeilenumbruch lässt `nachricht["To"] = an` mit ValueError
        # platzen. Stand das außerhalb, war das kein MailFehler — der
        # Sammelversand brach mit HTTP 500 ab, ohne zu sagen, wer seine Mail
        # schon hat, und der Nutzer stand vor einem halb versendeten Zeitraum.
        try:
            nachricht = EmailMessage()
            nachricht["From"] = formataddr((self.absender_name or "",
                                            self.absender))
            nachricht["To"] = an
            nachricht["Subject"] = betreff
            nachricht.set_content(text)
            if anhang:
                name, inhalt, subtyp = anhang
                nachricht.add_attachment(inhalt, maintype="application",
                                         subtype=subtyp, filename=name)
        except ValueError as e:
            raise MailFehler(
                f"Die Adresse {an!r} ist unbrauchbar (Zeilenumbruch oder "
                f"unerlaubtes Zeichen) — bitte im Mietverhältnis "
                f"korrigieren: {e}") from e
        try:
            if smtp is not None:
                smtp.send_message(nachricht)
            else:
                with self.verbindung_offen() as eigene:
                    eigene.send_message(nachricht)
        except (smtplib.SMTPException, OSError) as e:
            raise MailFehler(f"Versand fehlgeschlagen: {e}") from e
        log.info("Mail an %s versendet", an)


@contextmanager
def versandlauf(zugang: Zugang) -> Iterator[Callable[..., None]]:
    """Bündelt einen Sammelversand auf einer einzigen SMTP-Verbindung.

    Zurück kommt eine Funktion mit derselben Signatur wie `Zugang.sende`. Der
    Aufrufer merkt vom Unterschied nichts, spart aber je Empfänger eine
    Anmeldung — siehe `Zugang.verbindung_offen`.

    Ein Versender ohne `verbindung_offen` (Ersatz-Postfach im Prüfstand) sendet
    unverändert einzeln weiter; ein fehlendes Bündel darf keinen Lauf
    verhindern.
    """
    offen = getattr(zugang, "verbindung_offen", None)
    if offen is None:
        yield zugang.sende
        return
    with offen() as smtp:
        def senden(an: str, betreff: str, text: str,
                   anhang: tuple[str, bytes, str] | None = None) -> None:
            zugang.sende(an, betreff, text, anhang=anhang, smtp=smtp)
        yield senden
