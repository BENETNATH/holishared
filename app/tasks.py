"""RQ background tasks — async email sending.

These functions are called by the RQ worker (separate process). They are
standalone: no Flask app context required. All SMTP config is passed
explicitly as arguments, and the language as ``lang`` (default ``fr``): the
catalog is loaded with ``babel.support.Translations`` (B018).
"""

import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from babel.support import NullTranslations, Translations

logger = logging.getLogger(__name__)

_TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent / "translations"
_SUPPORTED = ("fr", "en")


def _translations(lang: str) -> NullTranslations:
    """Catalogue de ``lang`` (repli : français, langue source des msgids)."""
    return Translations.load(str(_TRANSLATIONS_DIR), [lang if lang in _SUPPORTED else "fr"])


def _smtp_send(
    host: str, port: int, user: str, password: str, frm: str, to: str, subject: str, body: str
) -> None:
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


def send_verification_email(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    smtp_from: str,
    to_addr: str,
    event_title: str,
    verify_url: str,
    lang: str = "fr",
) -> None:
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
    _smtp_send(
        smtp_host,
        smtp_port,
        smtp_user,
        smtp_password,
        smtp_from,
        to_addr,
        _("Validez votre événement - holishared"),
        body,
    )


def send_invite_email(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    smtp_from: str,
    to_addr: str,
    event_title: str,
    start_date: str,
    end_date: str,
    location: str,
    join_url: str,
    lang: str = "fr",
) -> None:
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
    ) % {
        "title": event_title,
        "start": start_date,
        "end": end_date,
        "location_line": location_line,
        "url": join_url,
    }
    _smtp_send(
        smtp_host,
        smtp_port,
        smtp_user,
        smtp_password,
        smtp_from,
        to_addr,
        _("Invitation : %(title)s") % {"title": event_title},
        body,
    )


def send_guest_invite_email(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    smtp_from: str,
    to_addr: str,
    event_title: str,
    start_date: str,
    end_date: str,
    join_url: str,
    display_name: str | None = None,
    lang: str = "fr",
) -> None:
    """Send a guest the invitation to create their personal code."""
    _ = _translations(lang).gettext
    greeting = _("Bonjour %(name)s,") % {"name": display_name} if display_name else _("Bonjour,")
    body = (
        greeting
        + "\n\n"
        + _(
            "Vous êtes invité(e) à l'événement « %(title)s » sur holishared\n"
            "(%(start)s → %(end)s).\n\n"
            "Pour rejoindre, créez votre code personnel (4 à 8 lettres ou chiffres "
            "que vous retiendrez) en suivant ce lien :\n\n"
            "%(url)s\n\n"
            "Votre code vous servira à vous reconnecter sur un autre appareil.\n\n"
            "— holishared\n"
        )
        % {"title": event_title, "start": start_date, "end": end_date, "url": join_url}
    )
    _smtp_send(
        smtp_host,
        smtp_port,
        smtp_user,
        smtp_password,
        smtp_from,
        to_addr,
        _("Invitation : %(title)s - holishared") % {"title": event_title},
        body,
    )


def send_recovery_email(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    smtp_from: str,
    to_addr: str,
    personal_code: str,
    display_name: str,
    lang: str = "fr",
) -> None:
    """Send recovery email with the personal code."""
    _ = _translations(lang).gettext
    body = _(
        "Bonjour,\n\n"
        "Votre code personnel holishared est : %(code)s\n\n"
        "Pseudo : %(name)s\n\n"
        "— holishared\n"
    ) % {"code": personal_code, "name": display_name}
    _smtp_send(
        smtp_host,
        smtp_port,
        smtp_user,
        smtp_password,
        smtp_from,
        to_addr,
        _("Votre code holishared"),
        body,
    )


PUSH_GONE = (404, 410)  # le service de push signale un abonnement expiré


def _push_db(database_url: str, sql: str, params: dict[str, object]) -> None:
    """Écriture ponctuelle sur la base de l'application (le worker n'a pas de contexte Flask)."""
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url, connect_args={"timeout": 5})
    try:
        with engine.begin() as conn:
            conn.execute(text(sql), params)
    except Exception:  # l'envoi a eu lieu : un échec de suivi ne le remet pas en cause
        logger.warning("push bookkeeping failed", exc_info=True)
    finally:
        engine.dispose()


def send_push(
    sub: dict[str, str],
    payload: str,
    vapid_private: str = "",
    vapid_subject: str = "",
    database_url: str = "",
) -> str:
    """Envoie une notification Web Push (tâche RQ, sans contexte Flask).

    ``sub`` = id, endpoint, p256dh, auth. La config vient des arguments, sinon de l'environnement
    du worker (``VAPID_PRIVATE_KEY``, ``VAPID_CLAIMS_SUBJECT``, ``DATABASE_URL``) : la clé privée
    n'a ainsi pas à transiter par Redis. Retourne ``sent``, ``gone`` (abonnement supprimé),
    ``skipped`` (pas de clés) ou ``error`` ; ne lève jamais.
    """
    import os

    vapid_private = vapid_private or os.environ.get("VAPID_PRIVATE_KEY", "")
    vapid_subject = vapid_subject or os.environ.get("VAPID_CLAIMS_SUBJECT", "")
    database_url = database_url or os.environ.get("DATABASE_URL", "")
    if not vapid_private:
        logger.warning("push skipped: no VAPID private key sub=%s", sub.get("id"))
        return "skipped"
    try:
        from py_vapid import Vapid  # type: ignore[import-untyped]
        from pywebpush import WebPushException, webpush  # type: ignore[import-untyped]

        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload,
                vapid_private_key=Vapid.from_string(vapid_private),
                vapid_claims={"sub": vapid_subject or "mailto:admin@holishared.local"},
                ttl=3600,
                timeout=10,
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in PUSH_GONE:
                if database_url:
                    _push_db(
                        database_url,
                        "DELETE FROM push_subscriptions WHERE id = :id",
                        {"id": sub["id"]},
                    )
                logger.info("push subscription gone sub=%s status=%s", sub.get("id"), status)
                return "gone"
            logger.warning("push failed sub=%s status=%s", sub.get("id"), status)
            return "error"
        if database_url:
            _push_db(
                database_url,
                "UPDATE push_subscriptions SET last_success_at = :now WHERE id = :id",
                {"id": sub["id"], "now": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")},
            )
        return "sent"
    except Exception:
        logger.warning("push error sub=%s", sub.get("id"), exc_info=True)
        return "error"
