"""B025 — Sondages : création (libre / activités), vote en un geste, résultats après vote, clôture, droits."""

import re
from datetime import date

from tests.ui_helpers import tag

from app.models import Activity, ActivityLog, Guest, Poll, PollOption, PollVote, generate_guest_code

HX = {"HX-Request": "true"}


def _opts(poll):
    return poll.options.order_by(PollOption.order.asc()).all()


def _poll(
    db, event, question="Où manger ?", labels=("Pizza", "Sushi"), kind="free", created_by=None
):
    p = Poll(question=question, kind=kind, event_id=event.id, created_by=created_by)
    db.session.add(p)
    db.session.flush()
    for i, label in enumerate(labels):
        db.session.add(PollOption(label=label, order=i, poll_id=p.id))
    db.session.commit()
    return p


def _act(db, event, title="Rando", day=date(2026, 12, 3)):
    a = Activity(title=title, date=day, event_id=event.id)
    db.session.add(a)
    db.session.commit()
    return a


def _guest(db, event, name="Autre"):
    g = Guest(code=generate_guest_code(), display_name=name, event_id=event.id)
    db.session.add(g)
    db.session.commit()
    return g


def _as_guest(client, event, guest):
    with client.session_transaction() as s:
        s[f"guest_{event.code}"] = guest.id


def _new(client, event, **data):
    return client.post(f"/e/{event.code}/voting/new", data=data)


def _vote(client, event, poll, option, headers=None):
    return client.post(
        f"/e/{event.code}/voting/{poll.id}/vote",
        data={"option_id": option.id},
        headers=headers or {},
    )


# --- Création : question libre ---


def test_create_free_poll_with_ten_options_succeeds(creator_client, event):
    options = "\n".join(f"Option {i}" for i in range(10))
    _new(creator_client, event, question="Choix ?", kind="free", options=options)
    assert Poll.query.one().options.count() == 10


def test_create_free_poll_stores_kind_free(creator_client, event):
    _new(creator_client, event, question="Choix ?", kind="free", options="A\nB")
    assert Poll.query.one().kind == "free"


def test_create_poll_without_kind_defaults_to_free(creator_client, event):
    _new(creator_client, event, question="Choix ?", options="A\nB")
    assert Poll.query.one().kind == "free"


def test_create_poll_stores_author(creator_client, event, creator_guest):
    _new(creator_client, event, question="Choix ?", options="A\nB")
    assert Poll.query.one().created_by == creator_guest.id


def test_create_poll_redirects_to_detail(creator_client, event):
    resp = _new(creator_client, event, question="Choix ?", options="A\nB")
    poll = Poll.query.one()
    assert resp.headers["Location"].endswith(f"/e/{event.code}/voting/{poll.id}")


def test_create_poll_with_one_option_shows_options_error_field(creator_client, event):
    html = _new(creator_client, event, question="Choix ?", options="A").get_data(as_text=True)
    assert 'data-testid="err-options"' in html


def test_create_poll_with_short_question_shows_question_error_field(creator_client, event):
    html = _new(creator_client, event, question="x", options="A\nB").get_data(as_text=True)
    assert 'data-testid="err-question"' in html


def test_create_poll_with_eleven_options_creates_nothing(creator_client, event):
    options = "\n".join(f"O{i}" for i in range(11))
    _new(creator_client, event, question="Choix ?", options=options)
    assert Poll.query.count() == 0


def test_create_poll_with_unknown_kind_shows_kind_error_field(creator_client, event):
    html = _new(creator_client, event, question="Q ?", kind="bogus", options="A\nB").get_data(
        as_text=True
    )
    assert 'data-testid="err-kind"' in html


def test_create_poll_error_keeps_typed_question(creator_client, event):
    html = _new(creator_client, event, question="Ma question", options="A").get_data(as_text=True)
    assert 'value="Ma question"' in html


def test_guest_can_create_poll(guest_client, event, guest):
    _new(guest_client, event, question="Choix ?", options="A\nB")
    assert Poll.query.one().created_by == guest.id


