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
        assert "/mycode" in resp.headers["Location"]

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
        assert "/mycode" in resp.headers["Location"]

    def test_delete_forbidden_for_other_guest(self, client, event, guest, db):
        other = _make_item(db, event, guest)
        # A different guest (not the uploader, not creator) cannot delete
        g2 = Guest(code="zzzz9999", display_name="Autre", event_id=event.id)
        db.session.add(g2)
        db.session.commit()
        _login_guest(client, event, g2)
        resp = client.post(f"/e/{event.code}/media/{other.id}/delete")
        assert resp.status_code == 403  # refus rendu par le gabarit 403, média conservé
        db.session.refresh(other)
        assert other.id is not None


def _expense_with_receipt(db, event, item):
    from app.models import Expense, Household

    household = Household(name="Foyer", event_id=event.id)
    db.session.add(household)
    db.session.flush()
    expense = Expense(
        description="Courses",
        amount_cents=1000,
        paid_by_household_id=household.id,
        receipt_media_id=item.id,
        event_id=event.id,
    )
    db.session.add(expense)
    db.session.commit()
    return expense


def test_delete_media_referenced_by_expense_receipt_returns_302(creator_client, db, event):
    item = _make_item(db, event)
    _expense_with_receipt(db, event, item)
    resp = creator_client.post(f"/e/{event.code}/media/{item.id}/delete")
    assert resp.status_code == 302


def test_delete_media_referenced_by_expense_receipt_nulls_the_reference(creator_client, db, event):
    item = _make_item(db, event)
    expense = _expense_with_receipt(db, event, item)
    creator_client.post(f"/e/{event.code}/media/{item.id}/delete")
    db.session.refresh(expense)
    assert expense.receipt_media_id is None


def test_delete_media_removes_row_and_file_after_commit(creator_client, app, db, event):
    from pathlib import Path

    item = _make_item(db, event)
    folder = Path(app.instance_path) / "media" / event.code
    folder.mkdir(parents=True, exist_ok=True)
    (folder / item.filename).write_bytes(b"x")
    creator_client.post(f"/e/{event.code}/media/{item.id}/delete")
    assert (MediaItem.query.count(), (folder / item.filename).exists()) == (0, False)


def test_failed_media_delete_keeps_file_and_quota(
    creator_client, creator_guest, app, db, event, monkeypatch
):
    from pathlib import Path

    from app.freemium import get_media_quota

    item = _make_item(db, event)
    quota = get_media_quota(event.creator)
    quota.used_bytes = 1000
    db.session.commit()
    folder = Path(app.instance_path) / "media" / event.code
    folder.mkdir(parents=True, exist_ok=True)
    (folder / item.filename).write_bytes(b"x")

    def boom():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db.session, "commit", boom)
    creator_client.post(f"/e/{event.code}/media/{item.id}/delete")
    monkeypatch.undo()
    db.session.rollback()
    db.session.refresh(quota)
    assert ((folder / item.filename).exists(), quota.used_bytes) == (True, 1000)
