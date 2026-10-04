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

    def test_join_success(self, client, event):
        resp = client.post(f"/e/{event.code}/join", data={
            "display_name": "Alice",
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_join_too_short_name(self, client, event):
        resp = client.post(f"/e/{event.code}/join", data={
            "display_name": "A",
        }, follow_redirects=True)
        assert b"requis" in resp.data.lower() or b"2 caract" in resp.data
