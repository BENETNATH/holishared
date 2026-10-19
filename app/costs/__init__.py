"""Costs blueprint - cost sharing by household with weighted settlement."""

import json
import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_babel import ngettext
from werkzeug.wrappers import Response

from app.context import EventContext, load_event_context, log_event
from app.extensions import db, limiter
from app.forms import FormErrors
from app.i18n import BASE_CURRENCY, CURRENCIES, currency_label, is_valid
from app.models import Event, Expense, Guest, Household, PaymentRequest, Transfer
from app.push import notify
from app.utils import reassign_work

costs_bp = Blueprint("costs", __name__)

# Icônes SVG du kit (B017) par catégorie de frais.
EXPENSE_CATEGORY_ICONS = {
    "general": "wallet",
    "food": "utensils",
    "transport": "map-pin",
    "lodging": "house",
    "activities": "sparkles",
    "other": "inbox",
}

TABS = ("expenses", "balance", "requests")
MAX_AMOUNT = 1_000_000.0
MAX_RATE = 10000.0
MIN_RATE = 0.0001
DATE_PAST_DAYS = 365 * 5
DATE_FUTURE_DAYS = 366

SHEET_EXPENSE = "costs-expense-sheet"
SHEET_EXPENSE_EDIT = "costs-expense-edit-sheet"
SHEET_HOUSEHOLD = "costs-household-sheet"
SHEET_HOUSEHOLD_EDIT = "costs-household-edit-sheet"
SHEET_RATIO = "costs-ratio-sheet"
SHEET_TRANSFER = "costs-transfer-sheet"
SHEET_REQUEST = "costs-request-sheet"


def _household_in_event(household_id: str, event: Event) -> bool:
    """Check that a household belongs to the given event (prevents cross-tenant refs)."""
    if not household_id:
        return False
    return Household.query.filter_by(id=household_id, event_id=event.id).first() is not None


# fmt: off
def _base_cents(amount_cents: int, exchange_rate: float | None) -> int:
    """Amount converted to base currency, in cents (int)."""
    return round(amount_cents * (exchange_rate or 1.0))


def _per_expense_shares(households: list[Household], expenses: list[Expense]) -> tuple[dict[str, int], dict[str, int]]:
    """Return ({household_id: share_cents}, {household_id: paid_cents}).

    Only shared expenses (is_shared=True) are included; personal expenses are
    excluded from cost sharing entirely.
    """
    ids = {h.id for h in households}
    paid: dict[str, int] = {h.id: 0 for h in households}
    shares: dict[str, int] = {h.id: 0 for h in households}
    for exp in expenses:
        if not exp.is_shared:
            continue
        payer_id = exp.paid_by_household_id
        if payer_id is None or payer_id not in ids:
            continue
        base = _base_cents(exp.amount_cents, exp.exchange_rate)
        paid[payer_id] += base
        weights = exp.get_split_weights(households)
        total_w = sum(weights.get(h.id, 0) for h in households)
        if total_w > 0:
            for h in households:
                shares[h.id] += round(base * weights.get(h.id, 0) / total_w)
    # Rounding fix: shares must sum to the total base amount.
    total_base = sum(
        _base_cents(e.amount_cents, e.exchange_rate)
        for e in expenses
        if e.is_shared and e.paid_by_household_id is not None and e.paid_by_household_id in ids
    )
    diff = total_base - sum(shares.values())
    if diff != 0 and households:
        shares[households[-1].id] += diff
    return shares, paid


def _settlement(households: list[Household], expenses: list[Expense], transfers: list[Transfer]) -> list[tuple[str, str, int]]:
    """Compute who pays whom, in base currency cents.

    Accounts for per-expense custom splits, exchange rates, and transfers
    already made (a transfer from A to B reduces A's outstanding debt).
    Uses the greedy minimum-transactions algorithm.
    """
    if not households:
        return []
    shares, paid = _per_expense_shares(households, expenses)
    balances: dict[str, int] = {h.id: paid[h.id] - shares[h.id] for h in households}
    ids = {h.id for h in households}
    for t in transfers:
        if (t.from_household_id is None or t.to_household_id is None
                or t.from_household_id not in ids or t.to_household_id not in ids):
            continue
        base = _base_cents(t.amount_cents, t.exchange_rate)
        balances[t.from_household_id] += base
        balances[t.to_household_id] -= base

    debtors = sorted([(hid, b) for hid, b in balances.items() if b < 0], key=lambda x: x[1])
    creditors = sorted([(hid, b) for hid, b in balances.items() if b > 0],
                       key=lambda x: x[1], reverse=True)
    settlements: list[tuple[str, str, int]] = []
    di = ci = 0
    while di < len(debtors) and ci < len(creditors):
        d_id, d_bal = debtors[di]
        c_id, c_bal = creditors[ci]
        amount = min(-d_bal, c_bal)
        if amount > 0:
            settlements.append((d_id, c_id, amount))
        debtors[di] = (d_id, d_bal + amount)
        creditors[ci] = (c_id, c_bal - amount)
        if debtors[di][1] == 0:
            di += 1
        if creditors[ci][1] == 0:
            ci += 1
    return settlements
