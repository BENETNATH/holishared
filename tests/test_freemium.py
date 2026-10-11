"""Tests for freemium limits."""

from datetime import date

from app.models import Event, Guest, generate_event_code, generate_guest_code


class TestGuestLimit:
    def test_can_add_guest_under_limit(self, db, event):
        from app.freemium import can_add_guest

        assert can_add_guest(event) is True

    def test_cannot_add_guest_at_limit(self, db, event, app):
        from app.freemium import can_add_guest

        app.config["MAX_GUESTS_PER_EVENT"] = 2
        for _ in range(2):
            g = Guest(code=generate_guest_code(), display_name="X", event_id=event.id)
            db.session.add(g)
        db.session.commit()
        assert can_add_guest(event) is False


class TestEventLimit:
    def test_can_create_event_under_limit(self, db, creator, app):
        from app.freemium import can_create_event

        assert can_create_event(creator) is True

    def test_cannot_create_event_at_limit(self, db, creator, app):
        from app.freemium import can_create_event

        app.config["MAX_EVENTS_PER_CREATOR"] = 1
        e = Event(
            code=generate_event_code(),
            title="E1",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
            creator_id=creator.id,
        )
        db.session.add(e)
        db.session.commit()
        assert can_create_event(creator) is False


class TestTiers:
    def test_default_tier_is_free(self, db, creator):
        from app.freemium import get_tier

        assert get_tier(creator) == "free"
        # A creator with no tier attribute at all defaults to free.
        assert get_tier(None) == "free"

    def test_set_tier(self, db, creator):
        from app.freemium import get_tier

        creator.tier = "pro"
        db.session.commit()
        assert get_tier(creator) == "pro"

    def test_invalid_tier_falls_back_to_free(self, db, creator):
        from app.freemium import get_tier

        creator.tier = "bogus"
        db.session.commit()
        assert get_tier(creator) == "free"


class TestHasFeature:
    def test_free_has_no_paid_features(self, db, creator):
        from app.freemium import has_feature

        assert has_feature(creator, "pdf_export") is False
        assert has_feature(creator, "unlimited_guests") is False
        assert has_feature(creator, "hd_video") is False

    def test_pro_unlocks_pro_features(self, db, creator):
        from app.freemium import has_feature

        creator.tier = "pro"
        db.session.commit()
        assert has_feature(creator, "pdf_export") is True
        assert has_feature(creator, "unlimited_guests") is True
        assert has_feature(creator, "hd_video") is False

    def test_unlimited_unlocks_everything(self, db, creator):
        from app.freemium import has_feature

        creator.tier = "unlimited"
        db.session.commit()
        assert has_feature(creator, "pdf_export") is True
        assert has_feature(creator, "unlimited_guests") is True
        assert has_feature(creator, "hd_video") is True

    def test_unknown_feature_is_free(self, db, creator):
        from app.freemium import has_feature

        assert has_feature(creator, "no_such_feature") is True


class TestRequireTier:
    def _login(self, client, creator):
        with client.session_transaction() as sess:
            sess["_user_id"] = creator.id
            sess["_fresh"] = True

    def test_free_creator_gets_paywall(self, client, db, creator, event):
        creator.tier = "free"
        db.session.commit()
        self._login(client, creator)
        resp = client.get(f"/e/{event.code}/export/pdf")
        assert resp.status_code == 200  # soft paywall, not a raw 403/400
        html = resp.data.decode()
        assert "Vacances+" in html
        assert "Export PDF" in html

    def test_pro_creator_gets_pdf_view(self, client, db, creator, event):
        creator.tier = "pro"
        db.session.commit()
        self._login(client, creator)
        resp = client.get(f"/e/{event.code}/export/pdf")
        assert resp.status_code == 200
        html = resp.data.decode()
        # Success view, not the paywall.
        assert "paywall-card" in html
        assert "Générer le PDF" in html

    def test_guest_is_not_redirected_to_paywall(self, client, db, creator, event, guest):
        # A non-creator guest hitting the gated route is NOT shown the paywall:
        # login_required (outermost) redirects them to login before the paywall.
        with client.session_transaction() as sess:
            sess[f"guest_{event.code}"] = guest.id
        resp = client.get(f"/e/{event.code}/export/pdf", follow_redirects=False)
        assert resp.status_code == 302
        assert "Vacances+" not in resp.data.decode()
