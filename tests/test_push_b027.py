"""B027 — Notifications Web Push : abonnements, envoi, déclencheurs (aucun envoi réseau)."""

import base64
import json
import os
import types

import manage
import pytest
from cryptography.hazmat.primitives import serialization
from sqlalchemy import create_engine, text

from app import push, tasks
from app.models import Household, PaymentRequest, PushSubscription


@pytest.fixture(autouse=True)
def _no_real_database(app, monkeypatch):
    """Le worker lit DATABASE_URL, le .env peut fournir des clés : rien de réel dans les tests."""
    for name in ("DATABASE_URL", "VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_CLAIMS_SUBJECT"):
        monkeypatch.delenv(name, raising=False)
        app.config[name] = ""


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def keys():
    return {"p256dh": b64(b"\x04" + os.urandom(64)), "auth": b64(os.urandom(16))}


def body(endpoint="https://push.example.com/a", **extra):
    return {"endpoint": endpoint, "keys": keys(), "lang": "fr", **extra}


def post(client, event, route, data):
    return client.post(f"/e/{event.code}/push/{route}", json=data)


def make_sub(db, event, guest, endpoint="https://push.example.com/x", **kw):
    sub = PushSubscription(
        event_id=event.id, guest_id=guest.id, endpoint=endpoint, p256dh="k", auth="a", **kw
    )
    db.session.add(sub)
    db.session.commit()
    return sub


@pytest.fixture
def as_guest(client, event, guest):
    with client.session_transaction() as s:
        s[f"guest_{event.code}"] = guest.id
    return client


@pytest.fixture
def queued(app, monkeypatch):
    """VAPID configuré, file RQ simulée : liste des (fonction, args) mis en file."""
    app.config["VAPID_PUBLIC_KEY"] = "pub"
    app.config["VAPID_PRIVATE_KEY"] = "priv"
    jobs = []

    class FakeQueue:
        def enqueue(self, func, *args, **kwargs):
            jobs.append((func, args))

    monkeypatch.setattr(push, "_queue", lambda: FakeQueue())
    return jobs


def payloads(jobs):
    return [json.loads(args[1]) for _func, args in jobs]


# --- Abonnement ------------------------------------------------------------------------


def test_subscribe_valid_body_creates_subscription(as_guest, event, guest):
    resp = post(as_guest, event, "subscribe", body())
    assert (resp.status_code, PushSubscription.query.filter_by(guest_id=guest.id).count()) == (
        200,
        1,
    )


def test_subscribe_http_endpoint_is_refused(as_guest, event):
    assert post(as_guest, event, "subscribe", body("http://push.example.com/a")).status_code == 400


def test_subscribe_invalid_p256dh_is_refused(as_guest, event):
    data = body()
    data["keys"]["p256dh"] = b64(b"short")
    assert post(as_guest, event, "subscribe", data).status_code == 400


def test_subscribe_invalid_auth_is_refused(as_guest, event):
    data = body()
    data["keys"]["auth"] = "!!!"
    assert post(as_guest, event, "subscribe", data).status_code == 400


def test_subscribe_missing_keys_is_refused(as_guest, event):
    assert (
        post(as_guest, event, "subscribe", {"endpoint": "https://p.example.com/a"}).status_code
        == 400
    )


def test_subscribe_sixth_device_is_refused(as_guest, event):
    for i in range(5):
        post(as_guest, event, "subscribe", body(f"https://p.example.com/{i}"))
    assert post(as_guest, event, "subscribe", body("https://p.example.com/6")).status_code == 409


def test_subscribe_same_endpoint_updates_instead_of_duplicating(as_guest, event):
    post(as_guest, event, "subscribe", body())
    post(as_guest, event, "subscribe", body(notify_chat=False))
    sub = PushSubscription.query.one()
    assert sub.notify_chat is False


def test_subscribe_defaults_enable_everything(as_guest, event):
    post(as_guest, event, "subscribe", body())
    sub = PushSubscription.query.one()
    assert (sub.notify_chat, sub.notify_polls, sub.notify_requests, sub.show_preview) == (True,) * 4


def test_subscribe_english_browser_language_is_stored(as_guest, event):
    data = body()
    data["lang"] = "en-US"
    post(as_guest, event, "subscribe", data)
    assert PushSubscription.query.one().lang == "en"