# fmt: on


def _category_breakdown(expenses: list[Expense]) -> list[tuple[str, int]]:
    """Return {category: base_cents} sorted by amount desc."""
    totals: dict[str, int] = {}
    for exp in expenses:
        base = _base_cents(exp.amount_cents, exp.exchange_rate)
        cat = exp.category or "general"
        totals[cat] = totals.get(cat, 0) + base
    return sorted(totals.items(), key=lambda x: x[1], reverse=True)


# === Aides de saisie et de visibilité (B024) ===


def _today() -> date:
    return datetime.now(UTC).date()


def _parse_decimal(raw: str) -> float | None:
    """Nombre décimal fini ("12,50" accepté), sinon None."""
    try:
        value = float(raw.strip().replace(",", ".").replace(" ", ""))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _parse_amount(raw: str, errors: FormErrors) -> int:
    value = _parse_decimal(raw)
    if value is None or value <= 0 or value > MAX_AMOUNT or round(value * 100) < 1:
        errors.add("amount", _("Montant invalide."))
        return 0
    return round(value * 100)


def _parse_date(raw: str, errors: FormErrors) -> date:
    """Date saisie (AAAA-MM-JJ) ; vide = aujourd'hui ; bornée à 5 ans avant / 1 an après."""
    raw = raw.strip()
    today = _today()
    if not raw:
        return today
    try:
        value = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        errors.add("date", _("Date invalide."))
        return today
    if (
        not today - timedelta(days=DATE_PAST_DAYS)
        <= value
        <= today + timedelta(days=DATE_FUTURE_DAYS)
    ):
        errors.add("date", _("Date hors limites (5 ans avant à 1 an après aujourd'hui)."))
        return today
    return value


def _parse_rate(raw: str, currency: str, errors: FormErrors) -> float:
    """Taux vers la devise de base : 1.0 pour la devise de base, obligatoire sinon (0,0001 ≤ taux ≤ 10000)."""
    if currency == BASE_CURRENCY:
        return 1.0
    if not raw.strip():
        errors.add("exchange_rate", _("Taux de change requis pour cette devise."))
        return 1.0
    value = _parse_decimal(raw)
    if value is None or not MIN_RATE <= value <= MAX_RATE:
        errors.add("exchange_rate", _("Taux de change invalide (0,0001 ≤ taux ≤ 10000)."))
        return 1.0
    return value


def _my_household(ctx: EventContext) -> Household | None:
    if ctx.participant is None:
        return None
    mine: Household | None = Household.query.filter_by(
        event_id=ctx.event.id, guest_id=ctx.participant.id
    ).first()
    return mine


def _visible(ctx: EventContext, exp: Expense) -> bool:
    """Une dépense personnelle n'est visible que des membres du foyer payeur (confidentialité)."""
    if exp.is_shared:
        return True
    payer = exp.paid_by
    return (
        ctx.participant is not None
        and payer is not None
        and payer.guest_id is not None
        and payer.guest_id == ctx.participant.id
    )


def _get_expense(ctx: EventContext, exp_id: str) -> Expense:
    """Dépense de l'événement visible du participant ; 404 sinon (n'en révèle pas l'existence)."""
    exp: Expense | None = Expense.query.filter_by(id=exp_id, event_id=ctx.event.id).first()
    if exp is None or not _visible(ctx, exp):
        abort(404)
    return exp


def _tab_of(raw: str | None, default: str = "expenses") -> str:
    return raw if raw in TABS else default


def _back(code: str, default: str = "expenses") -> Response:
    return redirect(
        url_for("costs.index", code=code, tab=_tab_of(request.form.get("tab"), default))
    )


