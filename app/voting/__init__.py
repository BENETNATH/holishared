"""Voting blueprint — sondages (B006)."""

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_babel import _
from werkzeug.wrappers import Response

from app.context import load_event_context, log_event
from app.extensions import db, limiter
from app.models import Poll, PollOption, PollVote

voting_bp = Blueprint("voting", __name__)

MIN_OPTIONS = 2
MAX_OPTIONS = 10
MAX_QUESTION_LENGTH = 300
MAX_OPTION_LENGTH = 200


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
    ctx = load_event_context(code)
    event = ctx.event

    polls = Poll.query.filter_by(event_id=event.id).order_by(Poll.created_at.asc()).all()
    open_polls = [poll for poll in polls if not poll.is_closed]
    closed_polls = [poll for poll in polls if poll.is_closed]

    guest_votes: dict[str, str] = {}
    if ctx.participant is not None:
        for vote in PollVote.query.filter_by(guest_id=ctx.participant.id).all():
            guest_votes[vote.option.poll_id] = vote.option_id

    return render_template(
        "voting/index.html",
        event=event,
        open_polls=open_polls,
        closed_polls=closed_polls,
        guest_votes=guest_votes,
        results=_poll_results,
    )


@voting_bp.route("/e/<code>/voting/new", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def create(code: str) -> Response | tuple[str, int] | str:
    """Create a new poll with its options."""
    ctx = load_event_context(code)
    event = ctx.event

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
    log_event(ctx, "poll.created", target=question)
    db.session.commit()

    flash(_("Sondage créé."))
    return redirect(url_for("voting.index", code=code))


@voting_bp.route("/e/<code>/voting/<poll_id>")
def detail(code: str, poll_id: str) -> Response | tuple[str, int] | str:
    """Show a single poll with its results."""
    ctx = load_event_context(code)
    event = ctx.event

    poll = Poll.query.filter_by(id=poll_id, event_id=event.id).first()
    if poll is None:
        abort(404)

    results, total = _poll_results(poll)
    guest_vote: PollVote | None = None
    if ctx.participant is not None:
        option_ids = [option.id for option in poll.options.all()]
        guest_vote = PollVote.query.filter(
            PollVote.guest_id == ctx.participant.id, PollVote.option_id.in_(option_ids)
        ).first()

    return render_template(
        "voting/detail.html",
        event=event,
        poll=poll,
        results=results,
        total=total,
        guest_vote=guest_vote,
    )


@voting_bp.route("/e/<code>/voting/<poll_id>/vote", methods=["POST"])
def vote(code: str, poll_id: str) -> Response | tuple[str, int] | str:
    """Cast (or replace) the actor's vote on a poll (creator or guest)."""
    ctx = load_event_context(code)
    event = ctx.event

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

    # One vote per actor per poll: remove any previous vote, then add the new one.
    participant = ctx.participant
    if participant is None:  # garanti par require="participant"
        abort(403)
    option_ids = [opt.id for opt in poll.options.all()]
    for old_vote in PollVote.query.filter(
        PollVote.guest_id == participant.id, PollVote.option_id.in_(option_ids)
    ).all():
        db.session.delete(old_vote)
    db.session.add(PollVote(option_id=option.id, guest_id=participant.id))
    log_event(ctx, "poll.voted", target=poll.question, details=option.label)
    db.session.commit()

    flash(_("Vote enregistré."))
    return redirect(url_for("voting.index", code=code))


@voting_bp.route("/e/<code>/voting/<poll_id>/close", methods=["POST"])
def close(code: str, poll_id: str) -> Response | tuple[str, int] | str:
    """Close a poll (creator only)."""
    ctx = load_event_context(code)
    poll = Poll.query.filter_by(id=poll_id, event_id=ctx.event.id).first()
    if poll is None:
        abort(404)
    if not ctx.can_edit(poll):
        abort(403)

    poll.is_closed = True
    log_event(ctx, "poll.closed", target=poll.question)
    db.session.commit()

    flash(_("Sondage fermé."))
    return redirect(url_for("voting.index", code=code))
