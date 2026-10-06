"""RQ background tasks — async email sending.

These functions are called by the RQ worker (separate process). They are
standalone: no Flask app context required. All SMTP config is passed
explicitly as arguments, and the language as ``lang`` (default ``fr``): the
catalog is loaded with ``babel.support.Translations`` (B018).
"""

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from babel.support import NullTranslations, Translations

logger = logging.getLogger(__name__)

_TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent / "translations"
_SUPPORTED = ("fr", "en")


def _translations(lang: str) -> NullTranslations:
    """Catalogue de ``lang`` (repli : français, langue source des msgids)."""
    return Translations.load(str(_TRANSLATIONS_DIR), [lang if lang in _SUPPORTED else "fr"])


def _smtp_send(host: str, port: int, user: str, password: str,
               frm: str, to: str, subject: str, body: str) -> None:
    """Send a plain-text email via SMTP."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = frm
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, password)
        s.send_message(msg)
    logger.info("Email sent to %s (%s)", to, subject)


def send_verification_email(smtp_host: str, smtp_port: int, smtp_user: str,
                            smtp_password: str, smtp_from: str,
                            to_addr: str, event_title: str,
                            verify_url: str, lang: str = "fr") -> None:
    """Send verification email with link to set code + nickname."""
    _ = _translations(lang).gettext
    body = _(
        "Bonjour,\n\n"
        "Vous avez créé l'événement « %(title)s » sur holishared.\n\n"
        "Pour finaliser, cliquez sur ce lien (valide 3 jours) :\n\n"
        "%(url)s\n\n"
        "Vous y définirez votre code personnel et votre pseudo, "
        "et vous pourrez inviter vos proches.\n\n"
        "— holishared\n"
    ) % {"title": event_title, "url": verify_url}
    _smtp_send(smtp_host, smtp_port, smtp_user, smtp_password, smtp_from,
               to_addr, _("Validez votre événement - holishared"), body)


def send_invite_email(smtp_host: str, smtp_port: int, smtp_user: str,
                      smtp_password: str, smtp_from: str,
                      to_addr: str, event_title: str,
                      start_date: str, end_date: str,
                      location: str, join_url: str, lang: str = "fr") -> None:
    """Send an invite email to a guest (email NOT stored)."""
    _ = _translations(lang).gettext
    location_line = _("Lieu : %(location)s") % {"location": location} + "\n" if location else ""
    body = _(
        "Bonjour,\n\n"
        "Vous êtes invité(e) à l'événement « %(title)s » sur holishared.\n\n"
        "Dates : %(start)s → %(end)s\n"
        "%(location_line)s"
        "Pour rejoindre, cliquez ici :\n\n"
        "%(url)s\n\n"
        "Vous choisirez votre pseudo et votre code personnel.\n\n"
        "— holishared\n"
    ) % {"title": event_title, "start": start_date, "end": end_date,
         "location_line": location_line, "url": join_url}
    _smtp_send(smtp_host, smtp_port, smtp_user, smtp_password, smtp_from,
               to_addr, _("Invitation : %(title)s") % {"title": event_title}, body)


def send_guest_invite_email(smtp_host: str, smtp_port: int, smtp_user: str,
                            smtp_password: str, smtp_from: str,
                            to_addr: str, event_title: str,
                            start_date: str, end_date: str,
                            join_url: str,
                            display_name: str | None = None, lang: str = "fr") -> None:
    """Send a guest the invitation to create their personal code."""
    _ = _translations(lang).gettext
    greeting = _("Bonjour %(name)s,") % {"name": display_name} if display_name else _("Bonjour,")
    body = greeting + "\n\n" + _(
        "Vous êtes invité(e) à l'événement « %(title)s » sur holishared\n"
        "(%(start)s → %(end)s).\n\n"
        "Pour rejoindre, créez votre code personnel (4 à 8 lettres ou chiffres "
        "que vous retiendrez) en suivant ce lien :\n\n"
        "%(url)s\n\n"
        "Votre code vous servira à vous reconnecter sur un autre appareil.\n\n"
        "— holishared\n"
    ) % {"title": event_title, "start": start_date, "end": end_date, "url": join_url}
    _smtp_send(smtp_host, smtp_port, smtp_user, smtp_password, smtp_from,
               to_addr, _("Invitation : %(title)s - holishared") % {"title": event_title}, body)


def send_recovery_email(smtp_host: str, smtp_port: int, smtp_user: str,
                        smtp_password: str, smtp_from: str,
                        to_addr: str, personal_code: str,
                        display_name: str, lang: str = "fr") -> None:
    """Send recovery email with the personal code."""
    _ = _translations(lang).gettext
    body = _(
        "Bonjour,\n\n"
        "Votre code personnel holishared est : %(code)s\n\n"
        "Pseudo : %(name)s\n\n"
        "— holishared\n"
    ) % {"code": personal_code, "name": display_name}
    _smtp_send(smtp_host, smtp_port, smtp_user, smtp_password, smtp_from,
               to_addr, _("Votre code holishared"), body)
