"""Voting blueprint — sondages (B006)."""

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import _
from flask_login import current_user
from werkzeug.wrappers import Response

from app.extensions import db, limiter
from app.models import Event, Guest, Poll, PollOption, PollVote
from app.utils import log_action

voting_bp = Blueprint("voting", __name__)

MIN_OPTIONS = 2
MAX_OPTIONS = 10
MAX_QUESTION_LENGTH = 300
MAX_OPTION_LENGTH = 200


def _get_event_or_404(code: str) -> Event:
    """Load an active event by code or abort with 404."""
    event: Event | None = Event.query.filter_by(code=code, is_active=True).first()
    if event is None:
        abort(404)
    return event


def _resolve_actor(event: Event, code: str) -> tuple[Guest | None, bool, Response | None]:
    """Resolve the current actor for an event.

    Returns (guest, is_creator, denied). ``denied`` is a redirect to the
    mycode page when neither the creator nor a guest session matches.
    """
    if current_user.is_authenticated and current_user.id == event.creator_id:
        return None, True, None
    guest_id = session.get(f"guest_{code}")
    if guest_id:
        guest = Guest.query.filter_by(id=guest_id, event_id=event.id, is_active=True).first()
        if guest is not None:
            return guest, False, None
    return None, False, redirect(url_for("events.my_code", code=code))


def _actor_name(guest: Guest | None, is_creator: bool) -> tuple[str, str]:
    """(actor_name, actor_type) for ActivityLog entries."""
    if is_creator:
        return (current_user.display_name or "Créateur"), "creator"
    if guest is not None:
        return guest.display_name, "guest"
    return "Système", "system"


def _poll_results(poll: Poll) -> tuple[list[dict[str, object]], int]:
    """Real-time results: per-option count and percentage, plus total votes."""
    options = PollOption.query.filter_by(poll_id=poll.id).order_by(PollOption.order.asc()).all()
    results: list[dict[str, object]] = []
    total = 0
    for option in options:
        count = PollVote.query.filter_by(option_id=option.id).count()
        total += count
        results.append(
            {
                "option": option,
                "count": count,
                "percent": round(count * 100 / total) if total else 0,
            }
        )
    return results, total


def _validate_poll_form() -> tuple[list[str], dict[str, str], str, list[str]]:
    """Validate the poll creation form.

    Returns (errors, form_data, question, option_labels).
    """
    errors: list[str] = []
    question = request.form.get("question", "").strip()
    options_raw = request.form.get("options", "")

    if len(question) < 2:
        errors.append(_("Question requise (min 2 caractères)."))
    elif len(question) > MAX_QUESTION_LENGTH:
        errors.append(_("Question trop longue (max 300 caractères)."))

    labels = [line.strip() for line in options_raw.splitlines() if line.strip()]
    if len(labels) < MIN_OPTIONS:
        errors.append(_("Au moins 2 options requises (une par ligne)."))
    elif len(labels) > MAX_OPTIONS:
        errors.append(_("Maximum 10 options (une par ligne)."))
    elif any(len(label) > MAX_OPTION_LENGTH for label in labels):
        errors.append(_("Option trop longue (max 200 caractères)."))

    form_data = {"question": question, "options": options_raw}
    return errors, form_data, question, labels


@voting_bp.route("/e/<code>/voting")
def index(code: str) -> Response | tuple[str, int] | str:
    """List the event's polls with live results."""
    event = _get_event_or_404(code)
    guest, _, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    polls = Poll.query.filter_by(event_id=event.id).order_by(Poll.created_at.asc()).all()
    open_polls = [poll for poll in polls if not poll.is_closed]
    closed_polls = [poll for poll in polls if poll.is_closed]

    guest_votes: dict[str, str] = {}
    if guest is not None:
        for vote in PollVote.query.filter_by(guest_id=guest.id).all():
            guest_votes[vote.option.poll_id] = vote.option_id

    return render_template(
        "voting/index.html",
        event=event,
        open_polls=open_polls,
        closed_polls=closed_polls,
        guest=guest,
        guest_votes=guest_votes,
        results=_poll_results,
    )