def _split_display(exp: Expense, households: list[Household]) -> list[dict[str, Any]]:
    """Répartition affichée d'une dépense partagée, en devise de base (affichage seulement)."""
    weights = exp.get_split_weights(households)
    total_w = sum(weights.get(h.id, 0) for h in households)
    if total_w <= 0:
        return []
    base = _base_cents(exp.amount_cents, exp.exchange_rate)
    rows = [
        {"household": h, "amount": round(base * weights.get(h.id, 0) / total_w) / 100.0}
        for h in households
        if weights.get(h.id, 0) > 0
    ]
    return rows


def _household_involved(h: Household, ctx: EventContext) -> bool:
    return ctx.participant is not None and h.guest_id == ctx.participant.id


def _page(
    ctx: EventContext,
    *,
    tab: str,
    errors: FormErrors | None = None,
    form_data: dict[str, str] | None = None,
    open_sheet: str | None = None,
    edit_expense: Expense | None = None,
    edit_household: Household | None = None,
) -> str:
    event = ctx.event
    households = event.households.order_by(Household.created_at, Household.id).all()
    h_map = {h.id: h for h in households}
    mine = next((h for h in households if _household_involved(h, ctx)), None)

    all_expenses = event.expenses.order_by(Expense.date.desc(), Expense.created_at.desc()).all()
    expenses = [e for e in all_expenses if _visible(ctx, e)]
    shared_expenses = [e for e in all_expenses if e.is_shared]
    transfers = event.transfers.order_by(Transfer.created_at.desc()).all()
    payment_requests = event.payment_requests.order_by(
        PaymentRequest.is_resolved.asc(), PaymentRequest.created_at.desc()
    ).all()

    settlements = [
        {"from": h_map[f], "to": h_map[t], "amount": a / 100.0}
        for f, t, a in _settlement(households, shared_expenses, transfers)
    ]
    shares, paid = _per_expense_shares(households, shared_expenses)
    h_summary = [
        {
            "household": h,
            "share": shares[h.id] / 100.0,
            "paid": paid[h.id] / 100.0,
            "balance": (paid[h.id] - shares[h.id]) / 100.0,
        }
        for h in households
    ]
    total_expenses = (
        sum(_base_cents(e.amount_cents, e.exchange_rate) for e in shared_expenses) / 100.0
    )
    category_breakdown = [
        {"category": c, "amount": a / 100.0} for c, a in _category_breakdown(shared_expenses)
    ]

    # Dépenses personnelles : seul le total de MON foyer est calculé et affiché.
    personal_total = 0.0
    if mine is not None:
        personal_total = (
            sum(
                _base_cents(e.amount_cents, e.exchange_rate)
                for e in expenses
                if not e.is_shared and e.paid_by_household_id == mine.id
            )
            / 100.0
        )

    my_balance: float | None = None
    i_owe: list[dict[str, Any]] = []
    owed_to_me: list[dict[str, Any]] = []
    if mine is not None:
        my_balance = next((s["balance"] for s in h_summary if s["household"].id == mine.id), None)
        for s in settlements:
            if s["from"].id == mine.id:
                i_owe.append({"to": s["to"], "amount": s["amount"]})
            if s["to"].id == mine.id:
                owed_to_me.append({"from": s["from"], "amount": s["amount"]})

    splits = {e.id: _split_display(e, households) for e in expenses if e.is_shared}
    first = households[0] if households else None

    return render_template(
        "costs/index.html",
        event=event,
        tab=tab,
        households=households,
        expenses=expenses,
        splits=splits,
        transfers=transfers,
        payment_requests=payment_requests,
        settlements=settlements,
        h_summary=h_summary,
        total_expenses=total_expenses,
        category_breakdown=category_breakdown,
        personal_total=personal_total,
        category_icons=EXPENSE_CATEGORY_ICONS,
        default_adult_weight=first.adult_weight if first else 1.0,
        default_child_weight=first.child_weight if first else 0.5,
        my_household=mine,
        my_balance=my_balance,
        i_owe=i_owe,
        owed_to_me=owed_to_me,
        base_currency=BASE_CURRENCY,
        errors=errors or FormErrors(),
        no_errors=FormErrors(),
        form_data=form_data or {},
        open_sheet=open_sheet,
        edit_expense=edit_expense,
        edit_household=edit_household,
        today=_today().isoformat(),
        household_options=[(h.id, h.name) for h in households],
        other_options=[(h.id, h.name) for h in households if mine is None or h.id != mine.id],
        currency_options=[(c, currency_label(c)) for c in CURRENCIES],
    )


def _form_data() -> dict[str, str]:
    return {k: v for k, v in request.form.items() if k != "csrf_token"}