def test_subscribe_unknown_language_falls_back_to_default(as_guest, event):
    data = body()
    data["lang"] = "zz"
    post(as_guest, event, "subscribe", data)
    assert PushSubscription.query.one().lang == "fr"


def test_subscribe_truncates_user_agent(as_guest, event):
    as_guest.post(f"/e/{event.code}/push/subscribe", json=body(), headers={"User-Agent": "u" * 500})
    assert len(PushSubscription.query.one().user_agent) == 200


def test_subscribe_without_participant_session_is_redirected(client, event):
    assert post(client, event, "subscribe", body()).status_code == 302


def test_subscribe_creator_participant_is_accepted(creator_client, event):
    assert post(creator_client, event, "subscribe", body()).status_code == 200


def test_subscribe_requires_csrf_token(app, as_guest, event):
    app.config["WTF_CSRF_ENABLED"] = True
    assert post(as_guest, event, "subscribe", body()).status_code == 400


def test_unsubscribe_removes_own_subscription(db, as_guest, event, guest):
    make_sub(db, event, guest)
    post(as_guest, event, "unsubscribe", {"endpoint": "https://push.example.com/x"})
    assert PushSubscription.query.count() == 0


def test_unsubscribe_other_participants_endpoint_keeps_subscription(
    db, as_guest, event, other_guest_c
):
    make_sub(db, event, other_guest_c)
    post(as_guest, event, "unsubscribe", {"endpoint": "https://push.example.com/x"})
    assert PushSubscription.query.count() == 1


def test_unsubscribe_all_removes_every_device_of_the_participant(db, as_guest, event, guest):
    make_sub(db, event, guest, "https://p.example.com/1")
    make_sub(db, event, guest, "https://p.example.com/2")
    post(as_guest, event, "unsubscribe", {"all": True})
    assert PushSubscription.query.count() == 0


def test_unsubscribe_all_keeps_other_participants_subscriptions(db, as_guest, event, other_guest_c):
    make_sub(db, event, other_guest_c)
    post(as_guest, event, "unsubscribe", {"all": True})
    assert PushSubscription.query.count() == 1


def test_prefs_updates_one_preference(db, as_guest, event, guest):
    make_sub(db, event, guest)
    post(
        as_guest, event, "prefs", {"endpoint": "https://push.example.com/x", "notify_polls": False}
    )
    assert PushSubscription.query.one().notify_polls is False


def test_prefs_non_boolean_value_is_refused(db, as_guest, event, guest):
    make_sub(db, event, guest)
    resp = post(
        as_guest, event, "prefs", {"endpoint": "https://push.example.com/x", "notify_chat": "no"}
    )
    assert resp.status_code == 400


def test_prefs_of_other_participant_is_not_found(db, as_guest, event, other_guest_c):
    make_sub(db, event, other_guest_c)
    resp = post(
        as_guest, event, "prefs", {"endpoint": "https://push.example.com/x", "notify_chat": False}
    )
    assert (resp.status_code, PushSubscription.query.one().notify_chat) == (404, True)


def test_status_reports_subscribed_device_preferences(db, as_guest, event, guest):
    make_sub(db, event, guest, show_preview=False)
    data = post(as_guest, event, "status", {"endpoint": "https://push.example.com/x"}).get_json()
    assert data["prefs"]["show_preview"] is False


def test_status_reports_unknown_device_as_not_subscribed(as_guest, event):
    data = post(as_guest, event, "status", {"endpoint": "https://push.example.com/none"}).get_json()
    assert data["subscribed"] is False


# --- Cascade ---------------------------------------------------------------------------


def test_deleting_event_removes_its_subscriptions(db, event, guest):
    make_sub(db, event, guest)
    db.session.delete(event)
    db.session.commit()
    assert PushSubscription.query.count() == 0


def test_removing_participant_deletes_their_subscriptions(db, creator_client, event, guest):
    make_sub(db, event, guest)
    creator_client.post(f"/e/{event.code}/members", data={"action": "remove", "guest_id": guest.id})
    assert PushSubscription.query.count() == 0


def test_removing_participant_keeps_others_subscriptions(
    db, creator_client, event, guest, other_guest_c
):
    make_sub(db, event, other_guest_c)
    creator_client.post(f"/e/{event.code}/members", data={"action": "remove", "guest_id": guest.id})
    assert PushSubscription.query.count() == 1


def test_push_table_migration_creates_missing_table_idempotently(tmp_path):
    from app.migrations import migrate_push

    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    first, second = migrate_push(engine), migrate_push(engine)
    assert (first, second) == (True, False)


