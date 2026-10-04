"""Database models for holishared."""

import secrets
import string
from datetime import datetime

from flask_login import UserMixin

from app.extensions import db


def generate_event_code(length=6):
    """Generate a short event code (URL-safe)."""
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_guest_code(length=8):
    """Generate a guest access code."""
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class Creator(UserMixin, db.Model):
    """Event creator (validated by email)."""

    __tablename__ = "creators"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    email = db.Column(db.String(255), unique=True, nullable=False)
    email_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(64), default=lambda: secrets.token_hex(32))
    display_name = db.Column(db.String(100), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    events = db.relationship("Event", backref="creator", lazy="dynamic")

    def get_id(self):
        return self.id


class Event(db.Model):
    """A shared event (vacation, weekend, project)."""

    __tablename__ = "events"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    code = db.Column(db.String(6), unique=True, nullable=False, default=generate_event_code)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    location = db.Column(db.String(300), default="")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator_id = db.Column(db.String(32), db.ForeignKey("creators.id"), nullable=False)

    guests = db.relationship("Guest", backref="event", lazy="dynamic")
    activities = db.relationship(
        "Activity", backref="event", lazy="dynamic", cascade="all, delete-orphan"
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

    @property
    def duration_days(self):
        return (self.end_date - self.start_date).days + 1

    @property
    def guest_count(self):
        return self.guests.count()


class Guest(db.Model):
    """A guest with a personal code (no personal data stored)."""

    __tablename__ = "guests"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    code = db.Column(db.String(8), nullable=False)
    display_name = db.Column(db.String(50), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    event_id = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False)

    # Unique constraint: one code per event
    __table_args__ = (db.UniqueConstraint("event_id", "code", name="uq_guest_event_code"),)

    activity_rsvps = db.relationship("ActivityRSVP", backref="guest", lazy="dynamic")
    poll_votes = db.relationship("PollVote", backref="guest", lazy="dynamic")


class Activity(db.Model):
    """A planned activity."""

    __tablename__ = "activities"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, default=None)
    end_time = db.Column(db.Time, default=None)
    location = db.Column(db.String(300), default="")
    min_headcount = db.Column(db.Integer, default=1)
    bring_items = db.Column(db.Text, default="")  # "who brings what"
    created_by = db.Column(db.String(32), db.ForeignKey("guests.id"), default=None)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    event_id = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False)

    rsvps = db.relationship(
        "ActivityRSVP", backref="activity", lazy="dynamic", cascade="all, delete-orphan"
    )

    @property
    def confirmed_count(self):
        return sum(1 for r in self.rsvps if r.status == "yes")


class ActivityRSVP(db.Model):
    """RSVP for an activity."""

    __tablename__ = "activity_rsvps"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    status = db.Column(db.String(10), nullable=False)  # yes, no, maybe
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    activity_id = db.Column(db.String(32), db.ForeignKey("activities.id"), nullable=False)
    guest_id = db.Column(db.String(32), db.ForeignKey("guests.id"), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("activity_id", "guest_id", name="uq_rsvp_activity_guest"),
    )


class ActivityLog(db.Model):
    """Audit trail of actions on an event (B002)."""

    __tablename__ = "activity_logs"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    actor_name = db.Column(db.String(100), nullable=False)
    actor_type = db.Column(db.String(20), nullable=False)  # creator, guest, system
    action = db.Column(db.String(50), nullable=False)
    target = db.Column(db.String(200), default=None)
    details = db.Column(db.Text, default=None)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    event_id = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False, index=True)


class SharedList(db.Model):
    """A shared list (shopping, packing, etc.)."""

    __tablename__ = "shared_lists"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    title = db.Column(db.String(200), nullable=False)
    list_type = db.Column(db.String(50), default="general")  # shopping, packing, materials, buffet
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    event_id = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False)

    items = db.relationship(
        "ListItem", backref="parent_list", lazy="dynamic", cascade="all, delete-orphan"
    )


class ListItem(db.Model):
    """An item in a shared list."""

    __tablename__ = "list_items"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    name = db.Column(db.String(300), nullable=False)
    quantity = db.Column(db.String(50), default="1")
    assigned_to = db.Column(db.String(50), default="")  # display name of who takes it
    is_done = db.Column(db.Boolean, default=False)
    section = db.Column(db.String(100), default="")  # category within the list
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    list_id = db.Column(db.String(32), db.ForeignKey("shared_lists.id"), nullable=False)