# Segment où vit chaque feuille (les dépenses acceptent aussi le segment courant).
_SHEET_TAB = {
    SHEET_HOUSEHOLD: "balance",
    SHEET_HOUSEHOLD_EDIT: "balance",
    SHEET_RATIO: "balance",
    SHEET_TRANSFER: "balance",
    SHEET_REQUEST: "requests",
}


def _invalid(ctx: EventContext, sheet: str, errors: FormErrors, **extra: Any) -> str | Response:
    if sheet == SHEET_EXPENSE and ctx.event.households.count() == 0:
        # Sans foyer la feuille d'ajout n'existe pas : les erreurs passent par des messages.
        errors.flash_all("danger")
        return _back(ctx.event.code)
    return _page(
        ctx,
        tab=_SHEET_TAB.get(sheet) or _tab_of(request.form.get("tab")),
        errors=errors,
        form_data=_form_data(),
        open_sheet=sheet,
        **extra,
    )


# === Routes ===


@costs_bp.route("/e/<code>/costs")
def index(code: str) -> str | Response | tuple[str, int]:
    """Cost sharing dashboard : segments Dépenses · Équilibre · Demandes."""
    ctx = load_event_context(code)
    tab = _tab_of(request.args.get("tab"))
    edit_expense = edit_household = None
    open_sheet = None
    if request.args.get("edit"):
        exp = Expense.query.filter_by(id=request.args["edit"], event_id=ctx.event.id).first()
        if exp is not None and _visible(ctx, exp) and ctx.can_edit(exp):
            edit_expense, open_sheet, tab = exp, SHEET_EXPENSE_EDIT, "expenses"
    elif request.args.get("edit_household"):
        hh = Household.query.filter_by(
            id=request.args["edit_household"], event_id=ctx.event.id
        ).first()
        if hh is not None and ctx.can_edit(hh):
            edit_household, open_sheet, tab = hh, SHEET_HOUSEHOLD_EDIT, "balance"
    return _page(
        ctx,
        tab=tab,
        open_sheet=open_sheet,
        edit_expense=edit_expense,
        edit_household=edit_household,
    )


def parse_household(form: Any) -> tuple[dict[str, Any], FormErrors]:
    name = form.get("name", "").strip()
    errors = FormErrors()
    if len(name) < 2:
        errors.add("name", _("Nom du foyer requis (min 2 caractères)."))
    elif len(name) > 100:
        errors.add("name", _("Nom trop long (max 100)."))
    values: dict[str, Any] = {"name": name, "num_adults": 1, "num_children": 0}
    try:
        num_adults = int(form.get("num_adults", "1"))
        num_children = int(form.get("num_children", "0"))
    except (ValueError, TypeError):
        errors.add_global(_("Valeurs numériques invalides."))
        return values, errors
    if num_adults < 1 or num_adults > 50:
        errors.add("num_adults", _("Adultes : entre 1 et 50."))
    if num_children < 0 or num_children > 50:
        errors.add("num_children", _("Enfants : entre 0 et 50."))
    values.update(num_adults=num_adults, num_children=num_children)
    return values, errors


def my_household(ctx: EventContext) -> Household | None:
    """Foyer du participant courant (None s'il n'en a pas)."""
    return _my_household(ctx)


def save_my_household(ctx: EventContext, values: dict[str, Any]) -> Household:
    """Met à jour le foyer du participant, ou le crée s'il n'en a pas (propriétaire = participant).

    Appelé après ``parse_household`` sans erreur ; droits B024 : le propriétaire modifie son foyer.
    """
    if ctx.participant is None:
        abort(403)
    hh = _my_household(ctx)
    if hh is None:
        first = Household.query.filter_by(event_id=ctx.event.id).first()
        hh = Household(
            **values,
            adult_weight=first.adult_weight if first else 1.0,
            child_weight=first.child_weight if first else 0.5,
            event_id=ctx.event.id,
            guest_id=ctx.participant.id,
        )
        db.session.add(hh)
        log_event(ctx, "household.created", target=values["name"])
    else:
        if not ctx.can_edit(hh):
            abort(403)
        hh.name = values["name"]
        hh.num_adults = values["num_adults"]
        hh.num_children = values["num_children"]
        log_event(ctx, "household.updated", target=hh.name)
    db.session.commit()
    return hh


