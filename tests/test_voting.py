"""Tests for voting blueprint — B006.

19 tests, déterministes, un comportement = un test.
Ces tests DOIVENT échouer avant le codage (TDD).
"""

import pytest

from app.models import ActivityLog, Guest, Poll, PollOption, PollVote

# === Fixtures locales (complètent conftest.py) ===


@pytest.fixture
def poll(db, event):
    """Un sondage ouvert avec 2 options."""
    p = Poll(question="Où mangeons-nous ?", event_id=event.id)
    db.session.add(p)
    db.session.flush()
    db.session.add_all(
        [
            PollOption(label="Pizza", order=0, poll_id=p.id),
            PollOption(label="Sushi", order=1, poll_id=p.id),
        ]
    )
    db.session.commit()
    return p


def _login_creator(client, creator):
    """Helper : simule le login du créateur."""
    with client.session_transaction() as sess:
        sess["_user_id"] = creator.id
        sess["_fresh"] = True


def _login_guest(client, event, guest):
    """Helper : simule la session d'un guest."""
    with client.session_transaction() as sess:
        sess[f"guest_{event.code}"] = guest.id


def _options(poll):
    return poll.options.order_by(PollOption.order.asc()).all()


# === TestVotingIndex (5 tests) ===


class TestVotingIndex:
    def test_index_renders_for_creator(self, client, creator, event, poll):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/voting")
        assert resp.status_code == 200
        assert b"mangeons-nous" in resp.data
        assert b"Pizza" in resp.data

    def test_index_renders_for_guest(self, client, event, guest, poll):
        _login_guest(client, event, guest)
        resp = client.get(f"/e/{event.code}/voting")
        assert resp.status_code == 200
        assert b"mangeons-nous" in resp.data
        assert b"Pizza" in resp.data

    def test_index_404_invalid_code(self, client, creator):
        _login_creator(client, creator)
        resp = client.get("/e/xxxxxx/voting")
        assert resp.status_code == 404

    def test_index_redirects_no_access(self, client, event):
        resp = client.get(f"/e/{event.code}/voting")
        assert resp.status_code == 302
        assert "/mycode" in resp.headers["Location"]

    def test_index_shows_results(self, client, creator, event, poll, guest, db):
        options = _options(poll)
        db.session.add(PollVote(option_id=options[0].id, guest_id=guest.id))
        db.session.commit()
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/voting")
        assert b"Pizza" in resp.data
        assert b"100%" in resp.data
        assert b"Sushi" in resp.data
        assert b"0%" in resp.data


# === TestCreatePoll (5 tests) ===