# --- Création : départage d'activités ---


def test_create_activities_poll_links_options_to_activities(creator_client, db, event):
    a1, a2 = _act(db, event, "Rando"), _act(db, event, "Piscine")
    _new(creator_client, event, question="Quelle ?", kind="activities", activity_ids=[a1.id, a2.id])
    poll = Poll.query.one()
    assert [o.activity_id for o in _opts(poll)] == [a1.id, a2.id]


def test_create_activities_poll_label_contains_title(creator_client, db, event):
    a1, a2 = _act(db, event, "Rando"), _act(db, event, "Piscine")
    _new(creator_client, event, question="Quelle ?", kind="activities", activity_ids=[a1.id, a2.id])
    assert _opts(Poll.query.one())[0].label.startswith("Rando")


def test_create_activities_poll_stores_kind_activities(creator_client, db, event):
    a1, a2 = _act(db, event, "Rando"), _act(db, event, "Piscine")
    _new(creator_client, event, question="Quelle ?", kind="activities", activity_ids=[a1.id, a2.id])
    assert Poll.query.one().kind == "activities"


def test_create_activities_poll_appends_free_options_without_activity(creator_client, db, event):
    a1, a2 = _act(db, event, "Rando"), _act(db, event, "Piscine")
    _new(
        creator_client,
        event,
        question="Q ?",
        kind="activities",
        activity_ids=[a1.id, a2.id],
        options="Rien",
    )
    assert [o.activity_id for o in _opts(Poll.query.one())] == [a1.id, a2.id, None]


def test_create_activities_poll_with_one_activity_shows_activity_error_field(
    creator_client, db, event
):
    a1, _a2 = _act(db, event, "A"), _act(db, event, "B")
    html = _new(
        creator_client, event, question="Q ?", kind="activities", activity_ids=[a1.id]
    ).get_data(as_text=True)
    assert 'data-testid="err-activity_ids"' in html


def test_create_activities_poll_with_one_activity_creates_nothing(creator_client, db, event):
    a1 = _act(db, event)
    _new(
        creator_client,
        event,
        question="Q ?",
        kind="activities",
        activity_ids=[a1.id],
        options="Autre",
    )
    assert Poll.query.count() == 0


def test_create_activities_poll_with_foreign_event_activity_is_refused(
    creator_client, db, event, creator
):
    from app.models import Event, generate_event_code

    other = Event(
        code=generate_event_code(),
        title="Autre",
        start_date=event.start_date,
        end_date=event.end_date,
        creator_id=creator.id,
        verified_at=event.verified_at,
    )
    db.session.add(other)
    db.session.commit()
    mine, foreign = _act(db, event, "A"), _act(db, other, "B")
    _new(
        creator_client, event, question="Q ?", kind="activities", activity_ids=[mine.id, foreign.id]
    )
    assert Poll.query.count() == 0


def test_create_activities_poll_with_dropped_activity_is_refused(creator_client, db, event):
    a1, a2 = _act(db, event, "A"), _act(db, event, "B")
    a2.status = "dropped"
    db.session.commit()
    _new(creator_client, event, question="Q ?", kind="activities", activity_ids=[a1.id, a2.id])
    assert Poll.query.count() == 0


def test_create_activities_poll_over_ten_options_is_refused(creator_client, db, event):
    acts = [_act(db, event, f"A{i}") for i in range(3)]
    options = "\n".join(f"O{i}" for i in range(8))
    _new(
        creator_client,
        event,
        question="Q ?",
        kind="activities",
        activity_ids=[a.id for a in acts],
        options=options,
    )
    assert Poll.query.count() == 0


