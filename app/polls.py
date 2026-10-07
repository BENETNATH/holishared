"""Logique partagée des sondages (B025) : résultats, gagnants, liens sondage ↔ activité."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.extensions import db
from app.models import Guest, Poll, PollOption, PollVote

KIND_FREE = "free"
KIND_ACTIVITIES = "activities"
KINDS = (KIND_FREE, KIND_ACTIVITIES)


@dataclass
class OptionResult:
    option: PollOption
    count: int
    fraction: float  # 0..1 des votants
    winner: bool  # gagnante d'un sondage clos (égalité : plusieurs)
    mine: bool


@dataclass
class PollView:
    """Un sondage prêt à afficher. Les comptes ne sont exposés qu'avec ``show_results``."""

    poll: Poll
    options: list[OptionResult]
    voters: int
    my_option_id: str | None
    show_results: bool
    winners: list[PollOption] = field(default_factory=list)

    @property
    def has_voted(self) -> bool:
        return self.my_option_id is not None


def poll_views(polls: Iterable[Poll], participant: Guest | None) -> list[PollView]:
    """Vues des sondages en trois requêtes ; résultats masqués avant le vote (sauf sondage clos)."""
    polls = list(polls)
    if not polls:
        return []
    ids = [p.id for p in polls]
    options: dict[str, list[PollOption]] = defaultdict(list)
    for option in (
        PollOption.query.filter(PollOption.poll_id.in_(ids))
        .order_by(PollOption.order.asc(), PollOption.id)
        .all()
    ):
        options[option.poll_id].append(option)
    counts: dict[str, int] = defaultdict(int)
    mine: dict[str, str] = {}
    for option_id, poll_id, guest_id in (
        db.session.query(PollVote.option_id, PollOption.poll_id, PollVote.guest_id)
        .join(PollOption, PollOption.id == PollVote.option_id)
        .filter(PollOption.poll_id.in_(ids))
    ):
        counts[option_id] += 1
        if participant is not None and guest_id == participant.id:
            mine[poll_id] = option_id
    views = []
    for poll in polls:
        opts = options[poll.id]
        voters = sum(counts[o.id] for o in opts)
        top = max((counts[o.id] for o in opts), default=0)
        decided = poll.is_closed and voters > 0
        show = poll.is_closed or poll.id in mine
        results = [
            OptionResult(
                option=o,
                count=counts[o.id],
                fraction=counts[o.id] / voters if voters else 0.0,
                winner=decided and counts[o.id] == top,
                mine=mine.get(poll.id) == o.id,
            )
            for o in opts
        ]
        views.append(
            PollView(
                poll=poll,
                options=results,
                voters=voters,
                my_option_id=mine.get(poll.id),
                show_results=show,
                winners=[r.option for r in results if r.winner],
            )
        )
    return views


@dataclass
class ActivityPolls:
    """Sondages d'activités qui touchent une activité."""

    open_poll_id: str | None = None  # sondage ouvert (badge « En vote »)
    retain_poll_id: str | None = None  # sondage clos dont l'activité est gagnante (« Retenir »)


def activity_polls(event_id: str) -> dict[str, ActivityPolls]:
    """Par activité : sondage ouvert qui la propose, sondage clos qu'elle a gagné (le plus récent)."""
    polls = (
        Poll.query.filter_by(event_id=event_id, kind=KIND_ACTIVITIES)
        .order_by(Poll.created_at.asc(), Poll.id)
        .all()
    )
    out: dict[str, ActivityPolls] = defaultdict(ActivityPolls)
    for view in poll_views(polls, None):
        for result in view.options:
            activity_id = result.option.activity_id
            if activity_id is None:
                continue
            if not view.poll.is_closed:
                out[activity_id].open_poll_id = out[activity_id].open_poll_id or view.poll.id
            elif result.winner:
                out[activity_id].retain_poll_id = view.poll.id
    return out
