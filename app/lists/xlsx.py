"""Import/export XLSX des listes partagées (B035).

Export : une feuille par liste, en-têtes localisés, nom de fichier
``<date ISO>-<nom événement>.xlsx``, dropdowns Assigné à/Fait +
validation numérique Quantité (valeurs issues des items existants). Import :
une feuille visible = une nouvelle liste (feuilles ``README``/``Refs`` et
feuilles cachées ignorées), en-têtes FR/EN insensibles à la casse et aux
accents, limites 500 lignes / 20 feuilles / 2 Mo, transaction.
"""

import io
import re
import unicodedata
from datetime import datetime
from typing import Any, cast

from flask import flash, make_response, redirect, request, url_for
from flask_babel import _
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.datavalidation import DataValidation
from werkzeug.wrappers import Response

from app.context import load_event_context
from app.extensions import db, limiter
from app.lists import _get_list_or_404, lists_bp
from app.models import ListItem, SharedList

MAX_SHEETS = 20
MAX_ROWS_PER_SHEET = 500
MAX_FILE_BYTES = 2 * 1024 * 1024
SHEET_NAME_MAX = 31
REFS_SHEET = "Refs"

_DONE_VALUES = {"oui", "yes", "x", "true", "1"}
_HEADER_MAP = {
    "section": "section",
    "item": "name",
    "quantite": "quantity",
    "quantity": "quantity",
    "assigne a": "assigned_to",
    "assigned to": "assigned_to",
    "fait": "is_done",
    "done": "is_done",
}
_FILENAME_UNSAFE = re.compile(r'[\\/:*?"<>|\n]')


def _norm(value: Any) -> str:
    """Casse-insensible et sans accents (reconnaissance d'en-têtes et de « fait »)."""
    if value is None:
        return ""
    text = str(value).strip().casefold()
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn"
    )


def _text(value: Any) -> str:
    """Valeur cellule en texte (les entiers stockés en flottant perdent leur « .0 »)."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _sheet_name(title: str, used: set[str]) -> str:
    """Titre tronqué à 31 caractères, collisions suffixées -2, -3…"""
    base = title[:SHEET_NAME_MAX]
    name, counter = base, 2
    while name in used:
        suffix = f"-{counter}"
        name = base[: SHEET_NAME_MAX - len(suffix)] + suffix
        counter += 1
    used.add(name)
    return name


def _export_filename(event_title: str, extra: str = "") -> str:
    """Nom de fichier : date ISO + nom d'événement (échappé) [+ titre de liste]."""
    date = datetime.now().date().isoformat()
    base = _FILENAME_UNSAFE.sub("_", event_title).strip() or "evenement"
    name = f"{date}-{base}"
    if extra:
        name += f"-{_FILENAME_UNSAFE.sub('_', extra).strip()}"
    return name[:200] + ".xlsx"


def _distinct(values: list[str]) -> list[str]:
    """Valeurs distinctes non vides, dans l'ordre d'apparition."""
    seen: list[str] = []
    for value in values:
        value = (value or "").strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def _make_refs_sheet(wb: Workbook, users: list[str]):
    """Feuille d'aide cachée (A=users) pour le dropdown Assigné à ; None si vide."""
    if not users:
        return None
    helper = wb.create_sheet(title=REFS_SHEET)
    for i, user in enumerate(users, start=1):
        helper.cell(row=i, column=1, value=user)
    helper.sheet_state = "hidden"
    return helper