@costs_bp.route("/e/<code>/costs/households/new", methods=["GET", "POST"])
def add_household(code: str) -> str | Response | tuple[str, int]:
    """Add a household (creator only)."""
    ctx = load_event_context(code)
    if not ctx.is_creator:
        abort(403)
    if request.method == "GET":
        return redirect(url_for("costs.index", code=code, tab="balance"))

    values, errors = parse_household(request.form)
    if errors:
        return _invalid(ctx, SHEET_HOUSEHOLD, errors)
    first = Household.query.filter_by(event_id=ctx.event.id).first()
    db.session.add(
        Household(
            **values,
            adult_weight=first.adult_weight if first else 1.0,
            child_weight=first.child_weight if first else 0.5,
            event_id=ctx.event.id,
        )
    )
    log_event(ctx, "household.created", target=values["name"])
    db.session.commit()
    flash(_("Foyer ajouté."), "success")
    return _back(code, "balance")


@costs_bp.route("/e/<code>/costs/households/<h_id>/edit", methods=["POST"])
def edit_household(code: str, h_id: str) -> str | Response | tuple[str, int]:
    """Modifier la composition d'un foyer (son propriétaire ou le créateur)."""
    ctx = load_event_context(code)
    hh = Household.query.filter_by(id=h_id, event_id=ctx.event.id).first()
    if hh is None:
        abort(404)
    if not ctx.can_edit(hh):
        abort(403)
    values, errors = parse_household(request.form)
    if errors:
        return _invalid(ctx, SHEET_HOUSEHOLD_EDIT, errors, edit_household=hh)
    hh.name = values["name"]
    hh.num_adults = values["num_adults"]
    hh.num_children = values["num_children"]
    log_event(ctx, "household.updated", target=hh.name)
    db.session.commit()
    flash(_("Foyer modifié."), "success")
    return _back(code, "balance")


def _parse_expense(ctx: EventContext, form: Any) -> tuple[dict[str, Any], FormErrors]:
    description = form.get("description", "").strip()
    category = form.get("category", "general").strip() or "general"
    currency = form.get("currency", BASE_CURRENCY).strip().upper() or BASE_CURRENCY
    household_id = form.get("household_id", "")
    is_shared = form.get("is_shared") == "on"
    errors = FormErrors()
    if not description:
        errors.add("description", _("Description requise."))
    elif len(description) > 300:
        errors.add("description", _("Description trop longue (max 300)."))
    amount_cents = _parse_amount(form.get("amount", ""), errors)
    if currency not in CURRENCIES:
        errors.add("currency", _("Devise invalide."))
        currency = BASE_CURRENCY
    exchange_rate = _parse_rate(form.get("exchange_rate", ""), currency, errors)
    if not (errors.has("amount") or errors.has("exchange_rate")) and (
        _base_cents(amount_cents, exchange_rate) < 1
    ):
        errors.add("amount", _("Montant trop faible une fois converti."))
    if not is_valid("expense_category", category):
        errors.add("category", _("Catégorie invalide."))
    payer: Household | None = None
    if not household_id:
        errors.add("household_id", _("Foyer payeur requis."))
    elif not _household_in_event(household_id, ctx.event):
        errors.add("household_id", _("Foyer payeur invalide."))
    else:
        payer = db.session.get(Household, household_id)
    if payer is not None and not is_shared and not _household_involved(payer, ctx):
        errors.add("is_shared", _("Une dépense personnelle doit être payée par votre foyer."))
    exp_date = _parse_date(form.get("date", ""), errors)
    values = {
        "description": description,
        "amount_cents": amount_cents,
        "currency": currency,
        "exchange_rate": exchange_rate,
        "category": category,
        "paid_by_household_id": household_id,
        "date": exp_date,
        "is_shared": is_shared,
    }
    return values, errors


def _log_expense(ctx: EventContext, action: str, exp: Expense) -> None:
    """Journal visible de tous : une dépense personnelle n'y laisse ni description ni montant."""
    if exp.is_shared:
        log_event(
            ctx,
            action,
            target=exp.description,
            details=f"{exp.amount_cents / 100:.2f} {exp.currency}",
        )
    else:
        log_event(ctx, action)


@costs_bp.route("/e/<code>/costs/expenses/new", methods=["POST"])
@limiter.limit("20 per hour")
def add_expense(code: str) -> str | Response | tuple[str, int]:
    """Add an expense."""
    ctx = load_event_context(code)
    values, errors = _parse_expense(ctx, request.form)
    if errors:
        return _invalid(ctx, SHEET_EXPENSE, errors)
    exp = Expense(
        **values,
        event_id=ctx.event.id,
        created_by=ctx.participant.id if ctx.participant else None,
    )
    db.session.add(exp)
    _log_expense(ctx, "expense.created", exp)
    db.session.commit()
    flash(_("Frais ajouté."), "success")
    return _back(code)


