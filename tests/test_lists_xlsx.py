"""Tests pour l'import/export XLSX des listes — B035.

TDD : ces tests DOIVENT échouer avant le codage.
Un comportement = un test.
"""

import base64
import io
import secrets
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from app.models import Event, ListItem, SharedList, generate_event_code

FR_HEADERS = ["Section", "Item", "Quantité", "Assigné à", "Fait"]
EN_HEADERS = ["Section", "Item", "Quantity", "Assigned to", "Done"]

ROOT = Path(__file__).resolve().parent.parent


def _workbook_bytes(sheets: dict[str, list[list]]) -> bytes:
    """Un classeur en mémoire : {nom de feuille : lignes}."""
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _read(data: bytes) -> dict[str, list[list]]:
    """{nom de feuille : [[valeurs]]} (cellules vides normalisées en « »)."""
    wb = load_workbook(io.BytesIO(data))
    return {
        ws.title: [
            [("" if cell.value is None else cell.value) for cell in row] for row in ws.iter_rows()
        ]
        for ws in wb.worksheets
    }


@pytest.fixture
def shared_list(db, event):
    sl = SharedList(title="Shopping", list_type="shopping", event_id=event.id)
    db.session.add(sl)
    db.session.commit()
    return sl


@pytest.fixture
def items(db, shared_list):
    """Trois articles, accents et états variés."""
    rows = [
        ("Milk", "2", "Dairy", "Test Guest", True),
        ("Café", "1", "Dairy", "", False),
        ("Pain au chocolat", "4", "Boulangerie", "Other", False),
    ]
    for name, qty, section, assigned, done in rows:
        db.session.add(
            ListItem(
                name=name,
                quantity=qty,
                section=section,
                assigned_to=assigned,
                is_done=done,
                list_id=shared_list.id,
            )
        )
    db.session.commit()


def _login_creator(client, creator):
    with client.session_transaction() as sess:
        sess["_user_id"] = creator.id
        sess["_fresh"] = True


# === Export (6 tests) ===


class TestExportAll:
    def test_returns_xlsx_download_named_after_event(
        self, client, creator, event, shared_list, items
    ):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/lists/export.xlsx")
        assert resp.status_code == 200
        assert "spreadsheetml.sheet" in resp.content_type
        assert f"filename=listes-{event.code}.xlsx" in resp.headers["Content-Disposition"]

    def test_one_sheet_per_list_named_by_title(self, client, creator, event, db, items):
        _login_creator(client, creator)
        db.session.add(SharedList(title="Valise", list_type="packing", event_id=event.id))
        db.session.commit()
        data = _read(client.get(f"/e/{event.code}/lists/export.xlsx").data)
        assert set(data) == {"Shopping", "Valise"}

    def test_rows_and_headers_localized_fr(self, client, creator, event, shared_list, items):
        _login_creator(client, creator)
        data = _read(client.get(f"/e/{event.code}/lists/export.xlsx").data)
        rows = data["Shopping"]
        assert rows[0] == FR_HEADERS
        assert rows[1] == ["Dairy", "Milk", "2", "Test Guest", "Oui"]
        assert rows[2] == ["Dairy", "Café", "1", "", "Non"]

    def test_preserves_accents(self, client, creator, event, shared_list, items):
        _login_creator(client, creator)
        data = _read(client.get(f"/e/{event.code}/lists/export.xlsx").data)
        names = [row[1] for row in data["Shopping"][1:]]
        assert "Café" in names
        assert "Pain au chocolat" in names

    def test_sheet_name_truncated_to_31_and_collisions_suffixed(
        self, client, creator, event, db, items
    ):
        _login_creator(client, creator)
        long_title = "L" * 40
        db.session.add(SharedList(title=long_title, list_type="general", event_id=event.id))
        db.session.add(SharedList(title=long_title, list_type="general", event_id=event.id))
        db.session.commit()
        data = _read(client.get(f"/e/{event.code}/lists/export.xlsx").data)
        names = sorted(data)
        assert all(len(name) <= 31 for name in names)
        truncated = "L" * 29 + "-2"
        assert truncated in names
        assert len(names) == 3  # Shopping + 2 collisions

    def test_headers_localized_en(self, client, creator, event, shared_list, items):
        _login_creator(client, creator)
        data = _read(client.get(f"/e/{event.code}/lists/export.xlsx?lang=en").data)
        assert data["Shopping"][0] == EN_HEADERS
        assert data["Shopping"][1][4] == "Yes"


