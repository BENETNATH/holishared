"""Voting blueprint — sondages (B006, B025) : question libre ou départage d'activités."""

import json
from dataclasses import dataclass, field

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_babel import _
from werkzeug.wrappers import Response

from app.context import EventContext, load_event_context, log_event
from app.extensions import db, limiter
from app.forms import FormErrors
from app.i18n import format_date_safe
from app.models import Activity, Poll, PollOption, PollVote
from app.polls import KIND_ACTIVITIES, KIND_FREE, KINDS, poll_views
from app.push import notify

voting_bp = Blueprint("voting", __name__)

MIN_OPTIONS = 2
MAX_OPTIONS = 10
MAX_QUESTION_LENGTH = 300
MAX_OPTION_LENGTH = 200


@dataclass
class PollFields:
    """Champs validés du formulaire de création."""

    question: str
    kind: str
    free_labels: list[str] = field(default_factory=list)
    activities: list[Activity] = field(default_factory=list)


def _htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


def _activity_choices(ctx: EventContext) -> list[Activity]:
    """Activités proposables au vote : Planning actif, activités non écartées."""
    if "planning" not in current_app.blueprints:
        return []
    return list(
        Activity.query.filter(Activity.event_id == ctx.event.id, Activity.status != "dropped")
        .order_by(Activity.date, Activity.start_time.asc().nulls_first(), Activity.created_at)
        .all()
    )


def _form_context(
    ctx: EventContext, form_data: dict[str, object], errors: FormErrors
) -> dict[str, object]:
    choices = _activity_choices(ctx)
    return {
        "event": ctx.event,
        "form_data": form_data,
        "errors": errors,
        "activity_choices": choices,
        "activities_available": len(choices) >= MIN_OPTIONS,
        "default_activity_question": _("Quelle activité choisir ?"),
    }


def _activity_label(activity: Activity) -> str:
    day = format_date_safe(activity.date, "EEE d MMM")
    suffix = f" — {day}"
    return activity.title[: MAX_OPTION_LENGTH - len(suffix)] + suffix


def _validate_poll_form(
    ctx: EventContext,
) -> tuple[FormErrors, dict[str, object], PollFields]:
    """Valide le formulaire ; ``form_data`` sert à réafficher la saisie."""
    errors = FormErrors()
    question = request.form.get("question", "").strip()
    kind = request.form.get("kind", KIND_FREE).strip() or KIND_FREE
    options_raw = request.form.get("options", "")
    chosen_ids = list(dict.fromkeys(request.form.getlist("activity_ids")))

    if len(question) < 2:
        errors.add("question", _("Question requise (min 2 caractères)."))
    elif len(question) > MAX_QUESTION_LENGTH:
        errors.add("question", _("Question trop longue (max 300 caractères)."))

    labels = [line.strip() for line in options_raw.splitlines() if line.strip()]
    fields = PollFields(question=question, kind=KIND_FREE, free_labels=labels)
    if kind not in KINDS:
        errors.add("kind", _("Type de sondage invalide."))
    elif kind == KIND_FREE:
        if len(labels) < MIN_OPTIONS:
            errors.add("options", _("Au moins 2 options requises (une par ligne)."))
        elif len(labels) > MAX_OPTIONS:
            errors.add("options", _("Maximum 10 options (une par ligne)."))
    else:
        fields.kind = KIND_ACTIVITIES
        if "planning" not in current_app.blueprints:
            errors.add("kind", _("Le Planning n'est pas activé : choisissez une question libre."))
        else:
            found = {
                a.id: a
                for a in Activity.query.filter(
                    Activity.event_id == ctx.event.id,
                    Activity.status != "dropped",
                    Activity.id.in_(chosen_ids),
                )
            }
            if len(found) != len(chosen_ids):
                errors.add("activity_ids", _("Activité introuvable dans cet événement."))
            elif len(found) < MIN_OPTIONS:
                errors.add("activity_ids", _("Sélectionnez au moins 2 activités."))
            elif len(found) + len(labels) > MAX_OPTIONS:
                errors.add("options", _("Maximum 10 options (activités comprises)."))
            fields.activities = [found[i] for i in chosen_ids if i in found]
    if any(len(label) > MAX_OPTION_LENGTH for label in labels):
        errors.add("options", _("Option trop longue (max 200 caractères)."))

    form_data: dict[str, object] = {
        "question": question,
        "kind": kind,
        "options": options_raw,
        "activity_ids": chosen_ids,
    }
    return errors, form_data, fields


def _load_poll(ctx: EventContext, poll_id: str) -> Poll:
    poll: Poll | None = Poll.query.filter_by(id=poll_id, event_id=ctx.event.id).first()
    if poll is None:
        abort(404)
    return poll


def _poll_response(
    ctx: EventContext,
    poll: Poll,
    *,
    detail: bool,
    status: int = 200,
    toast: tuple[str, str] | None = None,
) -> Response:
    """Fragment de carte à jour (réponse HTMX)."""
    view = poll_views([poll], ctx.participant)[0]
    html = render_template("voting/_poll.html", ctx=ctx, event=ctx.event, view=view, detail=detail)
    response = make_response(html, status)
    if toast is not None:
        message, tone = toast
        response.headers["HX-Trigger"] = json.dumps(
            {"ui:toast": {"message": message, "tone": tone}}
        )
    return response


@voting_bp.route("/e/<code>/voting")
def index(code: str) -> Response | tuple[str, int] | str:
    """Sondages de l'événement : ouverts d'abord (les plus récents en tête), puis clos."""
    ctx = load_event_context(code)
    polls = (
        Poll.query.filter_by(event_id=ctx.event.id).order_by(Poll.created_at.desc(), Poll.id).all()
    )
    views = poll_views(polls, ctx.participant)
    return render_template(
        "voting/index.html",
        open_views=[v for v in views if not v.poll.is_closed],
        closed_views=[v for v in views if v.poll.is_closed],
        **_form_context(ctx, {"kind": KIND_FREE}, FormErrors()),
    )


