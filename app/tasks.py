"""RQ background tasks — async email sending.

These functions are called by the RQ worker (separate process). They are
standalone: no Flask app context required. All SMTP config is passed
explicitly as arguments.
"""

import logging
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _smtp_send(host: str, port: int, user: str, password: str,
               frm: str, to: str, subject: str, body: str) -> None:
    """Send a plain-text email via SMTP."""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = frm
    msg["To"] = to
    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, password)
        s.send_message(msg)
    logger.info("Email sent to %s (%s)", to, subject)


def send_verification_email(smtp_host: str, smtp_port: int, smtp_user: str,
                            smtp_password: str, smtp_from: str,
                            to_addr: str, event_title: str,
                            verify_url: str) -> None:
    """Send verification email with link to set code + nickname."""
    body = f"""Bonjour,

Tu as créé l'événement "{event_title}" sur holishared.

Pour finaliser, clique sur ce lien (valide 3 jours) :

{verify_url}

Tu y définiras ton code personnel et ton pseudo, et tu pourras inviter tes proches.

— holishared
"""
    _smtp_send(smtp_host, smtp_port, smtp_user, smtp_password, smtp_from,
               to_addr, "Valide ton événement - holishared", body)


def send_invite_email(smtp_host: str, smtp_port: int, smtp_user: str,
                      smtp_password: str, smtp_from: str,
                      to_addr: str, event_title: str,
                      start_date: str, end_date: str,
                      location: str, join_url: str) -> None:
    """Send an invite email to a guest (email NOT stored)."""
    location_line = f"Lieu : {location}\n" if location else ""
    body = f"""Bonjour,

Tu es invité(e) à l'événement "{event_title}" sur holishared.

Dates : {start_date} → {end_date}
{location_line}Pour rejoindre, clique ici :

{join_url}

Tu choisiras ton pseudo et ton code personnel.

— holishared
"""
    _smtp_send(smtp_host, smtp_port, smtp_user, smtp_password, smtp_from,
               to_addr, f"Invitation : {event_title}", body)


def send_guest_invite_email(smtp_host: str, smtp_port: int, smtp_user: str,
                            smtp_password: str, smtp_from: str,
                            to_addr: str, event_title: str,
                            start_date: str, end_date: str,
                            join_url: str,
                            display_name: str | None = None) -> None:
    """Send a guest the invitation to create their personal code."""
    name = f" {display_name}" if display_name else ""
    body = f"""Bonjour{name},

Tu es invité(e) à l'événement "{event_title}" sur holishared
({start_date} → {end_date}).

Pour rejoindre, crée ton code personnel (4 à 8 lettres/chiffres que tu
retiendras) en suivant ce lien :

{join_url}

Ton code te servira à te reconnecter sur un autre appareil.

— holishared
"""
    _smtp_send(smtp_host, smtp_port, smtp_user, smtp_password, smtp_from,
               to_addr, f"Invitation : {event_title} - holishared", body)


def send_recovery_email(smtp_host: str, smtp_port: int, smtp_user: str,
                        smtp_password: str, smtp_from: str,
                        to_addr: str, personal_code: str,
                        display_name: str) -> None:
    """Send recovery email with the personal code."""
    body = f"""Bonjour,

Ton code personnel holishared est : {personal_code}

Pseudo : {display_name}

— holishared
"""
    _smtp_send(smtp_host, smtp_port, smtp_user, smtp_password, smtp_from,
               to_addr, "Ton code holishared", body)
