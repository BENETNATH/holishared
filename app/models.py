"""Database models for holishared."""

import secrets
import string
from datetime import date, datetime, time
from typing import Any, cast

from flask_login import UserMixin
from sqlalchemy.orm import Mapped

from app.extensions import db

CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # sans 0 1 i l o
RESERVED_EVENT_CODES = frozenset({"access", "verify"})


def generate_event_code(length: int = 6) -> str:
    """Generate a short event code (URL-safe), never a reserved route word."""
    alphabet = string.ascii_lowercase + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(length))
        if code not in RESERVED_EVENT_CODES:
            return code


def generate_guest_code(length: int = 8) -> str:
    """Generate an access code over an unambiguous alphabet."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


class Creator(UserMixin, db.Model):  # type: ignore[misc,name-defined]
    """Event creator (validated by email)."""

    __tablename__ = "creators"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    email: Mapped[str | None] = db.Column(db.String(255), unique=True, nullable=True)
    email_verified: Mapped[bool] = db.Column(db.Boolean, default=False)
    verification_token: Mapped[str] = db.Column(db.String(64), default=lambda: secrets.token_hex(32))
    verification_sent_at: Mapped[datetime | None] = db.Column(db.DateTime, nullable=True)
    display_name: Mapped[str] = db.Column(db.String(100), default="")
    personal_code: Mapped[str] = db.Column(db.String(8), unique=True, nullable=True, default=None)
    # Freemium feature tier: "free", "pro", "unlimited".
    # (Distinct from MediaQuota.tier, which is the storage-storage tier.)
    tier: Mapped[str] = db.Column(db.String(20), nullable=False, default="free", server_default="free")
    created_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)

    events = db.relationship("Event", backref="creator", lazy="dynamic")

    def get_id(self) -> str:
        return self.id


class Event(db.Model):  # type: ignore[misc,name-defined]
    """A shared event (vacation, weekend, project)."""

    __tablename__ = "events"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    code: Mapped[str] = db.Column(db.String(6), unique=True, nullable=False, default=generate_event_code)
    title: Mapped[str] = db.Column(db.String(200), nullable=False)
    description: Mapped[str] = db.Column(db.Text, default="")
    start_date: Mapped[date] = db.Column(db.Date, nullable=False)
    end_date: Mapped[date] = db.Column(db.Date, nullable=False)
    location: Mapped[str] = db.Column(db.String(300), default="")
    is_active: Mapped[bool] = db.Column(db.Boolean, default=True)
    created_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)
    verification_token: Mapped[str | None] = db.Column(db.String(64), nullable=True, unique=True)
    verified_at: Mapped[datetime | None] = db.Column(db.DateTime, nullable=True)

    creator_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("creators.id"), nullable=False)
    # The email that created the event. The event is tied to this email, not
    # to a separate "account": any email can create an event.
    creator_email: Mapped[str | None] = db.Column(db.String(255), nullable=True)

    guests = db.relationship("Guest", backref="event", lazy="dynamic", cascade="all, delete-orphan")
    activities = db.relationship(
        "Activity", backref="event", lazy="dynamic", cascade="all, delete-orphan"
    )
    meals = db.relationship(
        "Meal", backref="event", lazy="dynamic", cascade="all, delete-orphan"
    )
    lists = db.relationship(
        "SharedList", backref="event", lazy="dynamic", cascade="all, delete-orphan"
    )
    polls = db.relationship("Poll", backref="event", lazy="dynamic", cascade="all, delete-orphan")
    logistics_items = db.relationship(
        "LogisticsItem", backref="event", lazy="dynamic", cascade="all, delete-orphan"
    )
    chat_messages = db.relationship(
        "ChatMessage", backref="event", lazy="dynamic", cascade="all, delete-orphan"
    )
    # Audit trail is purged with the event (right-to-be-forgotten).
    activity_logs = db.relationship(
        "ActivityLog", backref="event_log", lazy="dynamic", cascade="all, delete-orphan"
    )

    @property
    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def guest_count(self) -> int:
        """Participants actifs, créateur compris (base de la limite d'invités, B020)."""
        return cast("int", self.guests.filter_by(is_active=True).count())


class Guest(db.Model):  # type: ignore[misc,name-defined]
    """A guest with a personal code (no personal data stored)."""

    __tablename__ = "guests"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    code: Mapped[str] = db.Column(db.String(16), nullable=False)
    display_name: Mapped[str] = db.Column(db.String(50), nullable=False)
    # Optional contact email, used only so the creator can re-send the
    # "create your code" invitation. Not required to join.
    email: Mapped[str | None] = db.Column(db.String(255), nullable=True)
    is_active: Mapped[bool] = db.Column(db.Boolean, default=True)
    joined_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)

    event_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False)
    # Set when this Guest is the event creator's own participant identity
    # (the creator is a participant in their own event: they can vote, RSVP,
    # and appear in the groups). Null for regular invited guests.
    creator_id: Mapped[str | None] = db.Column(db.String(32), db.ForeignKey("creators.id"), nullable=True)

    # Unique constraint: one code per event
    __table_args__ = (db.UniqueConstraint("event_id", "code", name="uq_guest_event_code"),)

    activity_rsvps = db.relationship(
        "ActivityRSVP", backref="guest", lazy="dynamic", cascade="all, delete-orphan"
    )
    poll_votes = db.relationship(
        "PollVote", backref="guest", lazy="dynamic", cascade="all, delete-orphan"
    )