@costs_bp.route("/e/<code>/costs/expenses/<exp_id>/edit", methods=["POST"])
@limiter.limit("60 per hour")
def edit_expense(code: str, exp_id: str) -> str | Response | tuple[str, int]:
    """Modifier une dépense (son auteur, le propriétaire du foyer payeur ou le créateur)."""
    ctx = load_event_context(code)
    exp = _get_expense(ctx, exp_id)
    if not ctx.can_edit(exp):
        abort(403)
    values, errors = _parse_expense(ctx, request.form)
    if errors:
        return _invalid(ctx, SHEET_EXPENSE_EDIT, errors, edit_expense=exp)
    for key, value in values.items():
        setattr(exp, key, value)
    _log_expense(ctx, "expense.updated", exp)
    db.session.commit()
    flash(_("Frais modifié."), "success")
    return _back(code)


@costs_bp.route("/e/<code>/costs/expenses/<exp_id>/delete", methods=["POST"])
def delete_expense(code: str, exp_id: str) -> Response | tuple[str, int]:
    """Delete an expense (author, payer household owner or creator)."""
    ctx = load_event_context(code)
    exp = _get_expense(ctx, exp_id)
    if not ctx.can_delete(exp):
        abort(403)
    shared = exp.is_shared
    desc = exp.description
    db.session.delete(exp)
    log_event(ctx, "expense.deleted", target=desc if shared else None)
    db.session.commit()
    flash(_("Frais supprimé."), "success")
    return _back(code)


@costs_bp.route("/e/<code>/costs/households/<h_id>/delete", methods=["POST"])
def delete_household(code: str, h_id: str) -> Response | tuple[str, int]:
    """Delete a household (creator only). Without ``reassign_to``: refused if expenses or
    transfers refer to it; with it, everything moves to that household first (B038 §4.6)."""
    ctx = load_event_context(code)
    h = Household.query.filter_by(id=h_id, event_id=ctx.event.id).first()
    if not h:
        abort(404)
    if not ctx.can_delete(h):
        abort(403)
    reassign_to = request.form.get("reassign_to", "").strip()
    if reassign_to:
        return _merge_household(ctx, h, reassign_to)
    used = (
        Expense.query.filter_by(paid_by_household_id=h.id).first()
        or Transfer.query.filter(
            (Transfer.from_household_id == h.id) | (Transfer.to_household_id == h.id)
        ).first()
        or PaymentRequest.query.filter(
            (PaymentRequest.from_household_id == h.id) | (PaymentRequest.to_household_id == h.id)
        ).first()
    )
    if used is not None:
        flash(
            _("Ce foyer a des dépenses, transferts ou demandes : supprimez-les d'abord."), "danger"
        )
        return _back(code, "balance")
    name = h.name
    db.session.delete(h)
    log_event(ctx, "household.deleted", target=name)
    db.session.commit()
    flash(_("Foyer supprimé."), "success")
    return _back(code, "balance")


def _merge_household(ctx: EventContext, source: Household, target_id: str) -> Response:
    """Réaffecte tout ce qui touche ``source`` au foyer ``target`` puis supprime ``source``.

    Les parts sont ensuite recalculées sur les foyers restants, avec leurs propres poids.
    """
    event = ctx.event
    target = Household.query.filter_by(id=target_id, event_id=event.id).first()
    if target is None or target.id == source.id:
        abort(404)
    expenses = Expense.query.filter_by(paid_by_household_id=source.id).all()
    for exp in expenses:
        exp.paid_by_household_id = target.id
    for exp in Expense.query.filter(
        Expense.event_id == event.id, Expense.custom_split.isnot(None)
    ).all():
        try:
            weights = json.loads(exp.custom_split)
        except (json.JSONDecodeError, TypeError):
            continue  # get_split_weights ignores an unreadable split too
        if isinstance(weights, dict) and source.id in weights:
            weights[target.id] = weights.get(target.id, 0) + weights.pop(source.id)
            exp.custom_split = json.dumps(weights)
    links = 0
    for model in (Transfer, PaymentRequest):
        for row in model.query.filter(
            db.or_(model.from_household_id == source.id, model.to_household_id == source.id)
        ).all():
            if row.from_household_id == source.id:
                row.from_household_id = target.id
            if row.to_household_id == source.id:
                row.to_household_id = target.id
            if row.from_household_id == row.to_household_id:
                db.session.delete(row)  # X -> X : nets to zero
            else:
                links += 1
    items = 0
    if source.guest_id is not None:
        source_owner = db.session.get(Guest, source.guest_id)
        target_owner = db.session.get(Guest, target.guest_id) if target.guest_id else None
        if source_owner is not None:
            items = reassign_work(event, source_owner, target_owner)
    source_name, target_name = source.name, target.name
    db.session.flush()
    db.session.delete(source)
    log_event(
        ctx, "household.merged", target=target_name, details=_("%(name)s absorbé", name=source_name)
    )
    db.session.commit()
    details = ", ".join(
        [
            ngettext("%(n)d dépense", "%(n)d dépenses", len(expenses), n=len(expenses)),
            ngettext("%(n)d transfert ou demande", "%(n)d transferts ou demandes", links, n=links),
            ngettext("%(n)d article", "%(n)d articles", items, n=items),
        ]
    )
    flash(
        _(
            "Foyer « %(source)s » réaffecté à %(target)s (%(details)s).",
            source=source_name,
            target=target_name,
            details=details,
        ),
        "success",
    )
    return _back(event.code, "balance")