def test_create_activities_poll_with_planning_disabled_is_refused(app_factory, db):
    # Planning inactif : app dédiée sans le module.
    application = app_factory({"ENABLED_MODULES": "voting"})
    from app.extensions import db as _db
    from app.models import Creator, Event, generate_event_code

    c = Creator(email="c@t.com", email_verified=True, display_name="C")
    _db.session.add(c)
    _db.session.commit()
    e = Event(
        code=generate_event_code(),
        title="E",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 2),
        creator_id=c.id,
        verified_at=date(2026, 1, 1),
    )
    _db.session.add(e)
    _db.session.commit()
    client = application.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = c.id
        s["_fresh"] = True
    html = client.post(
        f"/e/{e.code}/voting/new", data={"question": "Q ?", "kind": "activities"}
    ).get_data(as_text=True)
    assert 'data-testid="err-kind"' in html


def test_form_disables_activities_kind_when_fewer_than_two_activities(creator_client, db, event):
    _act(db, event)
    html = creator_client.get(f"/e/{event.code}/voting/new").get_data(as_text=True)
    assert "disabled" in tag(html, "poll-kind-activities")


def test_form_enables_activities_kind_with_two_activities(creator_client, db, event):
    _act(db, event, "A")
    _act(db, event, "B")
    html = creator_client.get(f"/e/{event.code}/voting/new").get_data(as_text=True)
    assert "disabled" not in tag(html, "poll-kind-activities")


def test_form_lists_event_activities_as_checkboxes(creator_client, db, event):
    _act(db, event, "A")
    _act(db, event, "B")
    html = creator_client.get(f"/e/{event.code}/voting/new").get_data(as_text=True)
    assert html.count('data-testid="poll-activity-option"') == 2


# --- Vote en un geste ---


def test_vote_creates_vote_for_guest(guest_client, db, event, guest):
    poll = _poll(db, event)
    _vote(guest_client, event, poll, _opts(poll)[0])
    assert PollVote.query.filter_by(guest_id=guest.id).count() == 1


def test_vote_change_replaces_previous_vote(guest_client, db, event, guest):
    poll = _poll(db, event)
    _vote(guest_client, event, poll, _opts(poll)[0])
    _vote(guest_client, event, poll, _opts(poll)[1])
    assert [v.option_id for v in PollVote.query.all()] == [_opts(poll)[1].id]


def test_vote_same_option_twice_keeps_one_vote(guest_client, db, event):
    poll = _poll(db, event)
    _vote(guest_client, event, poll, _opts(poll)[0])
    _vote(guest_client, event, poll, _opts(poll)[0])
    assert PollVote.query.count() == 1


def test_vote_same_option_twice_logs_once(guest_client, db, event):
    poll = _poll(db, event)
    _vote(guest_client, event, poll, _opts(poll)[0])
    _vote(guest_client, event, poll, _opts(poll)[0])
    assert ActivityLog.query.filter_by(action="poll.voted").count() == 1


def test_vote_on_closed_poll_records_nothing(guest_client, db, event):
    poll = _poll(db, event)
    poll.is_closed = True
    db.session.commit()
    _vote(guest_client, event, poll, _opts(poll)[0])
    assert PollVote.query.count() == 0


def test_vote_on_closed_poll_htmx_returns_fragment_with_toast(guest_client, db, event):
    poll = _poll(db, event)
    poll.is_closed = True
    db.session.commit()
    resp = _vote(guest_client, event, poll, _opts(poll)[0], HX)
    assert "ui:toast" in resp.headers["HX-Trigger"]


def test_vote_by_creator_is_recorded_on_creator_participant(
    creator_client, db, event, creator_guest
):
    poll = _poll(db, event)
    _vote(creator_client, event, poll, _opts(poll)[0])
    assert PollVote.query.one().guest_id == creator_guest.id


def test_vote_htmx_returns_card_fragment_without_layout(guest_client, db, event):
    poll = _poll(db, event)
    html = _vote(guest_client, event, poll, _opts(poll)[0], HX).get_data(as_text=True)
    assert html.lstrip().startswith("<article")
    assert "<html" not in html


