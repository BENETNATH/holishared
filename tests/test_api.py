"""Tests B034 — API REST + découvrabilité (spec ``specs/b034-api-spec.md`` §9.2).

TDD : écrits avant le code. Les imports des modules nouveaux (``ApiKey``,
``create_api_key``) sont faits dans les tests pour que la collecte reste
possible à l'état rouge.
"""

import secrets
from datetime import date, datetime

from app.models import (
    Activity,
    ActivityRSVP,
    ChatMessage,
    Event,
    Expense,
    Household,
    ListItem,
    LogisticsItem,
    Meal,
    Poll,
    PollOption,
    PollVote,
    SharedList,
    generate_event_code,
)


def make_key(db, event, *, guest=None, creator=None, label=""):
    """Crée une clé via ``create_api_key`` ; renvoie ``(api_key, key)``."""
    from app.apikeys import create_api_key

    return create_api_key(event, guest=guest, creator=creator, label=label)


def auth(key):
    return {"Authorization": f"Bearer {key}"}


def _fake_key():
    """Clé bien formée mais inconnue de la base."""
    return "hs_" + secrets.token_hex(24)


class TestDiscoverability:
    def test_health_no_auth(self, client):
        """§5.3 : GET /api/health sans clé → 200 {"ok": true, "version": "0.1.0"}."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True, "version": "0.1.0"}

    def test_index_lists_all_endpoints(self, client, event, creator, db):
        """§5.1 : l'index liste chaque endpoint v1 (méthode + chemin), généré depuis les routeurs."""
        _, key = make_key(db, event, creator=creator)
        resp = client.get(f"/api/events/{event.code}/index", headers=auth(key))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["event"] == event.code
        assert "auth" in data
        endpoints = data["endpoints"]
        assert isinstance(endpoints, list)
        assert endpoints
        for ep in endpoints:
            assert "method" in ep
            assert "path" in ep
        paths = {(ep["method"], ep["path"]) for ep in endpoints}
        expected = {
            ("GET", "/api/events/<code>"),
            ("GET", "/api/events/<code>/activities"),
            ("POST", "/api/events/<code>/activities"),
            ("GET", "/api/events/<code>/meals"),
            ("POST", "/api/events/<code>/meals"),
            ("GET", "/api/events/<code>/lists"),
            ("POST", "/api/events/<code>/lists"),
            ("GET", "/api/events/<code>/logistics"),
            ("POST", "/api/events/<code>/logistics"),
            ("GET", "/api/events/<code>/polls"),
            ("POST", "/api/events/<code>/polls"),
            ("GET", "/api/events/<code>/chat"),
            ("POST", "/api/events/<code>/chat"),
            ("GET", "/api/events/<code>/costs"),
            ("POST", "/api/events/<code>/costs/expenses"),
            ("POST", "/api/events/<code>/costs/households"),
            ("POST", "/api/events/<code>/costs/transfers"),
            ("POST", "/api/events/<code>/costs/payment-requests"),
        }
        assert expected <= paths
        # Endpoints « item » (avec variable de route) : présents par préfixe.
        all_paths = [ep["path"] for ep in endpoints]
        assert any("/rsvp" in p for p in all_paths)
        assert any("/items" in p for p in all_paths)
        assert any("/vote" in p for p in all_paths)

    def test_index_requires_auth(self, client, event):
        """§5.1 : GET /index sans clé → 401."""
        resp = client.get(f"/api/events/{event.code}/index")
        assert resp.status_code == 401

    def test_event_info_includes_api_field(self, client, event, creator, db):
        """§5.2 : GET /api/events/<code> → infos événement + champ api (auth + index + endpoints)."""
        _, key = make_key(db, event, creator=creator)
        resp = client.get(f"/api/events/{event.code}", headers=auth(key))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["code"] == event.code
        assert data["title"] == event.title
        assert "start_date" in data
        assert "participants" in data
        api = data["api"]
        assert "auth" in api
        assert "index" in api
        assert "endpoints" in api