# --- Envoi (tâche RQ) ------------------------------------------------------------------


@pytest.fixture
def worker_db(tmp_path):
    url = f"sqlite:///{tmp_path / 'w.db'}"
    engine = create_engine(url)
    PushSubscription.__table__.create(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO push_subscriptions (id, guest_id, event_id, endpoint, p256dh, auth,"
                " user_agent, lang, notify_chat, notify_polls, notify_requests, show_preview)"
                " VALUES ('s1','g','e','https://p.example.com/1','k','a','','fr',1,1,1,1)"
            )
        )
    return url, engine


@pytest.fixture
def fake_webpush(monkeypatch):
    """Remplace ``pywebpush.webpush`` ; ``calls`` liste les envois, ``fail`` l'erreur à lever."""
    import pywebpush

    state = types.SimpleNamespace(calls=[], fail=None)

    class FakeException(pywebpush.WebPushException):
        def __init__(self, status):
            super().__init__("boom", response=types.SimpleNamespace(status_code=status))

    def fake(**kwargs):
        state.calls.append(kwargs)
        if state.fail is not None:
            raise state.fail

    state.exc = FakeException
    monkeypatch.setattr(pywebpush, "webpush", fake)
    return state


SUB = {"id": "s1", "endpoint": "https://p.example.com/1", "p256dh": "k", "auth": "a"}


def vapid_private():
    return manage._generate_vapid_keys()[1]


