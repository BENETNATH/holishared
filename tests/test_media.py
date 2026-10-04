"""Tests for media blueprint — access control + gallery."""

from app.models import Guest, MediaItem


def _login_creator(client, creator):
    with client.session_transaction() as sess:
        sess["_user_id"] = creator.id
        sess["_fresh"] = True


def _login_guest(client, event, guest):
    with client.session_transaction() as sess:
        sess[f"guest_{event.code}"] = guest.id


def _make_item(db, event, guest=None):
    item = MediaItem(
        filename="abc.jpg",
        original_name="photo.jpg",
        mime_type="image/jpeg",
        size_bytes=1000,
        caption="Test",
        uploaded_by=guest.id if guest else None,
        uploaded_by_name=guest.display_name if guest else "Créateur",
        event_id=event.id,
    )
    db.session.add(item)
    db.session.commit()
    return item


class TestMediaAccess:
    def test_gallery_redirects_no_access(self, client, event):
        resp = client.get(f"/e/{event.code}/media")
        assert resp.status_code == 302
        assert "/join" in resp.headers["Location"] or "/mycode" in resp.headers["Location"]

    def test_gallery_renders_for_guest(self, client, event, guest, db):
        _make_item(db, event, guest)
        _login_guest(client, event, guest)
        resp = client.get(f"/e/{event.code}/media")
        assert resp.status_code == 200
        assert b"Media" in resp.data

    def test_gallery_renders_for_creator(self, client, creator, event, db):
        _make_item(db, event)
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/media")
        assert resp.status_code == 200

    def test_gallery_404_invalid_code(self, client, creator):
        _login_creator(client, creator)
        resp = client.get("/e/xxxxxx/media")
        assert resp.status_code == 404

    def test_upload_requires_access(self, client, event):
        resp = client.post(
            f"/e/{event.code}/media/upload",
            data={"file": (b"", "x.jpg")},
            content_type="multipart/form-data",
        )
        # No access -> redirected to join, not processed
        assert resp.status_code == 302
        assert "/join" in resp.headers["Location"] or "/mycode" in resp.headers["Location"]

    def test_delete_forbidden_for_other_guest(self, client, event, guest, db):
        other = _make_item(db, event, guest)
        # A different guest (not the uploader, not creator) cannot delete
        g2 = Guest(code="zzzz9999", display_name="Autre", event_id=event.id)
        db.session.add(g2)
        db.session.commit()
        _login_guest(client, event, g2)
        resp = client.post(f"/e/{event.code}/media/{other.id}/delete")
        assert resp.status_code == 302  # redirected back with flash, not deleted
        db.session.refresh(other)
        assert other.id is not None