class Activity(db.Model):  # type: ignore[misc,name-defined]
    """A planned activity."""

    __tablename__ = "activities"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    title: Mapped[str] = db.Column(db.String(200), nullable=False)
    description: Mapped[str] = db.Column(db.Text, default="")
    date: Mapped[date] = db.Column(db.Date, nullable=False)
    start_time: Mapped[time | None] = db.Column(db.Time, default=None)
    end_time: Mapped[time | None] = db.Column(db.Time, default=None)
    location: Mapped[str] = db.Column(db.String(300), default="")
    min_headcount: Mapped[int] = db.Column(db.Integer, default=1)
    bring_items: Mapped[str] = db.Column(db.Text, default="")  # "who brings what"
    # B025 : issue d'un sondage d'activités ('planned' | 'retained' | 'dropped').
    status: Mapped[str] = db.Column(
        db.String(10), nullable=False, default="planned", server_default="planned"
    )
    created_by: Mapped[str | None] = db.Column(db.String(32), db.ForeignKey("guests.id"), default=None)
    created_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)

    event_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False)

    rsvps = db.relationship(
        "ActivityRSVP", backref="activity", lazy="dynamic", cascade="all, delete-orphan"
    )

    @property
    def confirmed_count(self) -> int:
        return sum(1 for r in self.rsvps if r.status == "yes")  # type: ignore[misc,attr-defined]


MAX_MEALS_PER_CELL = 6


class Meal(db.Model):  # type: ignore[misc,name-defined]
    """A planned meal (lunch or dinner) in the meal grid.

    Several meals can share a (event, date, slot) cell (B022, at most
    ``MAX_MEALS_PER_CELL``); ``position`` orders them inside the cell.
    """

    __tablename__ = "meals"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    title: Mapped[str] = db.Column(db.String(200), nullable=False)
    date: Mapped[date] = db.Column(db.Date, nullable=False)
    slot: Mapped[str] = db.Column(db.String(10), nullable=False)  # 'lunch' | 'dinner'
    position: Mapped[int] = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    created_by: Mapped[str | None] = db.Column(db.String(32), db.ForeignKey("guests.id"), default=None)
    created_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)

    event_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False)

    __table_args__ = (db.Index("ix_meal_cell", "event_id", "date", "slot", "position"),)

    @staticmethod
    def ordering() -> tuple[Any, ...]:
        """ORDER BY chronologique : jour, midi avant soir, position dans la case."""
        lunch_first = db.case((Meal.slot == "lunch", 0), else_=1)
        return (Meal.date, lunch_first, Meal.position, Meal.created_at, Meal.id)


class ActivityRSVP(db.Model):  # type: ignore[misc,name-defined]
    """RSVP for an activity."""

    __tablename__ = "activity_rsvps"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    status: Mapped[str] = db.Column(db.String(10), nullable=False)  # yes, no, maybe
    updated_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    activity_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("activities.id"), nullable=False)
    guest_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("guests.id"), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("activity_id", "guest_id", name="uq_rsvp_activity_guest"),
    )


