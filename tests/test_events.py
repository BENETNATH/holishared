"""Tests for events blueprint."""


class TestEventCreation:
    def test_create_page_renders(self, client, creator):
        with client.session_transaction() as sess:
            sess["_user_id"] = creator.id
        resp = client.get("/e/new")
        assert resp.status_code == 200

    def test_create_event_success(self, client, creator):
        with client.session_transaction() as sess:
            sess["_user_id"] = creator.id
        resp = client.post("/e/new", data={
            "title": "Weekend",
            "description": "Fun",
            "start_date": "2026-12-01",
            "end_date": "2026-12-03",
            "location": "Lyon",
            "email": "creator@test.com",
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_create_event_missing_title(self, client, creator):
        with client.session_transaction() as sess:
            sess["_user_id"] = creator.id
        resp = client.post("/e/new", data={
            "title": "",
            "start_date": "2026-12-01",
            "end_date": "2026-12-03",
            "email": "creator@test.com",
        }, follow_redirects=True)
        assert b"Titre" in resp.data


class TestGuestAccess:
    def test_join_page_renders(self, client, event):
        resp = client.get(f"/e/{event.code}/join")
        assert resp.status_code == 200

    def test_join_success_with_own_code(self, client, event, db):
        """The guest chooses their own personal code (no flash)."""
        resp = client.post(f"/e/{event.code}/join", data={
            "display_name": "Alice",
            "code": "alice42",
        }, follow_redirects=True)
        assert resp.status_code == 200
        from app.models import Guest
        g = Guest.query.filter_by(event_id=event.id, code="alice42").first()
        assert g is not None
        # The code is shown on the dashboard, not flashed.
        assert b"alice42" in resp.data

    def test_join_missing_code(self, client, event):
        resp = client.post(f"/e/{event.code}/join", data={
            "display_name": "Alice",
        }, follow_redirects=True)
        assert b"code perso" in resp.data.lower()

    def test_join_code_too_short(self, client, event):
        resp = client.post(f"/e/{event.code}/join", data={
            "display_name": "Alice",
            "code": "ab",
        }, follow_redirects=True)
        assert b"4" in resp.data and b"8" in resp.data

    def test_join_code_bad_chars(self, client, event):
        resp = client.post(f"/e/{event.code}/join", data={
            "display_name": "Alice",
            "code": "ALICE!",
        }, follow_redirects=True)
        assert b"minuscules" in resp.data.lower()

    def test_join_duplicate_code(self, client, event, guest):
        resp = client.post(f"/e/{event.code}/join", data={
            "display_name": "Bob",
            "code": guest.code,
        }, follow_redirects=True)
        assert b"d\xc3\xa9j\xc3\xa0 pris" in resp.data

    def test_join_too_short_name(self, client, event):
        resp = client.post(f"/e/{event.code}/join", data={
            "display_name": "A",
            "code": "alice42",
        }, follow_redirects=True)
        assert b"requis" in resp.data.lower() or b"2 caract" in resp.data


class TestMyCode:
    def test_my_code_page_renders(self, client, event):
        resp = client.get(f"/e/{event.code}/mycode")
        assert resp.status_code == 200

    def test_my_code_access(self, client, event, guest):
        resp = client.post(f"/e/{event.code}/mycode", data={
            "guest_code": guest.code,
        }, follow_redirects=True)
        assert resp.status_code == 200
        # Dashboard shows the guest's own code.
        assert guest.code.encode() in resp.data

    def test_my_code_invalid(self, client, event):
        resp = client.post(f"/e/{event.code}/mycode", data={
            "guest_code": "zzzz9999",
        }, follow_redirects=True)
        assert b"Code invalide" in resp.data

    def test_dashboard_redirects_to_my_code(self, client, event):
        """Unauthenticated visitors are sent to the code-entry page."""
        resp = client.get(f"/e/{event.code}")
        assert resp.status_code == 302
        assert "/mycode" in resp.headers["Location"]


class TestInviteEmail:
    def _login(self, client, creator):
        with client.session_transaction() as sess:
            sess["_user_id"] = creator.id

    def test_invite_page_lists_guests(self, client, event, creator, guest):
        self._login(client, creator)
        resp = client.get(f"/e/{event.code}/invite")
        assert resp.status_code == 200
        assert guest.display_name.encode() in resp.data

    def test_invite_email_sends(self, client, event, creator, monkeypatch):
        self._login(client, creator)
        sent = {}

        def fake_send(ev, email, display_name=None):
            sent["email"] = email

        monkeypatch.setattr("app.events._send_guest_invite_email", fake_send)
        resp = client.post(f"/e/{event.code}/invite/email", data={
            "email": "friend@test.com",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert sent.get("email") == "friend@test.com"
        assert b"Invitation envoy" in resp.data

    def test_invite_email_rejects_disposable(self, client, event, creator, monkeypatch):
        self._login(client, creator)
        def boom(*a, **k):
            raise AssertionError("should not send")
        monkeypatch.setattr("app.events._send_guest_invite_email", boom)
        resp = client.post(f"/e/{event.code}/invite/email", data={
            "email": "x@mailinator.com",
        }, follow_redirects=True)
        assert b"jetable" in resp.data.lower()

    def test_invite_resend_to_existing_guest(self, client, event, creator, guest, monkeypatch):
        self._login(client, creator)
        guest.email = "member@test.com"
        from app.extensions import db
        db.session.commit()
        sent = {}
        monkeypatch.setattr(
            "app.events._send_guest_invite_email",
            lambda ev, email, display_name=None: sent.update(email=email),
        )
        resp = client.post(f"/e/{event.code}/invite/resend/{guest.id}", follow_redirects=True)
        assert resp.status_code == 200
        assert sent.get("email") == "member@test.com"


class TestInviteQr:
    def test_qr_returns_png(self, client, event):
        resp = client.get(f"/e/{event.code}/invite/qr")
        assert resp.status_code == 200
        assert resp.content_type == "image/png"
        # PNG magic bytes.
        assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_invite_page_shows_qr(self, client, event, creator):
        with client.session_transaction() as sess:
            sess["_user_id"] = creator.id
        resp = client.get(f"/e/{event.code}/invite")
        assert resp.status_code == 200
        assert b"invite/qr" in resp.data


class TestI18n:
    def test_default_locale_is_french(self, client, event):
        resp = client.get(f"/e/{event.code}/join")
        assert b"Rejoindre" in resp.data

    def test_en_locale_translates(self, client, event):
        resp = client.get(f"/e/{event.code}/join?lang=en")
        assert b"Join" in resp.data
        assert b"Your personal code" in resp.data
        # The French source string should not appear in the EN render.
        assert b"Rejoindre" not in resp.data

    def test_en_nav_translated(self, client, event, creator):
        with client.session_transaction() as sess:
            sess["_user_id"] = creator.id
        resp = client.get(f"/e/{event.code}?lang=en")
        assert b"My events" in resp.data or b"Schedule" in resp.data

    def test_lang_persists_in_session(self, client, event):
        """Switching to EN via ?lang=en persists across navigation."""
        client.get(f"/e/{event.code}/join?lang=en")
        # A subsequent request without ?lang= stays in EN.
        resp = client.get(f"/e/{event.code}/mycode")
        assert b"Your code" in resp.data
        assert b"Votre code" not in resp.data