class TestCreatePoll:
    def test_create_poll_success(self, client, creator, event, db):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/voting/new",
            data={"question": "Quel film ?", "options": "Inception\nInterstellar\nGravity"},
        )
        assert resp.status_code == 302
        p = Poll.query.filter_by(question="Quel film ?").first()
        assert p is not None
        assert p.event_id == event.id
        assert p.is_closed is False
        options = _options(p)
        assert [o.label for o in options] == ["Inception", "Interstellar", "Gravity"]
        assert [o.order for o in options] == [0, 1, 2]

    def test_create_poll_missing_question(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/voting/new",
            data={"question": "", "options": "A\nB"},
        )
        assert resp.status_code == 200
        assert b"Question requise" in resp.data
        assert Poll.query.count() == 0

    def test_create_poll_too_few_options(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(
            f"/e/{event.code}/voting/new",
            data={"question": "Test ?", "options": "Only one"},
        )
        assert resp.status_code == 200
        assert b"2 options" in resp.data
        assert Poll.query.count() == 0

    def test_create_poll_too_many_options(self, client, creator, event):
        _login_creator(client, creator)
        options = "\n".join(f"Option {i}" for i in range(11))
        resp = client.post(
            f"/e/{event.code}/voting/new",
            data={"question": "Test ?", "options": options},
        )
        assert resp.status_code == 200
        assert b"10 options" in resp.data
        assert Poll.query.count() == 0

    def test_create_poll_logs(self, client, creator, event, db):
        _login_creator(client, creator)
        client.post(
            f"/e/{event.code}/voting/new",
            data={"question": "Logged poll ?", "options": "A\nB"},
        )
        log = ActivityLog.query.filter_by(event_id=event.id, action="poll.created").first()
        assert log is not None
        assert log.target == "Logged poll ?"
        assert log.actor_type == "creator"


# === TestVote (6 tests) ===


class TestVote:
    def test_vote_success(self, client, event, guest, poll, db):
        _login_guest(client, event, guest)
        option = _options(poll)[0]
        resp = client.post(f"/e/{event.code}/voting/{poll.id}/vote", data={"option_id": option.id})
        assert resp.status_code == 302
        vote = PollVote.query.filter_by(guest_id=guest.id, option_id=option.id).first()
        assert vote is not None

    def test_vote_changes_existing(self, client, event, guest, poll, db):
        _login_guest(client, event, guest)
        options = _options(poll)
        client.post(f"/e/{event.code}/voting/{poll.id}/vote", data={"option_id": options[0].id})
        client.post(f"/e/{event.code}/voting/{poll.id}/vote", data={"option_id": options[1].id})
        votes = PollVote.query.filter_by(guest_id=guest.id).all()
        assert len(votes) == 1
        assert votes[0].option_id == options[1].id

    def test_vote_success_for_creator(self, client, creator, event, poll, db):
        """The creator is a participant in their own event: they can vote."""
        _login_creator(client, creator)
        option = _options(poll)[0]
        resp = client.post(f"/e/{event.code}/voting/{poll.id}/vote", data={"option_id": option.id})
        assert resp.status_code == 302
        assert "/voting" in resp.headers["Location"]
        # The vote is recorded under the creator's participant Guest record.
        creator_guest = Guest.query.filter_by(creator_id=creator.id, event_id=event.id).first()
        assert creator_guest is not None
        votes = PollVote.query.filter_by(guest_id=creator_guest.id).all()
        assert len(votes) == 1
        assert votes[0].option_id == option.id

    def test_vote_404_invalid_poll(self, client, event, guest):
        _login_guest(client, event, guest)
        resp = client.post(f"/e/{event.code}/voting/invalid_id/vote", data={"option_id": "x" * 32})
        assert resp.status_code == 404

    def test_vote_404_invalid_option(self, client, event, guest, poll):
        _login_guest(client, event, guest)
        resp = client.post(f"/e/{event.code}/voting/{poll.id}/vote", data={"option_id": "y" * 32})
        assert resp.status_code == 404
        assert PollVote.query.count() == 0

    def test_vote_logs(self, client, event, guest, poll, db):
        _login_guest(client, event, guest)
        option = _options(poll)[0]
        client.post(f"/e/{event.code}/voting/{poll.id}/vote", data={"option_id": option.id})
        log = ActivityLog.query.filter_by(event_id=event.id, action="poll.voted").first()
        assert log is not None
        assert log.actor_type == "guest"
        assert log.target == poll.question
        assert log.details == option.label


# === TestClosePoll (3 tests) ===


class TestClosePoll:
    def test_close_poll_as_creator(self, client, creator, event, poll, db):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/voting/{poll.id}/close")
        assert resp.status_code == 302
        db.session.refresh(poll)
        assert poll.is_closed is True

    def test_close_poll_forbidden_for_guest(self, client, event, guest, poll, db):
        _login_guest(client, event, guest)
        resp = client.post(f"/e/{event.code}/voting/{poll.id}/close")
        assert resp.status_code == 403
        db.session.refresh(poll)
        assert poll.is_closed is False

    def test_close_poll_logs(self, client, creator, event, poll, db):
        _login_creator(client, creator)
        client.post(f"/e/{event.code}/voting/{poll.id}/close")
        log = ActivityLog.query.filter_by(event_id=event.id, action="poll.closed").first()
        assert log is not None
        assert log.target == poll.question
        assert log.actor_type == "creator"