class TestAuth:
    def test_auth_no_header_is_401(self, client, event):
        """§6.2.1 : sans Authorization → 401."""
        resp = client.get(f"/api/events/{event.code}")
        assert resp.status_code == 401

    def test_auth_malformed_header_is_401(self, client, event):
        """§6.2.1 : « Bearer » vide / « Token hs_… » → 401."""
        resp = client.get(f"/api/events/{event.code}", headers={"Authorization": "Bearer"})
        assert resp.status_code == 401
        resp = client.get(
            f"/api/events/{event.code}", headers={"Authorization": f"Token {_fake_key()}"}
        )
        assert resp.status_code == 401

    def test_auth_invalid_key_is_401(self, client, event):
        """§6.2.3 : clé inconnue (hs_ + 48 hex) → 401."""
        resp = client.get(f"/api/events/{event.code}", headers=auth(_fake_key()))
        assert resp.status_code == 401

    def test_auth_revoked_key_is_401(self, client, event, creator, db):
        """§6.2.4 : clé révoquée → 401."""
        api_key, key = make_key(db, event, creator=creator)
        api_key.revoked_at = datetime.utcnow()
        db.session.commit()
        resp = client.get(f"/api/events/{event.code}", headers=auth(key))
        assert resp.status_code == 401

    def test_auth_unknown_event_is_404(self, client, event, creator, db):
        """§6.2.5/6 : clé valide mais <code> inconnu → 404."""
        _, key = make_key(db, event, creator=creator)
        resp = client.get("/api/events/xxxxxx", headers=auth(key))
        assert resp.status_code == 404

    def test_auth_cross_event_is_404_no_leak(self, client, event, creator, db):
        """§6.2.6/S2 : clé de l'événement A sur B → 404 ; aucune donnée de B."""
        e2 = Event(
            code=generate_event_code(),
            title="Autre Événement",
            start_date=date(2026, 12, 1),
            end_date=date(2026, 12, 7),
            creator_id=creator.id,
            verified_at=datetime.utcnow(),
        )
        db.session.add(e2)
        db.session.commit()
        _, key = make_key(db, event, creator=creator)
        resp = client.get(f"/api/events/{e2.code}", headers=auth(key))
        assert resp.status_code == 404
        assert e2.title not in resp.get_data(as_text=True)

    def test_orphan_key_event_deleted_is_401_not_500(self, client, event, creator, db):
        """§6.2.5/S5 : événement supprimé → ancienne clé → 401 (jamais 500)."""
        _, key = make_key(db, event, creator=creator)
        db.session.delete(event)
        db.session.commit()
        resp = client.get(f"/api/events/{event.code}", headers=auth(key))
        assert resp.status_code == 401

    def test_orphan_key_guest_deleted_is_401_not_500(self, creator_client, client, event, guest, db):
        """§6.2.7/S5 : retrait d'un invité → sa clé → 401 (jamais 500) ; clés supprimées (§3.4)."""
        from app.models import ApiKey

        _, key = make_key(db, event, guest=guest)
        # Retrait via l'UI : _remove_participant supprime les clés de l'invité.
        creator_client.post(f"/e/{event.code}/members", data={"action": "remove", "guest_id": guest.id})
        assert ApiKey.query.filter_by(owner_guest_id=guest.id).count() == 0
        resp = client.get(f"/api/events/{event.code}", headers=auth(key))
        assert resp.status_code == 401


class TestRights:
    def test_guest_cannot_add_household_is_403(self, client, event, guest, db):
        """§6.3/§6.4.8 : clé invité → POST costs/households → 403."""
        _, key = make_key(db, event, guest=guest)
        resp = client.post(
            f"/api/events/{event.code}/costs/households",
            headers=auth(key),
            json={"name": "Famille X", "num_adults": 2},
        )
        assert resp.status_code == 403

    def test_creator_can_add_household(self, client, event, creator, db):
        """§6.3/§6.4.8 : clé créateur → POST costs/households → 201."""
        _, key = make_key(db, event, creator=creator)
        resp = client.post(
            f"/api/events/{event.code}/costs/households",
            headers=auth(key),
            json={"name": "Famille X", "num_adults": 2},
        )
        assert resp.status_code == 201
        assert Household.query.filter_by(name="Famille X").first() is not None

    def test_guest_cannot_delete_list_is_403(self, client, event, guest, db):
        """§6.3 : clé invité ne peut pas supprimer une liste (droit créateur) → 403."""
        lst = SharedList(title="Ma liste", event_id=event.id)
        db.session.add(lst)
        db.session.commit()
        _, key = make_key(db, event, guest=guest)
        resp = client.delete(f"/api/events/{event.code}/lists/{lst.id}", headers=auth(key))
        assert resp.status_code == 403

    def test_creator_can_delete_list(self, client, event, creator, db):
        """§6.3 : clé créateur → suppression liste → 200."""
        lst = SharedList(title="Ma liste", event_id=event.id)
        db.session.add(lst)
        db.session.commit()
        _, key = make_key(db, event, creator=creator)
        resp = client.delete(f"/api/events/{event.code}/lists/{lst.id}", headers=auth(key))
        assert resp.status_code == 200
        assert SharedList.query.get(lst.id) is None