def _parse_transfer_households(
    ctx: EventContext, form: Any, event: Event, errors: FormErrors
) -> tuple[str, str]:
    """(from, to). Un participant non créateur ne peut enregistrer qu'un transfert impliquant son foyer."""
    mine = _my_household(ctx)
    if not ctx.is_creator and mine is None:
        abort(403)
    direction = form.get("direction", "")
    if direction in ("out", "in") and mine is not None:
        other = form.get("other_household_id", "")
        from_id, to_id = (mine.id, other) if direction == "out" else (other, mine.id)
        field = "other_household_id"
    else:
        from_id, to_id = form.get("from_household_id", ""), form.get("to_household_id", "")
        field = "from_household_id"
    if (
        from_id
        and to_id
        and not ctx.is_creator
        and (mine is None or mine.id not in (from_id, to_id))
    ):
        abort(403)
    if not from_id or not to_id:
        errors.add(field, _("Foyers d'origine et de destination requis."))
    elif from_id == to_id:
        errors.add(field, _("Le foyer d'origine et de destination doivent différer."))
    elif not _household_in_event(from_id, event) or not _household_in_event(to_id, event):
        errors.add(field, _("Foyer invalide pour cet événement."))
    return from_id, to_id


@costs_bp.route("/e/<code>/costs/transfers/new", methods=["POST"])
@limiter.limit("20 per hour")
def add_transfer(code: str) -> str | Response | tuple[str, int]:
    """Record a transfer/repayment between two households."""
    ctx = load_event_context(code)
    errors = FormErrors()
    from_id, to_id = _parse_transfer_households(ctx, request.form, ctx.event, errors)
    amount_cents = _parse_amount(request.form.get("amount", ""), errors)
    note = request.form.get("note", "").strip()
    if len(note) > 300:
        errors.add("note", _("Note trop longue (max 300)."))
    t_date = _parse_date(request.form.get("date", ""), errors)
    if errors:
        return _invalid(ctx, SHEET_TRANSFER, errors)
    db.session.add(
        Transfer(
            from_household_id=from_id,
            to_household_id=to_id,
            amount_cents=amount_cents,
            note=note,
            date=t_date,
            event_id=ctx.event.id,
            created_by=ctx.participant.id if ctx.participant else None,
        )
    )
    log_event(ctx, "transfer.created", details=f"{amount_cents / 100:.2f} {BASE_CURRENCY}")
    db.session.commit()
    flash(_("Transfert enregistré."), "success")
    return _back(code, "balance")


@costs_bp.route("/e/<code>/costs/transfers/<t_id>/delete", methods=["POST"])
def delete_transfer(code: str, t_id: str) -> Response | tuple[str, int]:
    """Delete a transfer (author or creator)."""
    ctx = load_event_context(code)
    t = Transfer.query.filter_by(id=t_id, event_id=ctx.event.id).first()
    if not t:
        abort(404)
    if not ctx.can_delete(t):
        abort(403)
    db.session.delete(t)
    log_event(ctx, "transfer.deleted")
    db.session.commit()
    flash(_("Transfert supprimé."), "success")
    return _back(code, "balance")