def _apply_constraints(ws: Any, users: list[str], last_row: int, refs: Any) -> None:
    """Dropdown Assigné à/Fait + validation numérique Quantité (lignes 2..last_row)."""
    if last_row < 2:
        return
    if users and refs is not None:
        dv = DataValidation(
            type="list", formula1=f"={REFS_SHEET}!$A$1:$A${len(users)}", allow_blank=True
        )
        ws.add_data_validation(dv)
        dv.add(f"D2:D{last_row}")
    dv = DataValidation(type="list", formula1=f'"{_("Oui")},{_("Non")}"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"E2:E{last_row}")
    dv = DataValidation(type="whole", operator="greaterThanOrEqual", formula1="1", allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"C2:C{last_row}")


def _export_rows(shared_list: SharedList) -> list[list[Any]]:
    items = cast(
        "list[ListItem]", cast("Any", shared_list.items).order_by(ListItem.created_at.asc()).all()
    )
    rows: list[list[Any]] = [[_("Section"), _("Item"), _("Quantité"), _("Assigné à"), _("Fait")]]
    for item in items:
        rows.append(
            [
                item.section or "",
                item.name,
                item.quantity or "1",
                item.assigned_to or "",
                _("Oui") if item.is_done else _("Non"),
            ]
        )
    return rows


def _xlsx_response(data: bytes, filename: str) -> Response:
    response = make_response(data)
    response.headers["Content-Type"] = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


def _save_workbook(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _back_to_lists(code: str) -> Response:
    return redirect(url_for("lists.index", code=code))


@lists_bp.route("/e/<code>/lists/export.xlsx")
def export_all(code: str) -> Response:
    """Toutes les listes de l'événement : une feuille par liste."""
    ctx = load_event_context(code)
    items = (
        ListItem.query.join(SharedList, ListItem.list_id == SharedList.id)
        .filter(SharedList.event_id == ctx.event.id)
        .all()
    )
    users = _distinct([item.assigned_to for item in items])
    wb = Workbook()
    wb.remove(wb.active)
    refs = _make_refs_sheet(wb, users)
    used: set[str] = set()
    if refs is not None:
        used.add(REFS_SHEET)
    lists = (
        SharedList.query.filter_by(event_id=ctx.event.id)
        .order_by(SharedList.created_at.asc())
        .all()
    )
    for shared_list in lists:
        ws = wb.create_sheet(title=_sheet_name(shared_list.title, used))
        rows = _export_rows(shared_list)
        for row in rows:
            ws.append(row)
        _apply_constraints(ws, users, len(rows), refs)
    if not lists:
        # Aucune liste : trame vide (en-têtes uniquement) — openpyxl exige ≥1 feuille visible.
        ws = wb.create_sheet(title=_("Liste"))
        ws.append([_("Section"), _("Item"), _("Quantité"), _("Assigné à"), _("Fait")])
        _apply_constraints(ws, [], MAX_ROWS_PER_SHEET, None)
    return _xlsx_response(_save_workbook(wb), _export_filename(ctx.event.title))


@lists_bp.route("/e/<code>/lists/<list_id>/export.xlsx")
def export_one(code: str, list_id: str) -> Response:
    """Une seule liste (1 feuille)."""
    ctx = load_event_context(code)
    shared_list = _get_list_or_404(ctx.event, list_id)
    items = cast("list[ListItem]", cast("Any", shared_list.items).all())
    users = _distinct([item.assigned_to for item in items])
    wb = Workbook()
    wb.remove(wb.active)
    refs = _make_refs_sheet(wb, users)
    used: set[str] = set()
    if refs is not None:
        used.add(REFS_SHEET)
    ws = wb.create_sheet(title=_sheet_name(shared_list.title, used))
    rows = _export_rows(shared_list)
    for row in rows:
        ws.append(row)
    _apply_constraints(ws, users, len(rows), refs)
    return _xlsx_response(_save_workbook(wb), _export_filename(ctx.event.title, shared_list.title))


def _parse_sheet(rows: list[list[Any]]) -> tuple[list[dict[str, Any]], list[int]]:
    """(items, numéros de lignes ignorées) ; lève ValueError si schéma inconnu."""
    if not rows:
        raise ValueError("empty sheet")
    columns = {
        _HEADER_MAP[_norm(cell)]: index
        for index, cell in enumerate(rows[0])
        if _norm(cell) in _HEADER_MAP
    }
    if "name" not in columns:
        raise ValueError("unknown header")
    items: list[dict[str, Any]] = []
    ignored: list[int] = []
    for offset, row in enumerate(rows[1:], start=2):

        def cell(field: str, _row: list[Any] = row) -> Any:
            index = columns.get(field)
            return _row[index] if index is not None and index < len(_row) else None

        name = _text(cell("name"))
        if not name:
            ignored.append(offset)
            continue
        quantity = _text(cell("quantity")) or "1"
        items.append(
            {
                "section": _text(cell("section"))[:100],
                "name": name[:300],
                "quantity": quantity[:50],
                "assigned_to": _text(cell("assigned_to"))[:50],
                "is_done": _norm(cell("is_done")) in _DONE_VALUES,
            }
        )
    return items, ignored


@lists_bp.route("/e/<code>/lists/import", methods=["POST"])
@limiter.limit("200 per hour")
def import_xlsx(code: str) -> Response:
    """Importe un classeur .xlsx : une feuille = une nouvelle liste."""
    ctx = load_event_context(code)
    event = ctx.event
    upload = request.files.get("file")
    if upload is None or upload.filename is None or not upload.filename.lower().endswith(".xlsx"):
        flash(_("Fichier non reconnu : seul le format .xlsx est accepté."))
        return _back_to_lists(code)
    filename = upload.filename
    data = upload.read()
    if len(data) > MAX_FILE_BYTES:
        flash(_("Fichier trop volumineux (2 Mo maximum)."))
        return _back_to_lists(code)
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        flash(_("Fichier non reconnu : seul le format .xlsx est accepté."))
        return _back_to_lists(code)

    sheets = [
        ws
        for ws in workbook.worksheets
        if ws.title not in ("README", REFS_SHEET) and ws.sheet_state == "visible"
    ]
    if not sheets:
        workbook.close()
        flash(_("Aucune liste à importer dans ce fichier."))
        return _back_to_lists(code)
    if len(sheets) > MAX_SHEETS:
        workbook.close()
        flash(_("Classeur trop volumineux : 20 feuilles maximum."))
        return _back_to_lists(code)

    # Lecture complète avant ``close()`` (mode read_only : itération paresseuse).
    sheet_rows = [
        (ws.title, [list(row) for row in ws.iter_rows(values_only=True)]) for ws in sheets
    ]
    workbook.close()

    parsed: list[tuple[str, list[dict[str, Any]], list[int]]] = []
    for title, rows in sheet_rows:
        try:
            items, ignored = _parse_sheet(rows)
        except ValueError:
            flash(
                _(
                    "Format non reconnu : en-têtes attendus Section | Item | Quantité | Assigné à | Fait."
                )
            )
            return _back_to_lists(code)
        if len(items) + len(ignored) > MAX_ROWS_PER_SHEET:
            flash(_("Feuille trop longue : 500 lignes maximum par liste."))
            return _back_to_lists(code)
        title = title.strip()[:200] or _("Liste %(n)d") % {"n": len(parsed) + 1}
        parsed.append((title, items, ignored))

    if len(parsed) == 1:
        title, items, ignored = parsed[0]
        wanted = request.form.get("title", "").strip()[:200]
        if wanted:
            parsed = [(wanted, items, ignored)]
        else:
            stem = filename.rsplit(".", 1)[0].strip()[:200]
            if stem:
                parsed = [(stem, items, ignored)]

    for title, items, _ignored in parsed:
        shared_list = SharedList(title=title, list_type="general", event_id=event.id)
        db.session.add(shared_list)
        db.session.flush()
        for item in items:
            db.session.add(ListItem(list_id=shared_list.id, **item))
    db.session.commit()

    total_items = sum(len(items) for _t, items, _i in parsed)
    all_ignored = [n for _t, _i_items, ignored in parsed for n in ignored]
    message = _("Import terminé : %(lists)s liste(s), %(items)s item(s).") % {
        "lists": len(parsed),
        "items": total_items,
    }
    if all_ignored:
        message += " " + _("Lignes ignorées : %(rows)s.") % {
            "rows": ", ".join(str(n) for n in all_ignored)
        }
    flash(message)
    return _back_to_lists(code)