class ActivityLog(db.Model):  # type: ignore[misc,name-defined]
    """Audit trail of actions on an event (B002)."""

    __tablename__ = "activity_logs"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    actor_name: Mapped[str] = db.Column(db.String(100), nullable=False)
    actor_type: Mapped[str] = db.Column(db.String(20), nullable=False)  # creator, guest, system
    action: Mapped[str] = db.Column(db.String(50), nullable=False)
    target: Mapped[str | None] = db.Column(db.String(200), default=None)
    details: Mapped[str | None] = db.Column(db.Text, default=None)
    created_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    event_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False, index=True)


class SharedList(db.Model):  # type: ignore[misc,name-defined]
    """A shared list (shopping, packing, etc.)."""

    __tablename__ = "shared_lists"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    title: Mapped[str] = db.Column(db.String(200), nullable=False)
    list_type: Mapped[str] = db.Column(db.String(50), default="general")  # shopping, packing, materials, buffet
    # Colonnes JSON historiques : ni lues ni écrites depuis B023 (remplacées par ListMealCoverage /
    # ListActivityCoverage, migrées par app.migrations) ; suppression physique prévue en B028.
    covered_meals: Mapped[list] = db.Column(db.JSON, default=list)
    covered_activities: Mapped[list] = db.Column(db.JSON, default=list)
    created_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)

    event_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False)

    items = db.relationship(
        "ListItem", backref="parent_list", lazy="dynamic", cascade="all, delete-orphan"
    )


class ListItem(db.Model):  # type: ignore[misc,name-defined]
    """An item in a shared list."""

    __tablename__ = "list_items"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    name: Mapped[str] = db.Column(db.String(300), nullable=False)
    quantity: Mapped[str] = db.Column(db.String(50), default="1")
    assigned_to: Mapped[str] = db.Column(db.String(50), default="")  # display name of who takes it
    assigned_to_id: Mapped[str | None] = db.Column(db.String(32), nullable=True)  # guest id or creator id
    is_done: Mapped[bool] = db.Column(db.Boolean, default=False)
    section: Mapped[str] = db.Column(db.String(100), default="")  # category within the list
    created_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)
    created_by: Mapped[str | None] = db.Column(db.String(32), db.ForeignKey("guests.id"), default=None)

    list_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("shared_lists.id"), nullable=False)


class ListMealCoverage(db.Model):  # type: ignore[misc,name-defined]
    """« Cette liste prend en compte ce repas » (B023) ; supprimée en cascade avec la liste ou le repas."""

    __tablename__ = "list_meal_coverages"

    list_id: Mapped[str] = db.Column(
        db.String(32), db.ForeignKey("shared_lists.id", ondelete="CASCADE"), primary_key=True
    )
    meal_id: Mapped[str] = db.Column(
        db.String(32), db.ForeignKey("meals.id", ondelete="CASCADE"), primary_key=True
    )
    covered_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)
    covered_by: Mapped[str | None] = db.Column(
        db.String(32), db.ForeignKey("guests.id", ondelete="SET NULL"), default=None
    )


class ListActivityCoverage(db.Model):  # type: ignore[misc,name-defined]
    """« Cette liste prend en compte cette activité » (B023) ; supprimée en cascade."""

    __tablename__ = "list_activity_coverages"

    list_id: Mapped[str] = db.Column(
        db.String(32), db.ForeignKey("shared_lists.id", ondelete="CASCADE"), primary_key=True
    )
    activity_id: Mapped[str] = db.Column(
        db.String(32), db.ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True
    )
    covered_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)
    covered_by: Mapped[str | None] = db.Column(
        db.String(32), db.ForeignKey("guests.id", ondelete="SET NULL"), default=None
    )


class Poll(db.Model):  # type: ignore[misc,name-defined]
    """A poll/vote."""

    __tablename__ = "polls"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    question: Mapped[str] = db.Column(db.String(300), nullable=False)
    is_closed: Mapped[bool] = db.Column(db.Boolean, default=False)
    # B025 : 'free' (question libre) | 'activities' (départager des activités du Planning).
    kind: Mapped[str] = db.Column(db.String(20), nullable=False, default="free", server_default="free")
    created_by: Mapped[str | None] = db.Column(db.String(32), db.ForeignKey("guests.id"), default=None)
    created_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)

    event_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False)

    options = db.relationship(
        "PollOption", backref="poll", lazy="dynamic", cascade="all, delete-orphan"
    )


