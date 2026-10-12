"""Feed iCal en lecture (B037) : GET /e/<code>/calendar.ics + bouton « Calendrier »."""

import re
from datetime import date, time

from app.models import Activity, Meal

ICS = "calendar.ics"


def _ics(client, event):
    resp = client.get(f"/e/{event.code}/{ICS}")
    assert resp.status_code == 200
    return resp.data.decode()


def _events(text):
    """Corps des VEVENT, dans l'ordre."""
    return re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S)


def _field(body, name):
    match = re.search(rf"^{re.escape(name)}[^:]*:(.*)$", body, re.M)
    assert match is not None, f"{name} absent"
    return match.group(1)


# --- Accès ---------------------------------------------------------------------


def test_ics_is_public_with_event_code_only(client, event):
    # Client anonyme, sans session : le code événement suffit.
    text = _ics(client, event)
    assert "BEGIN:VCALENDAR" in text
    assert "VERSION:2.0" in text


def test_ics_unknown_code_is_404(client, event):
    assert client.get(f"/e/zzzzzz/{ICS}").status_code == 404


def test_ics_unverified_event_is_404(client, unverified_event):
    assert client.get(f"/e/{unverified_event.code}/{ICS}").status_code == 404


def test_ics_content_type_and_disposition(client, event):
    resp = client.get(f"/e/{event.code}/{ICS}")
    assert resp.content_type.startswith("text/calendar")
    assert f"filename=\"holishared-{event.code}.ics\"" in resp.headers["Content-Disposition"]


# --- En-têtes -------------------------------------------------------------------


def test_ics_calendar_headers(client, event):
    text = _ics(client, event)
    assert "PRODID:-//holishared//FR" in text
    assert f"X-WR-CALNAME:{_esc('Test Vacation')}" in text


def _esc(value):
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


# --- Activités ------------------------------------------------------------------


def _activity(db, event, title="Rando", **kw):
    act = Activity(event_id=event.id, title=title, date=date(2026, 12, 2), **kw)
    db.session.add(act)
    db.session.commit()
    return act


def test_ics_all_day_activity(client, db, event):
    _activity(db, event)
    text = _ics(client, event)
    body = _events(text)[0]
    assert "DTSTART;VALUE=DATE:20261202" in body
    assert "DTEND;VALUE=DATE:20261203" in body


def test_ics_timed_activity(client, db, event):
    _activity(db, event, start_time=time(14, 30))
    body = _events(_ics(client, event))[0]
    assert "DTSTART:20261202T143000" in body
    assert "DTEND:20261202T153000" in body  # +1 h par défaut


def test_ics_timed_activity_uses_end_time(client, db, event):
    _activity(db, event, start_time=time(14, 30), end_time=time(17, 0))
    body = _events(_ics(client, event))[0]
    assert "DTEND:20261202T170000" in body


def test_ics_dropped_activity_absent(client, db, event):
    _activity(db, event, status="dropped")
    _activity(db, event, title="Rando 2")
    text = _ics(client, event)
    assert len(_events(text)) == 1
    assert "Rando 2" in text


def test_ics_activity_location_and_description(client, db, event):
    _activity(db, event, location="Forêt", description="Pique-nique\napporté")
    body = _events(_ics(client, event))[0]
    assert "LOCATION:Forêt" in body
    assert "DESCRIPTION:Pique-nique\\napporté" in body


def test_ics_activity_without_location_has_no_location_field(client, db, event):
    _activity(db, event)
    body = _events(_ics(client, event))[0]
    assert not re.search(r"^LOCATION:", body, re.M)


# --- Repas ----------------------------------------------------------------------


def _meal(db, event, title, slot, day=date(2026, 12, 3)):
    meal = Meal(event_id=event.id, title=title, date=day, slot=slot)
    db.session.add(meal)
    db.session.commit()
    return meal


def test_ics_meal_lunch_at_noon(client, db, event):
    _meal(db, event, "Barbecue", "lunch")
    body = _events(_ics(client, event))[0]
    assert "DTSTART:20261203T120000" in body
    assert "DTEND:20261203T130000" in body
    assert "SUMMARY:Midi — Barbecue" in body


def test_ics_meal_dinner_at_8pm(client, db, event):
    _meal(db, event, "Lasagnes", "dinner")
    body = _events(_ics(client, event))[0]
    assert "DTSTART:20261203T200000" in body
    assert "SUMMARY:Soir — Lasagnes" in body


# --- Échappement et stabilité ----------------------------------------------------


def test_ics_escapes_special_characters(client, db, event):
    _activity(db, event, title="Rando, avec ; point\net saut")
    body = _events(_ics(client, event))[0]
    assert "SUMMARY:Rando\\, avec \\; point\\net saut" in body


def test_ics_uids_are_stable_and_distinct(client, db, event):
    act = _activity(db, event)
    meal = _meal(db, event, "Barbecue", "lunch")
    first = _ics(client, event)
    second = _ics(client, event)
    assert f"UID:holishared-{event.code}-act-{act.id}" in first
    assert f"UID:holishared-{event.code}-meal-{meal.id}" in first
    assert first.count("UID:") == second.count("UID:") == 2
    # Même UID au second fetch (mise à jour, pas duplication).
    assert re.findall(r"^UID:(.*)$", first, re.M) == re.findall(r"^UID:(.*)$", second, re.M)


def test_ics_empty_event_has_no_vevent(client, event):
    text = _ics(client, event)
    assert "BEGIN:VCALENDAR" in text and "END:VCALENDAR" in text
    assert "BEGIN:VEVENT" not in text


# --- Bouton « Calendrier » -------------------------------------------------------


def test_home_calendar_button_copies_ics_url(creator_client, event, app):
    from tests.test_event_home import _home

    base = str(app.config["APP_URL"]).rstrip("/")
    html = _home(creator_client, event)
    match = re.search(r'<button[^>]*data-testid="calendar-action"[^>]*>', html)
    assert match is not None
    assert f'data-copy="{base}/e/{event.code}/calendar.ics"' in match.group(0)
