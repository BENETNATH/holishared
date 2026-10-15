"""Programme de l'événement au format iCal, en lecture seule (B037).

Génération en pur Python (RFC 5545) : une VEVENT par activité (non « dropped »)
et par repas. Heures locales flottantes (sans TZID) ; UID stables par objet
pour que les apps calendrier mettent à jour au lieu de dupliquer.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from app.i18n import label
from app.models import Activity, Event, Meal

PRODID = "-//holishared//FR"
SLOT_TIME = {"lunch": time(12, 0), "dinner": time(20, 0)}


def _esc(value: str) -> str:
    """Échappement des champs texte ICS (RFC 5545 §3.3.11)."""
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _vevent(
    event: Event,
    kind: str,
    obj_id: str,
    start: date | datetime,
    end: date | datetime,
    summary: str,
    location: str = "",
    description: str = "",
) -> list[str]:
    lines = [
        "BEGIN:VEVENT",
        f"UID:holishared-{event.code}-{kind}-{obj_id}",
        f"DTSTAMP:{_stamp()}",
    ]
    if isinstance(start, date) and not isinstance(start, datetime):
        lines.append(f"DTSTART;VALUE=DATE:{start:%Y%m%d}")
        lines.append(f"DTEND;VALUE=DATE:{end:%Y%m%d}")
    else:
        lines.append(f"DTSTART:{start:%Y%m%dT%H%M%S}")
        lines.append(f"DTEND:{end:%Y%m%dT%H%M%S}")
    lines.append(f"SUMMARY:{_esc(summary)}")
    if location:
        lines.append(f"LOCATION:{_esc(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_esc(description)}")
    lines.append("END:VEVENT")
    return lines


def build_ics(event: Event, activities: list[Activity], meals: list[Meal]) -> str:
    """VCALENDAR complet (CRLF, RFC 5545) : activités puis repas, dans l'ordre donné."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        f"X-WR-CALNAME:{_esc(event.title)}",
    ]
    for act in activities:
        if act.start_time is None:
            start: date | datetime = act.date
            end: date | datetime = act.date + timedelta(days=1)
        else:
            start = datetime.combine(act.date, act.start_time)
            end = (
                datetime.combine(act.date, act.end_time)
                if act.end_time
                else start + timedelta(hours=1)
            )
        lines += _vevent(event, "act", act.id, start, end, act.title, act.location, act.description)
    for meal in meals:
        start = datetime.combine(meal.date, SLOT_TIME.get(meal.slot, time(12, 0)))
        summary = f"{label(meal.slot, 'meal_slot')} — {meal.title}"
        lines += _vevent(event, "meal", meal.id, start, start + timedelta(hours=1), summary)
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
