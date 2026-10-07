"""B025 — Sondage d'activités dans le Planning : « En vote », « Retenir », « Non retenue », accueil."""

from datetime import date, datetime, timedelta

import pytest
from tests.ui_helpers import block, tag

from app.models import (
    Activity,
    ActivityLog,
    Event,
    Guest,
    Poll,
    PollOption,
    PollVote,
    generate_event_code,
    generate_guest_code,
)

DAY = date(2026, 12, 3)


def _act(db, event, title, **kw):
    a = Activity(title=title, date=kw.pop("day", DAY), event_id=event.id, **kw)
    db.session.add(a)
    db.session.commit()
    return a


def _poll(db, event, acts, *, closed=False, votes=(), free=(), created_by=None):
    """Sondage d'activités ; ``votes`` : liste d'index d'options (un votant neuf par vote)."""
    p = Poll(
        question="Quelle activité ?",
        kind="activities",
        event_id=event.id,
        is_closed=closed,
        created_by=created_by,
    )
    db.session.add(p)
    db.session.flush()
    options = []
    for i, a in enumerate(acts):
        o = PollOption(label=a.title, order=i, poll_id=p.id, activity_id=a.id)
        db.session.add(o)
        options.append(o)
    for j, label in enumerate(free):
        o = PollOption(label=label, order=len(acts) + j, poll_id=p.id)
        db.session.add(o)
        options.append(o)
    db.session.flush()
    for index in votes:
        voter = Guest(code=generate_guest_code(), display_name="v", event_id=event.id)
        db.session.add(voter)
        db.session.flush()
        db.session.add(PollVote(option_id=options[index].id, guest_id=voter.id))
    db.session.commit()
    return p


def _page(client, event):
    return client.get(f"/e/{event.code}/planning").get_data(as_text=True)


def _card(html, act):
    start = html.index(f'data-activity-id="{act.id}"')
    return html[start : html.index("</li>", start)]


def _retain(client, event, act):
    return client.post(f"/e/{event.code}/planning/{act.id}/retain")


def _restore(client, event, act):
    return client.post(f"/e/{event.code}/planning/{act.id}/restore")


@pytest.fixture
def two(db, event):
    return _act(db, event, "Rando"), _act(db, event, "Piscine")


# --- Badge « En vote » ---


def test_open_activities_poll_marks_activities_en_vote(creator_client, db, event, two):
    _poll(db, event, two)
    assert 'data-testid="activity-badge-voting"' in _card(_page(creator_client, event), two[0])


def test_en_vote_badge_links_to_the_poll(creator_client, db, event, two):
    poll = _poll(db, event, two)
    badge = tag(_card(_page(creator_client, event), two[0]), "activity-badge-voting")
    assert f"/voting/{poll.id}" in badge


def test_closed_poll_has_no_en_vote_badge(creator_client, db, event, two):
    _poll(db, event, two, closed=True)
    assert 'data-testid="activity-badge-voting"' not in _page(creator_client, event)


def test_activity_outside_the_poll_has_no_en_vote_badge(creator_client, db, event, two):
    other = _act(db, event, "Cinéma")
    _poll(db, event, two)
    assert 'data-testid="activity-badge-voting"' not in _card(_page(creator_client, event), other)


def test_en_vote_badge_absent_when_voting_module_is_off(app_factory):
    application = app_factory({"ENABLED_MODULES": "planning"})
    from app.extensions import db as _db
    from app.models import Creator

    c = Creator(email="c@t.com", email_verified=True, display_name="C")
    _db.session.add(c)
    _db.session.commit()
    e = Event(
        code=generate_event_code(),
        title="E",
        start_date=DAY,
        end_date=DAY + timedelta(days=1),
        creator_id=c.id,
        verified_at=datetime.utcnow(),
    )
    _db.session.add(e)
    _db.session.commit()
    acts = [_act(_db, e, "A"), _act(_db, e, "B")]
    _poll(_db, e, acts)
    client = application.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = c.id
        s["_fresh"] = True
    assert 'data-testid="activity-badge-voting"' not in _page(client, e)


# --- « Retenir » ---


def test_creator_sees_retain_on_the_winning_activity(creator_client, db, event, two):
    _poll(db, event, two, closed=True, votes=[0, 0, 1])
    assert 'data-testid="activity-retain"' in _card(_page(creator_client, event), two[0])


def test_creator_does_not_see_retain_on_the_losing_activity(creator_client, db, event, two):
    _poll(db, event, two, closed=True, votes=[0, 0, 1])
    assert 'data-testid="activity-retain"' not in _card(_page(creator_client, event), two[1])


