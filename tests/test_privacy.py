"""Privacy (Lot 4) tests: export ZIP + delete event + access control."""

import io
import json
import zipfile
from datetime import date


def _login_creator(client, creator):
    with client.session_transaction() as sess:
        sess["_user_id"] = creator.id
        sess["_fresh"] = True


def _login_guest(client, event, guest):
    with client.session_transaction() as sess:
        sess[f"guest_{event.code}"] = guest.id


def _read_zip(resp) -> dict:
    """Parse a ZIP response body: {name: bytes}."""
    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    return {name: zf.read(name) for name in zf.namelist()}


class TestExportEvent:
    def test_creator_export_returns_zip(self, client, creator, event, db):
        from app.models import Activity

        _login_creator(client, creator)
        db.session.add(Activity(title="Rando", date=date(2026, 12, 3), event_id=event.id))
        db.session.commit()
        resp = client.get(f"/e/{event.code}/export")
        assert resp.status_code == 200
        assert resp.content_type == "application/zip"
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        names = _read_zip(resp).keys()
        assert "evenement.json" in names

    def test_export_json_content(self, client, creator, event, guest, db):
        from app.models import Activity

        _login_creator(client, creator)
        db.session.add(Activity(title="Rando", date=date(2026, 12, 3), event_id=event.id))
        db.session.commit()
        resp = client.get(f"/e/{event.code}/export")
        data = json.loads(_read_zip(resp)["evenement.json"])
        assert data["titre"] == event.title
        assert any(a["titre"] == "Rando" for a in data["activites"])
        # The guest (Test Guest) is listed by name.
        assert any(g["nom"] == "Test Guest" for g in data["invites"])

    def test_export_includes_media_files(self, client, creator, event, db, app):
        from pathlib import Path

        from app.models import MediaItem

        _login_creator(client, creator)
        media_dir = Path(app.instance_path) / "media" / event.code
        media_dir.mkdir(parents=True, exist_ok=True)
        stored = "abc123.jpg"
        (media_dir / stored).write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
        item = MediaItem(
            filename=stored,
            original_name="photo-vacances.jpg",
            mime_type="image/jpeg",
            size_bytes=16,
            event_id=event.id,
        )
        db.session.add(item)
        db.session.commit()
        resp = client.get(f"/e/{event.code}/export")
        files = _read_zip(resp)
        assert f"medias/{item.original_name}" in files
        assert files[f"medias/{item.original_name}"] == b"\xff\xd8\xff\xe0fakejpeg"

    def test_guest_cannot_export_403(self, client, creator, event, guest):
        _login_guest(client, event, guest)
        resp = client.get(f"/e/{event.code}/export")
        assert resp.status_code == 403


class TestDeleteEvent:
    def test_creator_delete_removes_event(self, client, creator, event, guest, db):
        from app.models import Activity, Event, Guest

        _login_creator(client, creator)
        db.session.add(Activity(title="Rando", date=date(2026, 12, 3), event_id=event.id))
        db.session.commit()
        event_id = event.id
        guest_id = guest.id
        resp = client.post(f"/e/{event.code}/delete")
        assert resp.status_code == 302
        assert Event.query.get(event_id) is None
        # Cascade: guests + activities removed.
        assert Guest.query.get(guest_id) is None
        assert Activity.query.filter_by(event_id=event_id).count() == 0

    def test_creator_delete_purges_media_dir(self, client, creator, event, db, app):
        from pathlib import Path

        from app.models import MediaItem

        _login_creator(client, creator)
        media_dir = Path(app.instance_path) / "media" / event.code
        media_dir.mkdir(parents=True, exist_ok=True)
        (media_dir / "file1.jpg").write_bytes(b"data")
        db.session.add(MediaItem(
            filename="file1.jpg", mime_type="image/jpeg",
            size_bytes=4, event_id=event.id,
        ))
        db.session.commit()
        assert media_dir.exists()
        client.post(f"/e/{event.code}/delete")
        assert not media_dir.exists()

    def test_guest_cannot_delete_403(self, client, creator, event, guest, db):
        from app.models import Event

        _login_guest(client, event, guest)
        event_id = event.id
        resp = client.post(f"/e/{event.code}/delete")
        assert resp.status_code == 403
        # The event must still exist.
        assert Event.query.get(event_id) is not None

    def test_delete_creates_benevolent_flash_and_logout(self, client, creator, event, db):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/delete", follow_redirects=True)
        assert resp.status_code == 200
        # Creator is logged out after deletion.
        with client.session_transaction() as sess:
            assert "_user_id" not in sess