def count(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM push_subscriptions")).scalar()


def test_send_push_success_returns_sent_and_sends_payload(fake_webpush):
    result = tasks.send_push(SUB, '{"a": 1}', vapid_private(), "mailto:a@b.c")
    assert (result, fake_webpush.calls[0]["data"]) == ("sent", '{"a": 1}')


def test_send_push_success_records_last_success(fake_webpush, worker_db):
    url, engine = worker_db
    tasks.send_push(SUB, "{}", vapid_private(), "mailto:a@b.c", url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT last_success_at FROM push_subscriptions")).scalar()


@pytest.mark.parametrize("status", [404, 410])
def test_send_push_expired_endpoint_deletes_subscription(fake_webpush, worker_db, status):
    url, engine = worker_db
    fake_webpush.fail = fake_webpush.exc(status)
    result = tasks.send_push(SUB, "{}", vapid_private(), "mailto:a@b.c", url)
    assert (result, count(engine)) == ("gone", 0)


def test_send_push_server_error_keeps_subscription(fake_webpush, worker_db):
    url, engine = worker_db
    fake_webpush.fail = fake_webpush.exc(500)
    result = tasks.send_push(SUB, "{}", vapid_private(), "mailto:a@b.c", url)
    assert (result, count(engine)) == ("error", 1)


def test_send_push_unexpected_exception_is_swallowed(fake_webpush):
    fake_webpush.fail = RuntimeError("network")
    assert tasks.send_push(SUB, "{}", vapid_private(), "mailto:a@b.c") == "error"


def test_send_push_without_vapid_key_is_skipped(fake_webpush, monkeypatch):
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    assert (tasks.send_push(SUB, "{}"), fake_webpush.calls) == ("skipped", [])


def test_send_push_reads_vapid_key_from_worker_environment(fake_webpush, monkeypatch):
    monkeypatch.setenv("VAPID_PRIVATE_KEY", vapid_private())
    assert tasks.send_push(SUB, "{}") == "sent"


def test_manage_generated_vapid_key_is_loadable_by_py_vapid():
    from py_vapid import Vapid

    public, private = manage._generate_vapid_keys()
    raw = Vapid.from_string(private).public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    assert b64(raw) == public


# --- Déclencheurs ----------------------------------------------------------------------


def test_chat_message_notifies_other_subscribed_participant(
    db, queued, as_guest, event, creator_guest, guest
):
    make_sub(db, event, creator_guest)
    as_guest.post(f"/e/{event.code}/chat/send", data={"content": "Salut"})
    assert len(queued) == 1


def test_chat_message_never_notifies_its_author(db, queued, as_guest, event, guest):
    make_sub(db, event, guest)
    as_guest.post(f"/e/{event.code}/chat/send", data={"content": "Salut"})
    assert queued == []


def test_chat_message_respects_disabled_chat_preference(db, queued, as_guest, event, creator_guest):
    make_sub(db, event, creator_guest, notify_chat=False)
    as_guest.post(f"/e/{event.code}/chat/send", data={"content": "Salut"})
    assert queued == []


def test_chat_message_skips_removed_participants(db, queued, as_guest, event, other_guest_c):
    make_sub(db, event, other_guest_c)
    other_guest_c.is_active = False
    db.session.commit()
    as_guest.post(f"/e/{event.code}/chat/send", data={"content": "Salut"})
    assert queued == []


def test_chat_payload_has_preview_title_link_and_grouping_tag(
    db, queued, as_guest, event, creator_guest
):
    make_sub(db, event, creator_guest)
    as_guest.post(f"/e/{event.code}/chat/send", data={"content": "Salut"})
    assert payloads(queued)[0] == {
        "title": event.title,
        "body": "Test Guest : Salut",
        "tag": f"chat-{event.code}",
        "url": f"/e/{event.code}/chat",
        "renotify": True,
    }


def test_chat_payload_without_preview_is_generic(db, queued, as_guest, event, creator_guest):
    make_sub(db, event, creator_guest, show_preview=False)
    as_guest.post(f"/e/{event.code}/chat/send", data={"content": "Secret"})
    assert payloads(queued)[0]["body"] == "Nouveau message de Test Guest"


def test_chat_payload_uses_subscriber_language(db, queued, as_guest, event, creator_guest):
    make_sub(db, event, creator_guest, show_preview=False, lang="en")
    as_guest.post(f"/e/{event.code}/chat/send", data={"content": "Secret"})
    assert payloads(queued)[0]["body"] == "New message from Test Guest"


def test_chat_burst_messages_share_the_same_tag(db, queued, as_guest, event, creator_guest):
    make_sub(db, event, creator_guest)
    for text_ in ("un", "deux"):
        as_guest.post(f"/e/{event.code}/chat/send", data={"content": text_})
    assert len({p["tag"] for p in payloads(queued)}) == 1


def test_build_payload_truncates_long_text_to_ninety_characters(app, event):
    sub = PushSubscription(lang="fr", show_preview=True)
    with app.test_request_context():
        payload = push.build_payload(sub, event, "chat", "Ann", "x" * 300, "/u", "t")
    assert payload["body"] == "Ann : " + "x" * 89 + "…"


def test_build_payload_collapses_whitespace_in_preview(app, event):
    sub = PushSubscription(lang="fr", show_preview=True)
    with app.test_request_context():
        payload = push.build_payload(sub, event, "chat", "Ann", "a\n\n  b", "/u", "t")
    assert payload["body"] == "Ann : a b"


def test_poll_creation_notifies_everyone_but_the_author(
    db, queued, creator_client, event, creator_guest, guest
):
    make_sub(db, event, creator_guest, "https://p.example.com/c")
    make_sub(db, event, guest, "https://p.example.com/g")
    creator_client.post(
        f"/e/{event.code}/voting/new", data={"question": "Où dîner ?", "options": "A\nB"}
    )
    assert [p["body"] for p in payloads(queued)] == ["Test Creator a créé un sondage : Où dîner ?"]


def test_poll_payload_links_to_voting_page(db, queued, creator_client, event, guest):
    make_sub(db, event, guest)
    creator_client.post(f"/e/{event.code}/voting/new", data={"question": "Q ?", "options": "A\nB"})
    assert payloads(queued)[0]["url"] == f"/e/{event.code}/voting"


def test_poll_respects_disabled_polls_preference(db, queued, creator_client, event, guest):
    make_sub(db, event, guest, notify_polls=False)
    creator_client.post(f"/e/{event.code}/voting/new", data={"question": "Q ?", "options": "A\nB"})
    assert queued == []


@pytest.fixture
def households(db, event, creator_guest, guest, other_guest_c):
    def mk(name, owner):
        h = Household(name=name, event_id=event.id, guest_id=owner.id if owner else None)
        db.session.add(h)
        db.session.commit()
        return h

    return types.SimpleNamespace(
        alice=mk("Foyer Alice", guest),
        bob=mk("Foyer Bob", other_guest_c),
        orphan=mk("Sans nom", None),
    )


def request_from_alice(as_guest, event, to, amount="1250"):
    return as_guest.post(
        f"/e/{event.code}/costs/payment-requests/new",
        data={"to_household_id": to.id, "amount": amount, "message": "Gîte"},
    )


def test_payment_request_notifies_only_recipient_household_owner(
    db, queued, as_guest, event, guest, other_guest_c, creator_guest, households
):
    make_sub(db, event, other_guest_c, "https://p.example.com/b")
    make_sub(db, event, creator_guest, "https://p.example.com/c")
    request_from_alice(as_guest, event, households.bob)
    assert [a[0]["endpoint"] for _f, a in queued] == ["https://p.example.com/b"]


def test_payment_request_payload_has_no_amount_nor_message(
    db, queued, as_guest, event, other_guest_c, households
):
    make_sub(db, event, other_guest_c)
    request_from_alice(as_guest, event, households.bob)
    assert payloads(queued)[0]["body"] == "Nouvelle demande de paiement de Test Guest"


def test_payment_request_payload_links_to_requests_tab(
    db, queued, as_guest, event, other_guest_c, households
):
    make_sub(db, event, other_guest_c)
    request_from_alice(as_guest, event, households.bob)
    assert payloads(queued)[0]["url"] == f"/e/{event.code}/costs?tab=requests"


def test_payment_request_to_household_without_participant_notifies_nobody(
    db, queued, as_guest, event, creator_guest, households
):
    make_sub(db, event, creator_guest)
    request_from_alice(as_guest, event, households.orphan)
    assert queued == []


def test_payment_request_respects_disabled_requests_preference(
    db, queued, as_guest, event, other_guest_c, households
):
    make_sub(db, event, other_guest_c, notify_requests=False)
    request_from_alice(as_guest, event, households.bob)
    assert queued == []


def test_payment_request_still_created_when_push_is_unavailable(
    db, app, as_guest, event, other_guest_c, households
):
    make_sub(db, event, other_guest_c)
    request_from_alice(as_guest, event, households.bob)
    assert PaymentRequest.query.count() == 1


# --- Dégradation -----------------------------------------------------------------------


def test_chat_without_vapid_keys_succeeds_and_enqueues_nothing(
    db, app, monkeypatch, as_guest, event, creator_guest
):
    make_sub(db, event, creator_guest)
    calls = []
    monkeypatch.setattr(push, "_queue", lambda: calls.append(1))
    resp = as_guest.post(f"/e/{event.code}/chat/send", data={"content": "Salut"})
    assert (resp.status_code, calls) == (302, [])


def test_chat_with_redis_down_still_succeeds(db, app, monkeypatch, as_guest, event, creator_guest):
    app.config["VAPID_PUBLIC_KEY"] = app.config["VAPID_PRIVATE_KEY"] = "k"
    make_sub(db, event, creator_guest)

    def broken():
        raise ConnectionError("redis down")

    monkeypatch.setattr(push, "_queue", broken)
    assert as_guest.post(f"/e/{event.code}/chat/send", data={"content": "Salut"}).status_code == 302


def test_notify_with_redis_down_returns_zero(db, app, monkeypatch, event, guest, creator_guest):
    app.config["VAPID_PUBLIC_KEY"] = app.config["VAPID_PRIVATE_KEY"] = "k"
    make_sub(db, event, creator_guest)
    monkeypatch.setattr(push, "_queue", lambda: (_ for _ in ()).throw(ConnectionError()))
    assert push.notify(event, "chat", guest, "x", "/u", "t") == 0


def test_notify_enqueues_the_send_push_task_without_secrets(
    db, queued, event, guest, creator_guest
):
    make_sub(db, event, creator_guest)
    push.notify(event, "chat", guest, "x", "/u", "t")
    func, args = queued[0]
    assert (func is tasks.send_push, "priv" in json.dumps(args)) == (True, False)


# --- Garde statique : payload sans donnée sensible --------------------------------------


def test_payloads_contain_no_email_nor_amount(app, event, guest):
    guest.email = "alice@example.org"
    sub = PushSubscription(lang="fr", show_preview=True)
    with app.test_request_context():
        built = [
            push.build_payload(sub, event, "requests", guest.display_name, "12,50 EUR", "/u", "t"),
            push.build_payload(sub, event, "chat", guest.display_name, "ok", "/u", "t"),
        ]
    blob = json.dumps(built)
    assert ("@" in blob, "12" in blob) == (False, False)


def test_push_module_never_reads_email_or_amount_fields():
    source = open(push.__file__, encoding="utf-8").read()
    assert [w for w in ("email", "amount") if w in source.replace("jsonify", "")] == []