def test_vote_without_htmx_redirects_to_index(guest_client, db, event):
    poll = _poll(db, event)
    resp = _vote(guest_client, event, poll, _opts(poll)[0])
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/voting")


def test_vote_detail_flag_redirects_to_detail(guest_client, db, event):
    poll = _poll(db, event)
    resp = guest_client.post(
        f"/e/{event.code}/voting/{poll.id}/vote",
        data={"option_id": _opts(poll)[0].id, "detail": "1"},
    )
    assert resp.headers["Location"].endswith(f"/voting/{poll.id}")


def test_vote_with_option_of_another_poll_returns_404(guest_client, db, event):
    p1, p2 = _poll(db, event, "Q1 ?"), _poll(db, event, "Q2 ?")
    assert _vote(guest_client, event, p1, _opts(p2)[0]).status_code == 404


def test_vote_idor_other_event_returns_404(guest_client, db, event, creator):
    from app.models import Event, generate_event_code

    other = Event(
        code=generate_event_code(),
        title="Autre",
        start_date=event.start_date,
        end_date=event.end_date,
        creator_id=creator.id,
        verified_at=event.verified_at,
    )
    db.session.add(other)
    db.session.commit()
    foreign = _poll(db, other)
    assert (
        guest_client.post(
            f"/e/{event.code}/voting/{foreign.id}/vote", data={"option_id": _opts(foreign)[0].id}
        ).status_code
        == 404
    )


# --- Résultats : masqués avant le vote ---


def test_results_hidden_before_vote_on_detail(guest_client, db, event):
    poll = _poll(db, event)
    html = guest_client.get(f"/e/{event.code}/voting/{poll.id}").get_data(as_text=True)
    assert 'data-testid="poll-option-result"' not in html


def test_results_hidden_before_vote_on_index(guest_client, db, event):
    _poll(db, event)
    html = guest_client.get(f"/e/{event.code}/voting").get_data(as_text=True)
    assert 'data-testid="poll-option-result"' not in html


def test_voters_count_visible_before_vote(guest_client, db, event):
    poll = _poll(db, event)
    other = _guest(db, event)
    db.session.add(PollVote(option_id=_opts(poll)[0].id, guest_id=other.id))
    db.session.commit()
    html = guest_client.get(f"/e/{event.code}/voting/{poll.id}").get_data(as_text=True)
    assert "1 votant" in html


def test_results_visible_after_vote(guest_client, db, event):
    poll = _poll(db, event)
    _vote(guest_client, event, poll, _opts(poll)[0])
    html = guest_client.get(f"/e/{event.code}/voting/{poll.id}").get_data(as_text=True)
    assert html.count('data-testid="poll-option-result"') == 2


def test_results_visible_to_non_voter_once_closed(guest_client, db, event):
    poll = _poll(db, event)
    poll.is_closed = True
    db.session.commit()
    html = guest_client.get(f"/e/{event.code}/voting/{poll.id}").get_data(as_text=True)
    assert html.count('data-testid="poll-option-result"') == 2


def test_vote_htmx_fragment_shows_results(guest_client, db, event):
    poll = _poll(db, event)
    html = _vote(guest_client, event, poll, _opts(poll)[0], HX).get_data(as_text=True)
    assert html.count('data-testid="poll-option-result"') == 2


def test_percentages_are_computed_over_all_votes(guest_client, db, event):
    poll = _poll(db, event, labels=("A", "B", "C"))
    for opt in (_opts(poll)[0], _opts(poll)[0], _opts(poll)[1]):
        db.session.add(PollVote(option_id=opt.id, guest_id=_guest(db, event, "x").id))
    db.session.commit()
    _vote(guest_client, event, poll, _opts(poll)[2])
    html = guest_client.get(f"/e/{event.code}/voting/{poll.id}").get_data(as_text=True)
    assert re.findall(r'data-count="(\d)">([^<]*?) ·', html) == [
        ("2", "50\u00a0%"),
        ("1", "25\u00a0%"),
        ("1", "25\u00a0%"),
    ]