@voting_bp.route("/e/<code>/voting/new", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def create(code: str) -> Response | tuple[str, int] | str:
    """Crée un sondage (question libre ou départage d'activités)."""
    ctx = load_event_context(code)

    if request.method == "GET":
        return render_template(
            "voting/form.html", **_form_context(ctx, {"kind": KIND_FREE}, FormErrors())
        )

    errors, form_data, fields = _validate_poll_form(ctx)
    if errors:
        return render_template("voting/form.html", **_form_context(ctx, form_data, errors))

    poll = Poll(
        question=fields.question,
        kind=fields.kind,
        event_id=ctx.event.id,
        created_by=ctx.participant.id if ctx.participant else None,
    )
    order = 0
    for activity in fields.activities:
        poll.options.append(
            PollOption(label=_activity_label(activity), order=order, activity_id=activity.id)
        )
        order += 1
    for label in fields.free_labels:
        poll.options.append(PollOption(label=label, order=order))
        order += 1
    db.session.add(poll)
    log_event(ctx, "poll.created", target=fields.question)
    db.session.commit()
    notify(
        ctx.event,
        "polls",
        ctx.participant,
        fields.question,
        url_for("voting.index", code=code),
        f"poll-{poll.id}",
    )

    flash(_("Sondage créé."))
    return redirect(url_for("voting.detail", code=code, poll_id=poll.id))


@voting_bp.route("/e/<code>/voting/<poll_id>")
def detail(code: str, poll_id: str) -> Response | tuple[str, int] | str:
    """Un sondage : vote en un geste, résultats après le vote, gestion (clore, supprimer)."""
    ctx = load_event_context(code)
    poll = _load_poll(ctx, poll_id)
    return render_template(
        "voting/detail.html",
        event=ctx.event,
        view=poll_views([poll], ctx.participant)[0],
    )


@voting_bp.route("/e/<code>/voting/<poll_id>/vote", methods=["POST"])
def vote(code: str, poll_id: str) -> Response | tuple[str, int] | str:
    """Enregistre (ou remplace) le vote du participant, créateur compris.

    Une requête HTMX reçoit la carte à jour ; sinon redirection.
    """
    ctx = load_event_context(code)
    participant = ctx.participant
    if participant is None:  # garanti par require="participant"
        abort(403)
    poll = _load_poll(ctx, poll_id)
    detail = request.form.get("detail") == "1"
    back = (
        url_for("voting.detail", code=code, poll_id=poll.id)
        if detail
        else url_for("voting.index", code=code)
    )

    option = PollOption.query.filter_by(
        id=request.form.get("option_id", ""), poll_id=poll.id
    ).first()
    if option is None:
        abort(404)

    if poll.is_closed:
        if _htmx():
            return _poll_response(
                ctx, poll, detail=detail, toast=(_("Ce sondage est clos."), "warning")
            )
        flash(_("Ce sondage est clos."), "warning")
        return redirect(back)

    # Un vote par participant et par sondage : l'ancien est remplacé.
    option_ids = [opt.id for opt in poll.options.all()]
    previous = PollVote.query.filter(
        PollVote.guest_id == participant.id, PollVote.option_id.in_(option_ids)
    ).all()
    if not any(v.option_id == option.id for v in previous):
        for old_vote in previous:
            db.session.delete(old_vote)
        db.session.add(PollVote(option_id=option.id, guest_id=participant.id))
        log_event(ctx, "poll.voted", target=poll.question, details=option.label)
        db.session.commit()

    if _htmx():
        return _poll_response(ctx, poll, detail=detail)
    flash(_("Vote enregistré."))
    return redirect(back)


@voting_bp.route("/e/<code>/voting/<poll_id>/close", methods=["POST"])
def close(code: str, poll_id: str) -> Response | tuple[str, int] | str:
    """Clôt un sondage (créateur ou auteur du sondage)."""
    ctx = load_event_context(code)
    poll = _load_poll(ctx, poll_id)
    if not ctx.can_edit(poll):
        abort(403)

    if not poll.is_closed:
        poll.is_closed = True
        log_event(ctx, "poll.closed", target=poll.question)
        db.session.commit()
    flash(_("Sondage clos."))
    return redirect(url_for("voting.detail", code=code, poll_id=poll.id))


@voting_bp.route("/e/<code>/voting/<poll_id>/reopen", methods=["POST"])
def reopen(code: str, poll_id: str) -> Response | tuple[str, int] | str:
    """Rouvre un sondage clos (créateur de l'événement)."""
    ctx = load_event_context(code)
    poll = _load_poll(ctx, poll_id)
    if not ctx.is_creator:
        abort(403)

    if poll.is_closed:
        poll.is_closed = False
        log_event(ctx, "poll.reopened", target=poll.question)
        db.session.commit()
    flash(_("Sondage rouvert."))
    return redirect(url_for("voting.detail", code=code, poll_id=poll.id))


@voting_bp.route("/e/<code>/voting/<poll_id>/delete", methods=["POST"])
def delete(code: str, poll_id: str) -> Response | tuple[str, int] | str:
    """Supprime un sondage et ses votes (créateur ou auteur du sondage)."""
    ctx = load_event_context(code)
    poll = _load_poll(ctx, poll_id)
    if not ctx.can_delete(poll):
        abort(403)

    question = poll.question
    db.session.delete(poll)
    log_event(ctx, "poll.deleted", target=question)
    db.session.commit()
    flash(_("Sondage supprimé."))
    return redirect(url_for("voting.index", code=code))