def test_retain_on_tie_is_offered_on_both_winners(creator_client, db, event, two):
    _poll(db, event, two, closed=True, votes=[0, 1])
    html = _page(creator_client, event)
    assert [("activity-retain" in tag_) for tag_ in (_card(html, two[0]), _card(html, two[1]))] == [
        True,
        True,
    ]


def test_guest_does_not_see_retain(guest_client, db, event, two):
    _poll(db, event, two, closed=True, votes=[0])
    assert 'data-testid="activity-retain"' not in _page(guest_client, event)


def test_open_poll_offers_no_retain(creator_client, db, event, two):
    _poll(db, event, two, votes=[0, 0])
    assert 'data-testid="activity-retain"' not in _page(creator_client, event)


def test_retain_marks_winner_retained(creator_client, db, event, two):
    _poll(db, event, two, closed=True, votes=[0, 0, 1])
    _retain(creator_client, event, two[0])
    db.session.refresh(two[0])
    assert two[0].status == "retained"


def test_retain_marks_other_linked_options_dropped(creator_client, db, event, two):
    _poll(db, event, two, closed=True, votes=[0, 0, 1])
    _retain(creator_client, event, two[0])
    db.session.refresh(two[1])
    assert two[1].status == "dropped"


def test_retain_leaves_other_winner_of_a_tie_planned(creator_client, db, event, two):
    _poll(db, event, two, closed=True, votes=[0, 1])
    _retain(creator_client, event, two[0])
    db.session.refresh(two[1])
    assert two[1].status == "planned"


def test_retain_ignores_free_options_and_unlinked_activities(creator_client, db, event, two):
    bystander = _act(db, event, "Cinéma")
    _poll(db, event, two, closed=True, votes=[0], free=["Rien"])
    _retain(creator_client, event, two[0])
    db.session.refresh(bystander)
    assert bystander.status == "planned"


def test_retain_by_guest_returns_403(guest_client, db, event, two):
    _poll(db, event, two, closed=True, votes=[0])
    assert _retain(guest_client, event, two[0]).status_code == 403


def test_retain_on_losing_activity_changes_nothing(creator_client, db, event, two):
    _poll(db, event, two, closed=True, votes=[0, 0, 1])
    _retain(creator_client, event, two[1])
    db.session.refresh(two[1])
    assert two[1].status == "planned"


def test_retain_with_open_poll_changes_nothing(creator_client, db, event, two):
    _poll(db, event, two, votes=[0])
    _retain(creator_client, event, two[0])
    db.session.refresh(two[0])
    assert two[0].status == "planned"