# --- Gagnants et égalités ---


def _cast(db, event, poll, option):
    db.session.add(PollVote(option_id=option.id, guest_id=_guest(db, event, "v").id))
    db.session.commit()


def test_closed_poll_marks_single_winner(guest_client, db, event):
    poll = _poll(db, event)
    _cast(db, event, poll, _opts(poll)[0])
    poll.is_closed = True
    db.session.commit()
    html = guest_client.get(f"/e/{event.code}/voting/{poll.id}").get_data(as_text=True)
    assert html.count('data-testid="poll-winner"') == 1


def test_closed_poll_tie_marks_every_top_option(guest_client, db, event):
    poll = _poll(db, event)
    _cast(db, event, poll, _opts(poll)[0])
    _cast(db, event, poll, _opts(poll)[1])
    poll.is_closed = True
    db.session.commit()
    html = guest_client.get(f"/e/{event.code}/voting/{poll.id}").get_data(as_text=True)
    assert html.count('data-testid="poll-winner"') == 2
    assert 'data-testid="poll-tie"' in html


def test_closed_poll_without_votes_has_no_winner(guest_client, db, event):
    poll = _poll(db, event)
    poll.is_closed = True
    db.session.commit()
    html = guest_client.get(f"/e/{event.code}/voting/{poll.id}").get_data(as_text=True)
    assert 'data-testid="poll-winner"' not in html


def test_open_poll_shows_no_winner(guest_client, db, event):
    poll = _poll(db, event)
    _vote(guest_client, event, poll, _opts(poll)[0])
    html = guest_client.get(f"/e/{event.code}/voting/{poll.id}").get_data(as_text=True)
    assert 'data-testid="poll-winner"' not in html


# --- Clore, rouvrir, supprimer : droits ---


def _post(client, event, poll, action):
    return client.post(f"/e/{event.code}/voting/{poll.id}/{action}")


def test_close_by_creator_closes_poll(creator_client, db, event):
    poll = _poll(db, event)
    _post(creator_client, event, poll, "close")
    db.session.refresh(poll)
    assert poll.is_closed is True


def test_close_by_poll_author_closes_poll(guest_client, db, event, guest):
    poll = _poll(db, event, created_by=guest.id)
    _post(guest_client, event, poll, "close")
    db.session.refresh(poll)
    assert poll.is_closed is True


def test_close_by_other_guest_returns_403(guest_client, db, event):
    poll = _poll(db, event, created_by=_guest(db, event).id)
    assert _post(guest_client, event, poll, "close").status_code == 403


def test_close_idor_other_event_returns_404(creator_client, db, event, creator):
    from app.models import Event, generate_event_code

    other = Event(
        code=generate_event_code(),
        title="Autre",
        start_date=event.start_date,
        end_date=event.end_date,
        creator_id=creator.id,
        verified_at=event.verified_at,
    )
    db.session.add(other)
    db.session.commit()
    foreign = _poll(db, other)
    assert _post(creator_client, event, foreign, "close").status_code == 404


def test_reopen_by_creator_reopens_poll_and_logs(creator_client, db, event):
    poll = _poll(db, event)
    poll.is_closed = True
    db.session.commit()
    _post(creator_client, event, poll, "reopen")
    db.session.refresh(poll)
    assert (poll.is_closed, ActivityLog.query.filter_by(action="poll.reopened").count()) == (
        False,
        1,
    )


def test_reopen_by_poll_author_returns_403(guest_client, db, event, guest):
    poll = _poll(db, event, created_by=guest.id)
    poll.is_closed = True
    db.session.commit()
    assert _post(guest_client, event, poll, "reopen").status_code == 403


def test_delete_by_creator_removes_poll_and_votes(creator_client, db, event):
    poll = _poll(db, event)
    _cast(db, event, poll, _opts(poll)[0])
    _post(creator_client, event, poll, "delete")
    assert (Poll.query.count(), PollVote.query.count()) == (0, 0)