class TestExportSingle:
    def test_single_list_one_sheet_named_by_title(self, client, creator, event, shared_list, items):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/lists/{shared_list.id}/export.xlsx")
        assert resp.status_code == 200
        assert "filename=Shopping.xlsx" in resp.headers["Content-Disposition"]
        data = _read(resp.data)
        assert set(data) == {"Shopping"}
        assert len(data["Shopping"]) == 4  # en-tête + 3 items

    def test_list_from_another_event_404(self, client, creator, event, db, items):
        _login_creator(client, creator)
        other_event = Event(
            code=generate_event_code(),
            title="Other",
            start_date=event.start_date,
            end_date=event.end_date,
            creator_id=event.creator_id,
            verified_at=event.verified_at,
        )
        db.session.add(other_event)
        db.session.commit()
        other_list = SharedList(title="Autre", list_type="general", event_id=other_event.id)
        db.session.add(other_list)
        db.session.commit()
        resp = client.get(f"/e/{event.code}/lists/{other_list.id}/export.xlsx")
        assert resp.status_code == 404


# === Import (14 tests) ===


class TestImport:
    def test_creates_one_list_per_sheet(self, client, creator, event, db):
        _login_creator(client, creator)
        data = _workbook_bytes(
            {
                "Courses": [FR_HEADERS, ["", "Milk", "2", "", "Non"], ["", "Café", "1", "", "Oui"]],
                "Valise": [FR_HEADERS, ["", "Passport", "1", "", "Non"]],
            }
        )
        resp = client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(data), "import.xlsx")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        lists = {sl.title: sl for sl in SharedList.query.filter_by(event_id=event.id).all()}
        assert set(lists) == {"Courses", "Valise"}
        items = {i.name: i for i in ListItem.query.filter_by(list_id=lists["Courses"].id).all()}
        assert items["Milk"].quantity == "2"
        assert items["Milk"].is_done is False
        assert items["Café"].is_done is True
        assert len(ListItem.query.filter_by(list_id=lists["Valise"].id).all()) == 1

    def test_round_trip_export_then_import(self, client, creator, event, db, shared_list, items):
        _login_creator(client, creator)
        exported = client.get(f"/e/{event.code}/lists/{shared_list.id}/export.xlsx").data
        before = SharedList.query.filter_by(event_id=event.id).count()
        client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(exported), "Shopping.xlsx")},
            content_type="multipart/form-data",
        )
        after = SharedList.query.filter_by(event_id=event.id).all()
        assert len(after) == before + 1
        new_list = next(sl for sl in after if sl.id != shared_list.id)
        original = {i.name: i for i in ListItem.query.filter_by(list_id=shared_list.id).all()}
        copied = {i.name: i for i in ListItem.query.filter_by(list_id=new_list.id).all()}
        assert set(copied) == set(original)
        for name, src in original.items():
            dst = copied[name]
            assert (dst.quantity, dst.section, dst.assigned_to, dst.is_done) == (
                src.quantity,
                src.section,
                src.assigned_to,
                src.is_done,
            )

    def test_recognizes_english_headers(self, client, creator, event, db):
        _login_creator(client, creator)
        data = _workbook_bytes({"L": [EN_HEADERS, ["Snacks", "Chips", "3", "Bob", "yes"]]})
        client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(data), "l.xlsx")},
            content_type="multipart/form-data",
        )
        sl = SharedList.query.filter_by(event_id=event.id).first()
        item = ListItem.query.filter_by(list_id=sl.id).first()
        assert (item.section, item.name, item.quantity, item.assigned_to, item.is_done) == (
            "Snacks",
            "Chips",
            "3",
            "Bob",
            True,
        )

    def test_invalid_rows_ignored_and_reported(self, client, creator, event, db):
        _login_creator(client, creator)
        data = _workbook_bytes(
            {
                "L": [
                    FR_HEADERS,
                    ["", "Milk", "1", "", "Non"],
                    ["", "", "1", "", "Non"],
                    ["", "Egg", "1", "", "Non"],
                ]
            }
        )
        resp = client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(data), "l.xlsx")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        text = resp.get_data(as_text=True)
        sl = SharedList.query.filter_by(event_id=event.id).first()
        assert len(ListItem.query.filter_by(list_id=sl.id).all()) == 2
        assert "Lignes ignorées : 3." in text  # rapport : ligne 3 ignorée

    def test_is_done_multi_locale(self, client, creator, event, db):
        _login_creator(client, creator)
        data = _workbook_bytes(
            {
                "L": [
                    FR_HEADERS,
                    ["", "a", "1", "", "oui"],
                    ["", "b", "1", "", "YES"],
                    ["", "c", "1", "", "x"],
                    ["", "d", "1", "", "true"],
                    ["", "e", "1", "", "1"],
                    ["", "f", "1", "", "non"],
                    ["", "g", "1", "", ""],
                ]
            }
        )
        client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(data), "l.xlsx")},
            content_type="multipart/form-data",
        )
        sl = SharedList.query.filter_by(event_id=event.id).first()
        done = {i.name for i in ListItem.query.filter_by(list_id=sl.id, is_done=True).all()}
        assert done == {"a", "b", "c", "d", "e"}

    def test_quantity_defaults_to_one(self, client, creator, event, db):
        _login_creator(client, creator)
        data = _workbook_bytes({"L": [FR_HEADERS, ["", "Milk", None, "", "Non"]]})
        client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(data), "l.xlsx")},
            content_type="multipart/form-data",
        )
        sl = SharedList.query.filter_by(event_id=event.id).first()
        assert ListItem.query.filter_by(list_id=sl.id).first().quantity == "1"

    def test_numeric_cells_read_as_text(self, client, creator, event, db):
        """Excel stocke « 2 » en flottant : l'import doit lire « 2 », pas « 2.0 »."""
        _login_creator(client, creator)
        data = _workbook_bytes({"L": [FR_HEADERS, ["", "Milk", 2, 3, "Non"]]})
        client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(data), "l.xlsx")},
            content_type="multipart/form-data",
        )
        sl = SharedList.query.filter_by(event_id=event.id).first()
        item = ListItem.query.filter_by(list_id=sl.id).first()
        assert item.quantity == "2"
        assert item.assigned_to == "3"

    def test_readme_sheet_skipped(self, client, creator, event, db):
        _login_creator(client, creator)
        data = _workbook_bytes(
            {
                "README": [["Format : Section | Item | Quantité | Assigné à | Fait"]],
                "Courses": [FR_HEADERS, ["", "Milk", "1", "", "Non"]],
            }
        )
        client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(data), "courses.xlsx")},
            content_type="multipart/form-data",
        )
        lists = SharedList.query.filter_by(event_id=event.id).all()
        assert len(lists) == 1  # la feuille README n'a pas créé de liste
        assert lists[0].title == "courses"  # single-sheet : titre = nom du fichier

    def test_single_sheet_uses_title_field(self, client, creator, event, db):
        _login_creator(client, creator)
        data = _workbook_bytes({"Feuille1": [FR_HEADERS, ["", "Milk", "1", "", "Non"]]})
        client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(data), "l.xlsx"), "title": "Ma liste"},
            content_type="multipart/form-data",
        )
        sl = SharedList.query.filter_by(event_id=event.id).first()
        assert sl.title == "Ma liste"

    def test_single_sheet_defaults_to_filename(self, client, creator, event, db):
        _login_creator(client, creator)
        data = _workbook_bytes({"Feuille1": [FR_HEADERS, ["", "Milk", "1", "", "Non"]]})
        client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(data), "courses-samedi.xlsx")},
            content_type="multipart/form-data",
        )
        sl = SharedList.query.filter_by(event_id=event.id).first()
        assert sl.title == "courses-samedi"

    def test_rejects_more_than_500_rows(self, client, creator, event, db):
        _login_creator(client, creator)
        rows = [FR_HEADERS] + [["", f"item-{i}", "1", "", "Non"] for i in range(501)]
        data = _workbook_bytes({"L": rows})
        resp = client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(data), "l.xlsx")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert SharedList.query.filter_by(event_id=event.id).count() == 0
        assert "500" in resp.get_data(as_text=True)

    def test_rejects_more_than_20_sheets(self, client, creator, event, db):
        _login_creator(client, creator)
        sheets = {f"S{i}": [FR_HEADERS, ["", "x", "1", "", "Non"]] for i in range(21)}
        data = _workbook_bytes(sheets)
        resp = client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(data), "l.xlsx")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert SharedList.query.filter_by(event_id=event.id).count() == 0
        assert "20" in resp.get_data(as_text=True)

    def test_rejects_file_over_2mb(self, client, creator, event, db):
        _login_creator(client, creator)
        # openpyxl limite les cellules à 32 767 caractères : on remplit 100 cellules
        # de base64 aléatoire (haute entropie, peu compressible) pour dépasser 2 Mo.
        big = base64.b64encode(secrets.token_bytes(24_573)).decode()  # 32 764 caractères
        rows = [FR_HEADERS] + [["", big, "1", "", "Non"] for _ in range(100)]
        data = _workbook_bytes({"L": rows})
        assert len(data) > 2 * 1024 * 1024
        resp = client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(data), "l.xlsx")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert SharedList.query.filter_by(event_id=event.id).count() == 0
        assert "2 Mo" in resp.get_data(as_text=True)

    def test_rejects_non_xlsx_extension(self, client, creator, event, db):
        _login_creator(client, creator)
        data = _workbook_bytes({"L": [FR_HEADERS, ["", "Milk", "1", "", "Non"]]})
        resp = client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(data), "l.xls")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert SharedList.query.filter_by(event_id=event.id).count() == 0
        assert ".xlsx" in resp.get_data(as_text=True)

    def test_requires_csrf_token(self, client, app, creator, event):
        _login_creator(client, creator)
        app.config["WTF_CSRF_ENABLED"] = True
        data = _workbook_bytes({"L": [FR_HEADERS, ["", "Milk", "1", "", "Non"]]})
        resp = client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(data), "l.xlsx")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert SharedList.query.filter_by(event_id=event.id).count() == 0