class TestCRUD:
    def test_activities_create_valid(self, client, event, creator, db):
        """§6.4.2 : POST activities (valide) → 201 ; l'activité existe en base."""
        _, key = make_key(db, event, creator=creator)
        resp = client.post(
            f"/api/events/{event.code}/activities",
            headers=auth(key),
            json={"title": "Natation", "date": "2026-12-02"},
        )
        assert resp.status_code == 201
        assert Activity.query.filter_by(title="Natation", event_id=event.id).first() is not None

    def test_activities_create_invalid(self, client, event, creator, db):
        """§6.4.2 : title trop court / date hors période → 400 {"error": …} ; rien en base."""
        _, key = make_key(db, event, creator=creator)
        resp = client.post(
            f"/api/events/{event.code}/activities",
            headers=auth(key),
            json={"title": "N", "date": "2026-12-02"},
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()
        resp = client.post(
            f"/api/events/{event.code}/activities",
            headers=auth(key),
            json={"title": "Natation", "date": "2027-01-01"},
        )
        assert resp.status_code == 400
        assert Activity.query.filter_by(event_id=event.id).count() == 0

    def test_rsvp_valid(self, client, event, creator, db):
        """§6.4.2 : POST rsvp status=yes → 200 ; RSVP créé."""
        _, key = make_key(db, event, creator=creator)
        resp = client.post(
            f"/api/events/{event.code}/activities",
            headers=auth(key),
            json={"title": "Natation", "date": "2026-12-02"},
        )
        assert resp.status_code == 201
        activity_id = resp.get_json()["id"]
        resp = client.post(
            f"/api/events/{event.code}/activities/{activity_id}/rsvp",
            headers=auth(key),
            json={"status": "yes"},
        )
        assert resp.status_code == 200
        rsvp = ActivityRSVP.query.filter_by(activity_id=activity_id).first()
        assert rsvp is not None
        assert rsvp.status == "yes"

    def test_meals_create_valid(self, client, event, creator, db):
        """§6.4.3 : POST meals (valide) → 201."""
        _, key = make_key(db, event, creator=creator)
        resp = client.post(
            f"/api/events/{event.code}/meals",
            headers=auth(key),
            json={"title": "Déjeuner", "date": "2026-12-02", "slot": "lunch"},
        )
        assert resp.status_code == 201
        assert Meal.query.filter_by(title="Déjeuner", event_id=event.id).first() is not None

    def test_meals_create_invalid(self, client, event, creator, db):
        """§6.4.3 : slot invalide / case pleine → 400."""
        _, key = make_key(db, event, creator=creator)
        resp = client.post(
            f"/api/events/{event.code}/meals",
            headers=auth(key),
            json={"title": "Déjeuner", "date": "2026-12-02", "slot": "brunch"},
        )
        assert resp.status_code == 400
        # Case pleine : 6 repas maximum par (date, créneau).
        for i in range(6):
            client.post(
                f"/api/events/{event.code}/meals",
                headers=auth(key),
                json={"title": f"Repas {i}", "date": "2026-12-03", "slot": "dinner"},
            )
        resp = client.post(
            f"/api/events/{event.code}/meals",
            headers=auth(key),
            json={"title": "Repas 6", "date": "2026-12-03", "slot": "dinner"},
        )
        assert resp.status_code == 400

    def test_lists_create_valid(self, client, event, creator, db):
        """§6.4.4 : POST lists (valide) → 201."""
        _, key = make_key(db, event, creator=creator)
        resp = client.post(
            f"/api/events/{event.code}/lists", headers=auth(key), json={"title": "Courses"}
        )
        assert resp.status_code == 201
        assert SharedList.query.filter_by(title="Courses", event_id=event.id).first() is not None

    def test_lists_create_invalid(self, client, event, creator, db):
        """§6.4.4 : title absent → 400 ; rien en base."""
        _, key = make_key(db, event, creator=creator)
        resp = client.post(f"/api/events/{event.code}/lists", headers=auth(key), json={})
        assert resp.status_code == 400
        assert SharedList.query.filter_by(event_id=event.id).count() == 0

    def test_list_items_create_valid(self, client, event, creator, db):
        """§6.4.4 : POST lists/<id>/items (valide) → 201."""
        _, key = make_key(db, event, creator=creator)
        resp = client.post(
            f"/api/events/{event.code}/lists", headers=auth(key), json={"title": "Courses"}
        )
        assert resp.status_code == 201
        list_id = resp.get_json()["id"]
        resp = client.post(
            f"/api/events/{event.code}/lists/{list_id}/items",
            headers=auth(key),
            json={"name": "Pain"},
        )
        assert resp.status_code == 201
        assert ListItem.query.filter_by(name="Pain").first() is not None

    def test_chat_send_valid(self, client, event, creator, db):
        """§6.4.7 : POST chat (valide) → 201 ; message en base."""
        _, key = make_key(db, event, creator=creator)
        resp = client.post(
            f"/api/events/{event.code}/chat", headers=auth(key), json={"content": "Bonjour"}
        )
        assert resp.status_code == 201
        assert ChatMessage.query.filter_by(content="Bonjour", event_id=event.id).first() is not None

    def test_chat_send_invalid(self, client, event, creator, db):
        """§6.4.7 : content vide / > 2000 → 400 ; rien en base."""
        _, key = make_key(db, event, creator=creator)
        resp = client.post(
            f"/api/events/{event.code}/chat", headers=auth(key), json={"content": "  "}
        )
        assert resp.status_code == 400
        resp = client.post(
            f"/api/events/{event.code}/chat", headers=auth(key), json={"content": "x" * 2001}
        )
        assert resp.status_code == 400
        assert ChatMessage.query.filter_by(event_id=event.id).count() == 0

    def test_polls_create_valid(self, client, event, creator, db):
        """§6.4.6 : POST polls (free, 2 options) → 201."""
        _, key = make_key(db, event, creator=creator)
        resp = client.post(
            f"/api/events/{event.code}/polls",
            headers=auth(key),
            json={"question": "Quel film ?", "kind": "free", "options": "Inception\nInterstellar"},
        )
        assert resp.status_code == 201
        assert Poll.query.filter_by(question="Quel film ?", event_id=event.id).first() is not None

    def test_vote_valid(self, client, event, creator, db):
        """§6.4.6 : POST polls/<id>/vote option_id valide → 200 ; vote créé."""
        _, key = make_key(db, event, creator=creator)
        resp = client.post(
            f"/api/events/{event.code}/polls",
            headers=auth(key),
            json={"question": "Quel film ?", "kind": "free", "options": "Inception\nInterstellar"},
        )
        assert resp.status_code == 201
        poll_id = resp.get_json()["id"]
        option = PollOption.query.filter_by(poll_id=poll_id).first()
        assert option is not None
        resp = client.post(
            f"/api/events/{event.code}/polls/{poll_id}/vote",
            headers=auth(key),
            json={"option_id": option.id},
        )
        assert resp.status_code == 200
        assert PollVote.query.filter_by(option_id=option.id).first() is not None

    def test_logistics_create_valid(self, client, event, creator, db):
        """§6.4.5 : POST logistics (valide) → 201."""
        _, key = make_key(db, event, creator=creator)
        resp = client.post(
            f"/api/events/{event.code}/logistics",
            headers=auth(key),
            json={"title": "Adresse", "content": "123 rue des Lilas"},
        )
        assert resp.status_code == 201
        assert LogisticsItem.query.filter_by(title="Adresse", event_id=event.id).first() is not None

    def test_costs_expense_create_valid(self, client, event, creator, creator_guest, db):
        """§6.4.8 : POST costs/expenses (valide) → 201."""
        _, key = make_key(db, event, creator=creator)
        h = Household(name="Famille A", event_id=event.id, guest_id=creator_guest.id)
        db.session.add(h)
        db.session.commit()
        resp = client.post(
            f"/api/events/{event.code}/costs/expenses",
            headers=auth(key),
            json={"description": "Loyer", "amount": "100.00", "household_id": h.id},
        )
        assert resp.status_code == 201
        assert Expense.query.filter_by(description="Loyer", event_id=event.id).first() is not None

    def test_costs_expense_create_invalid(self, client, event, creator, db):
        """§6.4.8 : amount invalide / foyer absent → 400 ; rien en base."""
        _, key = make_key(db, event, creator=creator)
        h = Household(name="Famille A", event_id=event.id)
        db.session.add(h)
        db.session.commit()
        resp = client.post(
            f"/api/events/{event.code}/costs/expenses",
            headers=auth(key),
            json={"description": "Loyer", "amount": "-5", "household_id": h.id},
        )
        assert resp.status_code == 400
        resp = client.post(
            f"/api/events/{event.code}/costs/expenses",
            headers=auth(key),
            json={"description": "Loyer", "amount": "100"},
        )
        assert resp.status_code == 400
        assert Expense.query.filter_by(event_id=event.id).count() == 0


class TestRateLimit:
    def test_api_rate_limit_429_after_60(self, client, event, creator, db):
        """§7 : 61 requêtes GET avec la même clé → 60 fois 200 puis 429 (JSON)."""
        _, key = make_key(db, event, creator=creator)
        codes = [
            client.get(f"/api/events/{event.code}", headers=auth(key)).status_code
            for _ in range(61)
        ]
        assert codes[:60] == [200] * 60
        assert codes[60] == 429
        assert "error" in client.get(
            f"/api/events/{event.code}", headers=auth(key)
        ).get_json()

    def test_api_rate_limit_per_key(self, client, event, creator, db):
        """§7/A10 : deux clés distinctes ont chacune leur budget."""
        _, key1 = make_key(db, event, creator=creator, label="k1")
        _, key2 = make_key(db, event, creator=creator, label="k2")
        for _ in range(60):
            client.get(f"/api/events/{event.code}", headers=auth(key1))
        assert client.get(f"/api/events/{event.code}", headers=auth(key1)).status_code == 429
        assert client.get(f"/api/events/{event.code}", headers=auth(key2)).status_code == 200

    def test_api_rate_limit_invalid_key_per_ip(self, client, event, db):
        """F2 : 61 requêtes à clé invalide depuis la même IP : 60 fois 401 puis 429 (JSON)."""
        bad = {"Authorization": "Bearer hs_invalid"}
        codes = [
            client.get(f"/api/events/{event.code}", headers=bad).status_code
            for _ in range(61)
        ]
        assert codes[:60] == [401] * 60
        assert codes[60] == 429
        assert "error" in client.get(
            f"/api/events/{event.code}", headers=bad
        ).get_json()


class TestSecurity:
    def test_api_responses_are_json_no_html(self, client, event, creator, db):
        """§8/S1 : Content-Type application/json sur succès ET erreur ; pas de HTML."""
        _, key = make_key(db, event, creator=creator)
        resp = client.get(f"/api/events/{event.code}", headers=auth(key))
        assert resp.status_code == 200
        assert resp.content_type.startswith("application/json")
        assert b"<html" not in resp.data.lower()
        assert b"<!doctype" not in resp.data.lower()
        resp = client.get(f"/api/events/{event.code}")
        assert resp.status_code == 401
        assert resp.content_type.startswith("application/json")
        assert b"<html" not in resp.data.lower()
        assert b"<!doctype" not in resp.data.lower()

    def test_api_error_shape(self, client, event):
        """§6.6 : toute erreur est {"error": "…"} (clé error présente, string)."""
        resp = client.get(f"/api/events/{event.code}")
        assert resp.status_code == 401
        data = resp.get_json()
        assert "error" in data
        assert isinstance(data["error"], str)

    def test_api_no_cross_event_leak(self, client, event, creator, db):
        """§8/S2 : clé A ne lit rien de B (GET collection)."""
        e2 = Event(
            code=generate_event_code(),
            title="Événement Secret",
            start_date=date(2026, 12, 1),
            end_date=date(2026, 12, 7),
            creator_id=creator.id,
            verified_at=datetime.utcnow(),
        )
        db.session.add(e2)
        db.session.commit()
        _, key = make_key(db, event, creator=creator)
        resp = client.get(f"/api/events/{e2.code}/activities", headers=auth(key))
        assert resp.status_code == 404
        assert "Événement Secret" not in resp.get_data(as_text=True)