@voting_bp.route("/e/<code>/voting/new", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def create(code: str) -> Response | tuple[str, int] | str:
    """Create a new poll with its options."""
    event = _get_event_or_404(code)
    guest, is_creator, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    if request.method == "GET":
        return render_template(
            "voting/form.html",
            event=event,
            form_data={},
            errors=[],
        )

    errors, form_data, question, labels = _validate_poll_form()
    if errors:
        return render_template(
            "voting/form.html",
            event=event,
            form_data=form_data,
            errors=errors,
        )

    poll = Poll(question=question, event_id=event.id)
    for order, label in enumerate(labels):
        poll.options.append(PollOption(label=label, order=order))
    db.session.add(poll)
    actor_name, actor_type = _actor_name(guest, is_creator)
    log_action(db.session, event.id, actor_name, actor_type, "poll.created", target=question)
    db.session.commit()

    flash(_("Sondage créé."))
    return redirect(url_for("voting.index", code=code))


@voting_bp.route("/e/<code>/voting/<poll_id>")
def detail(code: str, poll_id: str) -> Response | tuple[str, int] | str:
    """Show a single poll with its results."""
    event = _get_event_or_404(code)
    guest, _, denied = _resolve_actor(event, code)
    if denied is not None:
        return denied

    poll = Poll.query.filter_by(id=poll_id, event_id=event.id).first()
    if poll is None:
        abort(404)

    results, total = _poll_results(poll)
    guest_vote: PollVote | None = None
    if guest is not None:
        option_ids = [option.id for option in poll.options.all()]
        guest_vote = PollVote.query.filter(
            PollVote.guest_id == guest.id, PollVote.option_id.in_(option_ids)
        ).first()

    return render_template(
        "voting/detail.html",
        event=event,
        poll=poll,
        results=results,
        total=total,
        guest=guest,
        guest_vote=guest_vote,
    )


@voting_bp.route("/e/<code>/voting/<poll_id>/vote", methods=["POST"])
def vote(code: str, poll_id: str) -> Response | tuple[str, int] | str:
    """Cast (or replace) the guest's vote on a poll."""
    event = _get_event_or_404(code)

    if current_user.is_authenticated and current_user.id == event.creator_id:
        return _("Le créateur ne vote pas."), 403

    guest_id = session.get(f"guest_{code}")
    guest = None
    if guest_id:
        guest = Guest.query.filter_by(id=guest_id, event_id=event.id, is_active=True).first()
    if guest is None:
        return redirect(url_for("events.my_code", code=code))

    poll = Poll.query.filter_by(id=poll_id, event_id=event.id).first()
    if poll is None:
        abort(404)

    option_id = request.form.get("option_id", "")
    option = PollOption.query.filter_by(id=option_id, poll_id=poll.id).first()
    if option is None:
        abort(404)

    if poll.is_closed:
        flash(_("Sondage fermé."), "warning")
        return redirect(url_for("voting.index", code=code))

    # One vote per guest per poll: remove any previous vote, then add the new one.
    option_ids = [opt.id for opt in poll.options.all()]
    for old_vote in PollVote.query.filter(
        PollVote.guest_id == guest.id, PollVote.option_id.in_(option_ids)
    ).all():
        db.session.delete(old_vote)
    db.session.add(PollVote(option_id=option.id, guest_id=guest.id))
    log_action(
        db.session,
        event.id,
        guest.display_name,
        "guest",
        "poll.voted",
        target=poll.question,
        details=option.label,
    )
    db.session.commit()

    flash(_("Vote enregistré."))
    return redirect(url_for("voting.index", code=code))


@voting_bp.route("/e/<code>/voting/<poll_id>/close", methods=["POST"])
def close(code: str, poll_id: str) -> Response | tuple[str, int] | str:
    """Close a poll (creator only)."""
    event = _get_event_or_404(code)
    if not (current_user.is_authenticated and current_user.id == event.creator_id):
        return _("Pas autorisé."), 403

    poll = Poll.query.filter_by(id=poll_id, event_id=event.id).first()
    if poll is None:
        abort(404)

    poll.is_closed = True
    log_action(
        db.session,
        event.id,
        current_user.display_name or "Créateur",
        "creator",
        "poll.closed",
        target=poll.question,
    )
    db.session.commit()

    flash(_("Sondage fermé."))
    return redirect(url_for("voting.index", code=code))