# === Droits (2 tests) ===


class TestAccess:
    def test_export_requires_participant(self, client, event):
        resp = client.get(f"/e/{event.code}/lists/export.xlsx")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(f"/{event.code}/mycode")

    def test_import_requires_participant(self, client, event):
        data = _workbook_bytes({"L": [FR_HEADERS, ["", "Milk", "1", "", "Non"]]})
        resp = client.post(
            f"/e/{event.code}/lists/import",
            data={"file": (io.BytesIO(data), "l.xlsx")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(f"/{event.code}/mycode")


# === i18n (1 test) ===


def test_messages_present_in_both_catalogs():
    """Les nouveaux msgids B035 existent dans les deux .po, traduits en EN."""
    fr = (ROOT / "translations" / "fr" / "LC_MESSAGES" / "messages.po").read_text(encoding="utf-8")
    en = (ROOT / "translations" / "en" / "LC_MESSAGES" / "messages.po").read_text(encoding="utf-8")
    for msgid in (
        "Exporter les listes (XLSX)",
        "Importer une liste (XLSX)",
        "Fichier non reconnu : seul le format .xlsx est accepté.",
        "Import terminé : %(lists)s liste(s), %(items)s item(s).",
        "Lignes ignorées : %(rows)s.",
    ):
        assert f'msgid "{msgid}"' in fr
        assert f'msgid "{msgid}"' in en
        # l'anglais doit être traduit (msgstr non vide)
        block = en.split(f'msgid "{msgid}"')[1].split("\n\n")[0]
        assert 'msgstr ""' not in block