@costs_bp.route("/e/<code>/costs/payment-requests/new", methods=["POST"])
@limiter.limit("20 per hour")
def add_payment_request(code: str) -> str | Response | tuple[str, int]:
    """Create a payment request from one's own household (any household for the creator)."""
    ctx = load_event_context(code)
    mine = _my_household(ctx)
    if not ctx.is_creator and mine is None:
        abort(403)
    from_id = request.form.get("from_household_id", mine.id if mine else "")
    if not ctx.is_creator and mine is not None and from_id != mine.id:
        abort(403)
    to_id = request.form.get("to_household_id", "")
    message = request.form.get("message", "").strip()

    errors = FormErrors()
    if not from_id or not to_id:
        errors.add("to_household_id", _("Foyers requis."))
    elif from_id == to_id:
        errors.add("to_household_id", _("Les foyers doivent différer."))
    elif not _household_in_event(from_id, ctx.event) or not _household_in_event(to_id, ctx.event):
        errors.add("to_household_id", _("Foyer invalide pour cet événement."))
    amount_cents = _parse_amount(request.form.get("amount", ""), errors)
    if len(message) > 500:
        errors.add("message", _("Message trop long (max 500)."))
    if errors:
        return _invalid(ctx, SHEET_REQUEST, errors)

    payment_request = PaymentRequest(
        from_household_id=from_id,
        to_household_id=to_id,
        amount_cents=amount_cents,
        message=message,
        event_id=ctx.event.id,
        created_by=ctx.participant.id if ctx.participant else None,
    )
    db.session.add(payment_request)
    log_event(ctx, "payment_request.created", details=f"{amount_cents / 100:.2f} {BASE_CURRENCY}")
    db.session.commit()
    recipient = payment_request.to_household.guest_id
    if recipient:  # foyer sans participant : personne à notifier (jamais de diffusion)
        notify(
            ctx.event,
            "requests",
            ctx.participant,
            "",
            url_for("costs.index", code=code, tab="requests"),
            f"request-{payment_request.id}",
            only_guest_id=recipient,
        )
    flash(_("Demande de paiement créée."), "success")
    return _back(code, "requests")


@costs_bp.route("/e/<code>/costs/payment-requests/<pr_id>/resolve", methods=["POST"])
def resolve_payment_request(code: str, pr_id: str) -> Response | tuple[str, int]:
    """Mark a payment request as resolved (recipient household owner or creator)."""
    ctx = load_event_context(code)
    pr = PaymentRequest.query.filter_by(id=pr_id, event_id=ctx.event.id).first()
    if not pr:
        abort(404)
    if not ctx.can_edit(pr):
        abort(403)
    pr.is_resolved = True
    pr.resolved_at = datetime.now(UTC).replace(tzinfo=None)
    log_event(ctx, "payment_request.resolved")
    db.session.commit()
    flash(_("Demande marquée comme réglée."), "success")
    return _back(code, "requests")


@costs_bp.route("/e/<code>/costs/payment-requests/<pr_id>/delete", methods=["POST"])
def delete_payment_request(code: str, pr_id: str) -> Response | tuple[str, int]:
    """Delete a payment request (author or creator)."""
    ctx = load_event_context(code)
    pr = PaymentRequest.query.filter_by(id=pr_id, event_id=ctx.event.id).first()
    if not pr:
        abort(404)
    if not ctx.can_delete(pr):
        abort(403)
    db.session.delete(pr)
    log_event(ctx, "payment_request.deleted")
    db.session.commit()
    flash(_("Demande supprimée."), "success")
    return _back(code, "requests")


@costs_bp.route("/e/<code>/costs/ratio", methods=["POST"])
def update_ratio(code: str) -> str | Response | tuple[str, int]:
    """Update adult/child weights for all households in the event (creator only)."""
    ctx = load_event_context(code)
    if not ctx.is_creator:
        abort(403)
    errors = FormErrors()
    adult_weight = _parse_decimal(request.form.get("adult_weight", "1.0"))
    child_weight = _parse_decimal(request.form.get("child_weight", "0.5"))
    if adult_weight is None or adult_weight <= 0 or adult_weight > 10:
        errors.add("adult_weight", _("Parts par adulte : 0 < valeur ≤ 10."))
    if child_weight is None or child_weight < 0 or child_weight > 10:
        errors.add("child_weight", _("Parts par enfant : 0 ≤ valeur ≤ 10."))
    if errors or adult_weight is None or child_weight is None:
        return _invalid(ctx, SHEET_RATIO, errors)
    for h in ctx.event.households.all():
        h.adult_weight = adult_weight
        h.child_weight = child_weight
    log_event(ctx, "ratio.updated", details=f"adult={adult_weight}, child={child_weight}")
    db.session.commit()
    flash(_("Ratio appliqué à tous les foyers."), "success")
    return _back(code, "balance")