class PollOption(db.Model):  # type: ignore[misc,name-defined]
    """An option in a poll."""

    __tablename__ = "poll_options"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    label: Mapped[str] = db.Column(db.String(200), nullable=False)
    order: Mapped[int] = db.Column(db.Integer, default=0)

    poll_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("polls.id"), nullable=False)
    # B025 : activité départagée ; supprimée -> NULL, l'option garde son libellé.
    activity_id: Mapped[str | None] = db.Column(
        db.String(32), db.ForeignKey("activities.id", ondelete="SET NULL"), default=None
    )

    votes = db.relationship(
        "PollVote", backref="option", lazy="dynamic", cascade="all, delete-orphan"
    )
    activity = db.relationship("Activity", lazy="joined")


class PollVote(db.Model):  # type: ignore[misc,name-defined]
    """A vote on a poll option."""

    __tablename__ = "poll_votes"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    voted_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)

    option_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("poll_options.id"), nullable=False)
    guest_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("guests.id"), nullable=False)

    __table_args__ = (db.UniqueConstraint("option_id", "guest_id", name="uq_vote_option_guest"),)


class LogisticsItem(db.Model):  # type: ignore[misc,name-defined]
    """A logistics/practical info item."""

    __tablename__ = "logistics_items"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    title: Mapped[str] = db.Column(db.String(200), nullable=False)
    content: Mapped[str] = db.Column(db.Text, default="")
    category: Mapped[str] = db.Column(db.String(50), default="general")  # address, access, timing, docs, notes
    order: Mapped[int] = db.Column(db.Integer, default=0)
    created_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)

    event_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False)


class MediaItem(db.Model):  # type: ignore[misc,name-defined]
    """Shared media (photo/video) with geolocation and dating."""

    __tablename__ = "media_items"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    filename: Mapped[str] = db.Column(db.String(255), nullable=False)  # stored filename
    original_name: Mapped[str] = db.Column(db.String(255), default="")  # user's original filename
    mime_type: Mapped[str] = db.Column(db.String(100), nullable=False)  # image/jpeg, video/mp4, etc.
    size_bytes: Mapped[int] = db.Column(db.Integer, nullable=False)  # file size in bytes
    caption: Mapped[str] = db.Column(db.Text, default="")  # optional description

    # Geolocation (WGS84)
    latitude: Mapped[float | None] = db.Column(db.Float, nullable=True)
    longitude: Mapped[float | None] = db.Column(db.Float, nullable=True)
    geo_precision: Mapped[str] = db.Column(db.String(20), default="approximate")  # exact, approximate, city

    # Dating
    taken_at: Mapped[datetime | None] = db.Column(db.DateTime, nullable=True)  # when the photo/video was taken
    uploaded_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)  # when uploaded to the event

    # Author
    uploaded_by: Mapped[str | None] = db.Column(db.String(32), db.ForeignKey("guests.id"), nullable=True)
    uploaded_by_name: Mapped[str] = db.Column(db.String(100), default="Créateur")  # denormalized for display

    event_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False, index=True)

    event = db.relationship(
        "Event", backref=db.backref("media", lazy="dynamic", cascade="all, delete-orphan")
    )
    uploader = db.relationship("Guest", foreign_keys=[uploaded_by])

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @property
    def display_date(self) -> datetime | None:
        return self.taken_at or self.uploaded_at


class ChatMessage(db.Model):  # type: ignore[misc,name-defined]
    """A chat message on an event (B008)."""

    __tablename__ = "chat_messages"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    content: Mapped[str] = db.Column(db.Text, nullable=False)
    created_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    guest_id: Mapped[str | None] = db.Column(db.String(32), db.ForeignKey("guests.id"), nullable=True)
    author_name: Mapped[str] = db.Column(db.String(100), nullable=False)
    author_type: Mapped[str] = db.Column(db.String(20), nullable=False)  # creator, guest

    event_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False, index=True)