class Poll(db.Model):
    """A poll/vote."""

    __tablename__ = "polls"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    question = db.Column(db.String(300), nullable=False)
    is_closed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    event_id = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False)

    options = db.relationship(
        "PollOption", backref="poll", lazy="dynamic", cascade="all, delete-orphan"
    )


class PollOption(db.Model):
    """An option in a poll."""

    __tablename__ = "poll_options"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    label = db.Column(db.String(200), nullable=False)
    order = db.Column(db.Integer, default=0)

    poll_id = db.Column(db.String(32), db.ForeignKey("polls.id"), nullable=False)

    votes = db.relationship("PollVote", backref="option", lazy="dynamic")


class PollVote(db.Model):
    """A vote on a poll option."""

    __tablename__ = "poll_votes"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    voted_at = db.Column(db.DateTime, default=datetime.utcnow)

    option_id = db.Column(db.String(32), db.ForeignKey("poll_options.id"), nullable=False)
    guest_id = db.Column(db.String(32), db.ForeignKey("guests.id"), nullable=False)

    __table_args__ = (db.UniqueConstraint("option_id", "guest_id", name="uq_vote_option_guest"),)


class LogisticsItem(db.Model):
    """A logistics/practical info item."""

    __tablename__ = "logistics_items"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, default="")
    category = db.Column(db.String(50), default="general")  # address, access, timing, docs, notes
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    event_id = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False)


class MediaItem(db.Model):
    """Shared media (photo/video) with geolocation and dating."""

    __tablename__ = "media_items"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    filename = db.Column(db.String(255), nullable=False)  # stored filename
    original_name = db.Column(db.String(255), default="")  # user's original filename
    mime_type = db.Column(db.String(100), nullable=False)  # image/jpeg, video/mp4, etc.
    size_bytes = db.Column(db.Integer, nullable=False)  # file size in bytes
    caption = db.Column(db.Text, default="")  # optional description

    # Geolocation (WGS84)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    geo_precision = db.Column(db.String(20), default="approximate")  # exact, approximate, city

    # Dating
    taken_at = db.Column(db.DateTime, nullable=True)  # when the photo/video was taken
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)  # when uploaded to the event

    # Author
    uploaded_by = db.Column(db.String(32), db.ForeignKey("guests.id"), nullable=True)
    uploaded_by_name = db.Column(db.String(100), default="Créateur")  # denormalized for display

    event_id = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False, index=True)

    event = db.relationship(
        "Event", backref=db.backref("media", lazy="dynamic", cascade="all, delete-orphan")
    )
    uploader = db.relationship("Guest", foreign_keys=[uploaded_by])

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def display_date(self):
        return self.taken_at or self.uploaded_at


class ChatMessage(db.Model):
    """A chat message on an event (B008)."""

    __tablename__ = "chat_messages"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    guest_id = db.Column(db.String(32), db.ForeignKey("guests.id"), nullable=True)
    author_name = db.Column(db.String(100), nullable=False)
    author_type = db.Column(db.String(20), nullable=False)  # creator, guest

    event_id = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False, index=True)


class MediaQuota(db.Model):
    """Per-creator media storage quota (freemium tier based)."""

    __tablename__ = "media_quotas"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    creator_id = db.Column(db.String(32), db.ForeignKey("creators.id"), unique=True, nullable=False)
    tier = db.Column(db.String(20), default="free")  # free, basic, premium
    max_bytes = db.Column(db.BigInteger, default=524288000)  # 500 MB default (free)
    used_bytes = db.Column(db.BigInteger, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = db.relationship("Creator", backref=db.backref("media_quota", uselist=False))

    @property
    def remaining_bytes(self):
        return max(0, self.max_bytes - self.used_bytes)

    @property
    def is_exceeded(self):
        return self.used_bytes >= self.max_bytes

    def can_upload(self, size_bytes):
        return self.used_bytes + size_bytes <= self.max_bytes


class Household(db.Model):
    """A household (foyer) for cost sharing, with weighted shares."""

    __tablename__ = "households"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    name = db.Column(db.String(100), nullable=False)  # "Famille Dupont"
    num_adults = db.Column(db.Integer, nullable=False, default=1)
    num_children = db.Column(db.Integer, nullable=False, default=0)
    adult_weight = db.Column(db.Float, nullable=False, default=1.0)  # parts per adult
    child_weight = db.Column(db.Float, nullable=False, default=0.5)  # parts per child
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    event_id = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False, index=True)

    event = db.relationship("Event", backref=db.backref("households", lazy="dynamic", cascade="all, delete-orphan"))

    @property
    def total_weight(self):
        """Total weighted share for this household."""
        return self.num_adults * self.adult_weight + self.num_children * self.child_weight

    @property
    def total_people(self):
        return self.num_adults + self.num_children