def test_retain_activity_of_another_event_returns_404(creator_client, db, event, creator, two):
    other = Event(
        code=generate_event_code(),
        title="Autre",
        start_date=DAY,
        end_date=DAY,
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(other)
    db.session.commit()
    foreign = _act(db, other, "Ailleurs")
    assert _retain(creator_client, event, foreign).status_code == 404


def test_retain_logs_retained_and_dropped(creator_client, db, event, two):
    _poll(db, event, two, closed=True, votes=[0])
    _retain(creator_client, event, two[0])
    actions = sorted(
        entry.action for entry in ActivityLog.query.filter(ActivityLog.action.like("activity.%"))
    )
    assert actions == ["activity.dropped", "activity.retained"]


def test_retained_activity_shows_retained_badge(creator_client, db, event, two):
    _poll(db, event, two, closed=True, votes=[0])
    _retain(creator_client, event, two[0])
    assert 'data-testid="activity-badge-retained"' in _card(_page(creator_client, event), two[0])


def test_retained_activity_no_longer_offers_retain(creator_client, db, event, two):
    _poll(db, event, two, closed=True, votes=[0])
    _retain(creator_client, event, two[0])
    assert 'data-testid="activity-retain"' not in _card(_page(creator_client, event), two[0])


# --- « Non retenue » : grisée, restaurable, hors programme ---


@pytest.fixture
def dropped(creator_client, db, event, two):
    _poll(db, event, two, closed=True, votes=[0])
    _retain(creator_client, event, two[0])
    db.session.refresh(two[1])
    return two[1]


def test_dropped_activity_is_not_in_the_day_program(creator_client, event, dropped):
    html = _page(creator_client, event)
    assert dropped.title not in block(html, "day-activities", "ul")


def test_dropped_activity_is_listed_in_the_dropped_section(creator_client, event, dropped):
    html = _page(creator_client, event)
    assert 'data-status="dropped"' in block(html, "day-dropped", "details")


def test_dropped_card_shows_non_retenue_badge(creator_client, event, dropped):
    assert 'data-testid="activity-badge-dropped"' in _card(_page(creator_client, event), dropped)


def test_dropped_card_has_no_rsvp_form(creator_client, event, dropped):
    assert 'data-testid="rsvp-form"' not in _card(_page(creator_client, event), dropped)


def test_dropped_activity_does_not_count_in_threshold_alerts(creator_client, db, event, two):
    two[1].min_headcount = 5
    db.session.commit()
    _poll(db, event, two, closed=True, votes=[0])
    _retain(creator_client, event, two[0])
    assert 'data-testid="threshold"' not in _card(_page(creator_client, event), two[1])


def test_creator_can_restore_a_dropped_activity(creator_client, db, event, dropped):
    _restore(creator_client, event, dropped)
    db.session.refresh(dropped)
    assert dropped.status == "planned"


def test_restore_logs_activity_restored(creator_client, db, event, dropped):
    _restore(creator_client, event, dropped)
    assert ActivityLog.query.filter_by(action="activity.restored").count() == 1


def test_author_can_restore_own_dropped_activity(guest_client, db, event, guest, two):
    two[1].created_by = guest.id
    db.session.commit()
    _poll(db, event, two, closed=True, votes=[0])
    two[1].status = "dropped"
    db.session.commit()
    _restore(guest_client, event, two[1])
    db.session.refresh(two[1])
    assert two[1].status == "planned"


def test_other_guest_cannot_restore(guest_client, db, event, two):
    two[1].status = "dropped"
    db.session.commit()
    assert _restore(guest_client, event, two[1]).status_code == 403


def test_restored_activity_returns_to_the_day_program(creator_client, db, event, dropped):
    _restore(creator_client, event, dropped)
    assert dropped.title in block(_page(creator_client, event), "day-activities", "ul")


def test_dropped_activity_can_be_deleted(creator_client, db, event, dropped):
    creator_client.post(f"/e/{event.code}/planning/{dropped.id}/delete")
    assert Activity.query.filter_by(title=dropped.title).count() == 0


def test_deleting_activity_keeps_poll_option_with_its_label(creator_client, db, event, two):
    _poll(db, event, two)
    creator_client.post(f"/e/{event.code}/planning/{two[0].id}/delete")
    option = PollOption.query.filter_by(label="Rando").one()
    assert option.activity_id is None


def test_poll_page_renders_after_linked_activity_deleted(creator_client, db, event, two):
    poll = _poll(db, event, two)
    creator_client.post(f"/e/{event.code}/planning/{two[0].id}/delete")
    assert creator_client.get(f"/e/{event.code}/voting/{poll.id}").status_code == 200


def test_dashboard_today_excludes_dropped_activities(creator_client, db, event):
    today = date.today()
    event.start_date, event.end_date = today, today + timedelta(days=2)
    _act(db, event, "Gardée", day=today)
    b = _act(db, event, "Écartée", day=today)
    b.status = "dropped"
    db.session.commit()
    html = creator_client.get(f"/e/{event.code}").get_data(as_text=True)
    assert ("Gardée" in html, "Écartée" in html) == (True, False)


def test_lists_panel_excludes_dropped_activities(creator_client, db, event, dropped):
    from app.models import SharedList

    lst = SharedList(title="Courses", list_type="shopping", event_id=event.id)
    db.session.add(lst)
    db.session.commit()
    html = creator_client.get(f"/e/{event.code}/lists/{lst.id}/panel").get_data(as_text=True)
    assert dropped.title not in html


# --- Accueil : « À voter » ---


def _home(client, event):
    return client.get(f"/e/{event.code}").get_data(as_text=True)


def test_home_lists_open_poll_with_to_vote_mention(guest_client, db, event, two):
    _poll(db, event, two)
    assert 'data-testid="home-poll-to-vote"' in block(
        _home(guest_client, event), "polls", "section"
    )


def test_home_links_to_the_poll(guest_client, db, event, two):
    poll = _poll(db, event, two)
    assert f"/voting/{poll.id}" in block(_home(guest_client, event), "polls", "section")


def test_home_has_no_to_vote_mention_after_voting(guest_client, db, event, guest, two):
    poll = _poll(db, event, two)
    db.session.add(PollVote(option_id=poll.options.first().id, guest_id=guest.id))
    db.session.commit()
    assert 'data-testid="home-poll-to-vote"' not in _home(guest_client, event)


def test_home_puts_unvoted_polls_first(guest_client, db, event, guest, two):
    old = _poll(db, event, two)
    db.session.add(PollVote(option_id=old.options.first().id, guest_id=guest.id))
    old.created_at = datetime.utcnow() + timedelta(days=1)  # le plus récent, mais déjà voté
    new = _poll(db, event, two)
    new.question = "Pas encore voté ?"
    db.session.commit()
    html = block(_home(guest_client, event), "polls", "section")
    assert html.index("Pas encore voté ?") < html.index("Quelle activité ?")


def test_home_excludes_closed_polls(guest_client, db, event, two):
    _poll(db, event, two, closed=True)
    assert 'data-testid="home-poll"' not in _home(guest_client, event)