class MediaQuota(db.Model):  # type: ignore[misc,name-defined]
    """Per-creator media storage quota (freemium tier based)."""

    __tablename__ = "media_quotas"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    creator_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("creators.id"), unique=True, nullable=False)
    tier: Mapped[str] = db.Column(db.String(20), default="free")  # free, basic, premium
    max_bytes: Mapped[int] = db.Column(db.BigInteger, default=524288000)  # 500 MB default (free)
    used_bytes: Mapped[int] = db.Column(db.BigInteger, default=0)
    updated_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = db.relationship("Creator", backref=db.backref("media_quota", uselist=False))

    @property
    def remaining_bytes(self) -> int:
        return max(0, self.max_bytes - self.used_bytes)

    @property
    def is_exceeded(self) -> bool:
        return self.used_bytes >= self.max_bytes

    def can_upload(self, size_bytes: int) -> bool:
        return self.used_bytes + size_bytes <= self.max_bytes


class Household(db.Model):  # type: ignore[misc,name-defined]
    """A household (foyer) for cost sharing, with weighted shares."""

    __tablename__ = "households"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    name: Mapped[str] = db.Column(db.String(100), nullable=False)  # "Famille Dupont"
    num_adults: Mapped[int] = db.Column(db.Integer, nullable=False, default=1)
    num_children: Mapped[int] = db.Column(db.Integer, nullable=False, default=0)
    adult_weight: Mapped[float] = db.Column(db.Float, nullable=False, default=1.0)  # parts per adult
    child_weight: Mapped[float] = db.Column(db.Float, nullable=False, default=0.5)  # parts per child
    created_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)

    event_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False, index=True)
    guest_id: Mapped[str | None] = db.Column(db.String(32), db.ForeignKey("guests.id"), nullable=True)

    event = db.relationship("Event", backref=db.backref("households", lazy="dynamic", cascade="all, delete-orphan"))
    guest = db.relationship("Guest", backref=db.backref("household", lazy=True))

    @property
    def total_weight(self) -> float:
        """Total weighted share for this household."""
        return self.num_adults * self.adult_weight + self.num_children * self.child_weight

    @property
    def total_people(self) -> int:
        return self.num_adults + self.num_children


class Expense(db.Model):  # type: ignore[misc,name-defined]
    """An expense (frais) shared among households."""

    __tablename__ = "expenses"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    description: Mapped[str] = db.Column(db.String(300), nullable=False)
    amount_cents: Mapped[int] = db.Column(db.Integer, nullable=False)  # in cents to avoid float issues
    currency: Mapped[str] = db.Column(db.String(3), default="EUR")  # ISO 4217
    exchange_rate: Mapped[float] = db.Column(db.Float, default=1.0)  # rate to base currency
    paid_by_household_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("households.id"), nullable=False)
    date: Mapped[date | None] = db.Column(db.Date, nullable=True)
    category: Mapped[str] = db.Column(db.String(50), default="general")  # food, transport, lodging, activities, other
    # When False, the expense is personal (not included in cost sharing).
    is_shared: Mapped[bool] = db.Column(db.Boolean, default=True, nullable=False)
    receipt_media_id: Mapped[str | None] = db.Column(db.String(32), db.ForeignKey("media_items.id"), nullable=True)
    # Custom split override: JSON {household_id: weight, ...}
    custom_split: Mapped[str | None] = db.Column(db.Text, nullable=True)
    created_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)
    created_by: Mapped[str | None] = db.Column(db.String(32), db.ForeignKey("guests.id"), default=None)

    event_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False, index=True)

    event = db.relationship("Event", backref=db.backref("expenses", lazy="dynamic", cascade="all, delete-orphan"))
    paid_by = db.relationship("Household", foreign_keys=[paid_by_household_id])
    receipt = db.relationship("MediaItem", foreign_keys=[receipt_media_id])

    @property
    def amount(self) -> float:
        """Amount in base currency (float for display)."""
        return self.amount_cents / 100.0 * self.exchange_rate

    @property
    def amount_original(self) -> float:
        """Amount in original currency."""
        return self.amount_cents / 100.0

    def get_split_weights(self, households: list[Household]) -> dict[str, float]:
        """Return {household_id: weight} for this expense.
        Uses custom_split if set, otherwise household total_weight."""
        import json
        if self.custom_split:
            try:
                return cast("dict[str, float]", json.loads(self.custom_split))
            except (json.JSONDecodeError, TypeError):
                pass
        return {h.id: h.total_weight for h in households}