def test_delete_by_poll_author_removes_poll(guest_client, db, event, guest):
    poll = _poll(db, event, created_by=guest.id)
    _post(guest_client, event, poll, "delete")
    assert Poll.query.count() == 0


def test_delete_by_other_guest_returns_403(guest_client, db, event):
    poll = _poll(db, event, created_by=_guest(db, event).id)
    assert _post(guest_client, event, poll, "delete").status_code == 403


def test_delete_logs_poll_deleted(creator_client, db, event):
    poll = _poll(db, event)
    _post(creator_client, event, poll, "delete")
    assert ActivityLog.query.filter_by(action="poll.deleted").one().target == "Où manger ?"


def test_close_logs_poll_closed(creator_client, db, event):
    poll = _poll(db, event)
    _post(creator_client, event, poll, "close")
    assert ActivityLog.query.filter_by(action="poll.closed").count() == 1


def test_detail_shows_close_button_to_creator(creator_client, db, event):
    poll = _poll(db, event)
    html = creator_client.get(f"/e/{event.code}/voting/{poll.id}").get_data(as_text=True)
    assert 'data-testid="poll-close"' in html


def test_detail_close_form_asks_confirmation(creator_client, db, event):
    poll = _poll(db, event)
    html = creator_client.get(f"/e/{event.code}/voting/{poll.id}").get_data(as_text=True)
    assert "data-confirm=" in tag(html, "poll-close-form")


def test_detail_hides_manage_buttons_from_other_guest(guest_client, db, event):
    poll = _poll(db, event)
    html = guest_client.get(f"/e/{event.code}/voting/{poll.id}").get_data(as_text=True)
    assert 'data-testid="poll-manage"' not in html


def test_detail_shows_reopen_only_for_closed_poll_and_creator(creator_client, db, event):
    poll = _poll(db, event)
    poll.is_closed = True
    db.session.commit()
    html = creator_client.get(f"/e/{event.code}/voting/{poll.id}").get_data(as_text=True)
    assert 'data-testid="poll-reopen"' in html
    assert 'data-testid="poll-close"' not in html


# --- Rendu de la page ---


def test_index_lists_open_polls_before_closed(guest_client, db, event):
    closed = _poll(db, event, "Fini ?")
    closed.is_closed = True
    _poll(db, event, "Ouvert ?")
    db.session.commit()
    html = guest_client.get(f"/e/{event.code}/voting").get_data(as_text=True)
    assert html.index("Ouvert ?") < html.index("Fini ?")


def test_index_empty_state_without_polls(guest_client, event):
    html = guest_client.get(f"/e/{event.code}/voting").get_data(as_text=True)
    assert 'class="ui-empty"' in html


def test_index_single_primary_add_button_opens_sheet(guest_client, event):
    html = guest_client.get(f"/e/{event.code}/voting").get_data(as_text=True)
    assert "data-poll-add" in tag(html, "poll-add")
    assert 'data-testid="poll-sheet"' in html


def test_index_card_marks_unvoted_open_poll_to_vote(guest_client, db, event):
    _poll(db, event)
    html = guest_client.get(f"/e/{event.code}/voting").get_data(as_text=True)
    assert 'data-testid="poll-badge-to-vote"' in html


def test_index_card_has_no_to_vote_badge_after_vote(guest_client, db, event):
    poll = _poll(db, event)
    _vote(guest_client, event, poll, _opts(poll)[0])
    html = guest_client.get(f"/e/{event.code}/voting").get_data(as_text=True)
    assert 'data-testid="poll-badge-to-vote"' not in html


def test_vote_button_marks_chosen_option_pressed(guest_client, db, event):
    poll = _poll(db, event)
    option = _opts(poll)[0]
    html = _vote(guest_client, event, poll, option, HX).get_data(as_text=True)
    assert re.search(
        rf'aria-pressed="true"\s+data-testid="poll-option" data-option-id="{option.id}"', html
    )