class Expense(db.Model):
    """An expense (frais) shared among households."""

    __tablename__ = "expenses"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    description = db.Column(db.String(300), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)  # in cents to avoid float issues
    currency = db.Column(db.String(3), default="EUR")  # ISO 4217
    exchange_rate = db.Column(db.Float, default=1.0)  # rate to base currency
    paid_by_household_id = db.Column(db.String(32), db.ForeignKey("households.id"), nullable=False)
    date = db.Column(db.Date, nullable=True)
    category = db.Column(db.String(50), default="general")  # food, transport, lodging, activities, other
    receipt_media_id = db.Column(db.String(32), db.ForeignKey("media_items.id"), nullable=True)
    # Custom split override: JSON {household_id: weight, ...}
    custom_split = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    event_id = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False, index=True)

    event = db.relationship("Event", backref=db.backref("expenses", lazy="dynamic", cascade="all, delete-orphan"))
    paid_by = db.relationship("Household", foreign_keys=[paid_by_household_id])
    receipt = db.relationship("MediaItem", foreign_keys=[receipt_media_id])

    @property
    def amount(self):
        """Amount in base currency (float for display)."""
        return self.amount_cents / 100.0 * self.exchange_rate

    @property
    def amount_original(self):
        """Amount in original currency."""
        return self.amount_cents / 100.0

    def get_split_weights(self, households):
        """Return {household_id: weight} for this expense.
        Uses custom_split if set, otherwise household total_weight."""
        import json
        if self.custom_split:
            try:
                return json.loads(self.custom_split)
            except (json.JSONDecodeError, TypeError):
                pass
        return {h.id: h.total_weight for h in households}


class Transfer(db.Model):
    """A transfer/repayment between households (not an expense)."""

    __tablename__ = "transfers"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    from_household_id = db.Column(db.String(32), db.ForeignKey("households.id"), nullable=False)
    to_household_id = db.Column(db.String(32), db.ForeignKey("households.id"), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), default="EUR")
    exchange_rate = db.Column(db.Float, default=1.0)
    note = db.Column(db.String(300), default="")
    date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    event_id = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False, index=True)

    event = db.relationship("Event", backref=db.backref("transfers", lazy="dynamic", cascade="all, delete-orphan"))
    from_household = db.relationship("Household", foreign_keys=[from_household_id])
    to_household = db.relationship("Household", foreign_keys=[to_household_id])

    @property
    def amount(self):
        return self.amount_cents / 100.0 * self.exchange_rate


class PaymentRequest(db.Model):
    """A payment request (reminder) from one household to another."""

    __tablename__ = "payment_requests"

    id = db.Column(db.String(32), primary_key=True, default=lambda: secrets.token_hex(16))
    from_household_id = db.Column(db.String(32), db.ForeignKey("households.id"), nullable=False)
    to_household_id = db.Column(db.String(32), db.ForeignKey("households.id"), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    message = db.Column(db.String(500), default="")
    is_resolved = db.Column(db.Boolean, default=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    event_id = db.Column(db.String(32), db.ForeignKey("events.id"), nullable=False, index=True)

    event = db.relationship("Event", backref=db.backref("payment_requests", lazy="dynamic", cascade="all, delete-orphan"))
    from_household = db.relationship("Household", foreign_keys=[from_household_id])
    to_household = db.relationship("Household", foreign_keys=[to_household_id])