class Transfer(db.Model):  # type: ignore[misc,name-defined]
    """A transfer/repayment between households (not an expense)."""

    __tablename__ = "transfers"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    from_household_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("households.id"), nullable=False)
    to_household_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("households.id"), nullable=False)
    amount_cents: Mapped[int] = db.Column(db.Integer, nullable=False)
    currency: Mapped[str] = db.Column(db.String(3), default="EUR")
    exchange_rate: Mapped[float] = db.Column(db.Float, default=1.0)
    note: Mapped[str] = db.Column(db.String(300), default="")
    date: Mapped[date | None] = db.Column(db.Date, nullable=True)
    created_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)
    created_by: Mapped[str | None] = db.Column(db.String(32), db.ForeignKey("guests.id"), default=None)

    event_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False, index=True)

    event = db.relationship("Event", backref=db.backref("transfers", lazy="dynamic", cascade="all, delete-orphan"))
    from_household = db.relationship("Household", foreign_keys=[from_household_id])
    to_household = db.relationship("Household", foreign_keys=[to_household_id])

    @property
    def amount(self) -> float:
        return self.amount_cents / 100.0 * self.exchange_rate


class PaymentRequest(db.Model):  # type: ignore[misc,name-defined]
    """A payment request (reminder) from one household to another."""

    __tablename__ = "payment_requests"

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    from_household_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("households.id"), nullable=False)
    to_household_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("households.id"), nullable=False)
    amount_cents: Mapped[int] = db.Column(db.Integer, nullable=False)
    message: Mapped[str] = db.Column(db.String(500), default="")
    is_resolved: Mapped[bool] = db.Column(db.Boolean, default=False)
    resolved_at: Mapped[datetime | None] = db.Column(db.DateTime, nullable=True)
    created_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)
    created_by: Mapped[str | None] = db.Column(db.String(32), db.ForeignKey("guests.id"), default=None)

    event_id: Mapped[str] = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False, index=True)

    event = db.relationship("Event", backref=db.backref("payment_requests", lazy="dynamic", cascade="all, delete-orphan"))
    from_household = db.relationship("Household", foreign_keys=[from_household_id])
    to_household = db.relationship("Household", foreign_keys=[to_household_id])

    @property
    def amount(self) -> float:
        """Amount in the base currency (float for display)."""
        return self.amount_cents / 100.0


class PushSubscription(db.Model):  # type: ignore[misc,name-defined]
    """Abonnement Web Push d'un appareil pour un participant d'un événement (B027).

    Un navigateur renvoie le même ``endpoint`` pour tous les événements de l'origine : l'unicité
    est donc (événement, endpoint). Les préférences sont par appareil.
    """

    __tablename__ = "push_subscriptions"
    __table_args__ = (db.UniqueConstraint("event_id", "endpoint", name="uq_push_event_endpoint"),)

    id: Mapped[str] = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    guest_id: Mapped[str] = db.Column(
        db.String(32), db.ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[str] = db.Column(
        db.String(32), db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint: Mapped[str] = db.Column(db.String(2048), nullable=False)
    p256dh: Mapped[str] = db.Column(db.String(128), nullable=False)
    auth: Mapped[str] = db.Column(db.String(64), nullable=False)
    user_agent: Mapped[str] = db.Column(db.String(200), nullable=False, default="")
    lang: Mapped[str] = db.Column(db.String(5), nullable=False, default="fr", server_default="fr")
    created_at: Mapped[datetime] = db.Column(db.DateTime, default=datetime.utcnow)
    last_success_at: Mapped[datetime | None] = db.Column(db.DateTime, nullable=True)
    notify_chat: Mapped[bool] = db.Column(db.Boolean, nullable=False, default=True)
    notify_polls: Mapped[bool] = db.Column(db.Boolean, nullable=False, default=True)
    notify_requests: Mapped[bool] = db.Column(db.Boolean, nullable=False, default=True)
    show_preview: Mapped[bool] = db.Column(db.Boolean, nullable=False, default=True)

    guest = db.relationship(
        "Guest",
        backref=db.backref("push_subscriptions", lazy="dynamic", cascade="all, delete-orphan"),
    )
    event = db.relationship(
        "Event",
        backref=db.backref("push_subscriptions", lazy="dynamic", cascade="all, delete-orphan"),
    )
