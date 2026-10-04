"""Costs blueprint - cost sharing by household with weighted settlement."""

from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.extensions import db
from app.models import Event, Expense, Household, PaymentRequest, Transfer
from app.utils import log_action

costs_bp = Blueprint("costs", __name__)

CURRENCIES = ["EUR", "USD", "GBP", "CHF", "CAD", "AUD", "JPY"]


def _get_event_or_404(code):
    event = Event.query.filter_by(code=code, is_active=True).first()
    if not event:
        return None
    return event


def _resolve_actor(event):
    """Return (guest, is_creator, denied_redirect_or_None)."""
    from flask_login import current_user

    from app.models import Guest

    is_creator = (current_user.is_authenticated and current_user.id == event.creator_id)
    guest_id = session.get(f"guest_{event.code}")
    guest = None
    if guest_id:
        guest = Guest.query.filter_by(id=guest_id, event_id=event.id, is_active=True).first()
    if not guest and not is_creator:
        return None, False, redirect(url_for("events.guest_access", code=event.code))
    return guest, is_creator, None


def _actor(event, guest):
    return (guest.display_name if guest else "Créateur", "guest" if guest else "creator")


def _base_cents(amount_cents, exchange_rate):
    """Amount converted to base currency, in cents (int)."""
    return round(amount_cents * (exchange_rate or 1.0))


def _per_expense_shares(households, expenses):
    """Return ({household_id: share_cents}, {household_id: paid_cents})."""
    ids = {h.id for h in households}
    paid = {h.id: 0 for h in households}
    shares = {h.id: 0 for h in households}
    for exp in expenses:
        if exp.paid_by_household_id not in ids:
            continue
        base = _base_cents(exp.amount_cents, exp.exchange_rate)
        paid[exp.paid_by_household_id] += base
        weights = exp.get_split_weights(households)
        total_w = sum(weights.get(h.id, 0) for h in households)
        if total_w > 0:
            for h in households:
                shares[h.id] += round(base * weights.get(h.id, 0) / total_w)
    # Rounding fix: shares must sum to the total base amount.
    total_base = sum(
        _base_cents(e.amount_cents, e.exchange_rate)
        for e in expenses if e.paid_by_household_id in ids
    )
    diff = total_base - sum(shares.values())
    if diff != 0 and households:
        shares[households[-1].id] += diff
    return shares, paid


def _settlement(households, expenses, transfers):
    """Compute who pays whom, in base currency cents.

    Accounts for per-expense custom splits, exchange rates, and transfers
    already made (a transfer from A to B reduces A's outstanding debt).
    Uses the greedy minimum-transactions algorithm.
    """
    if not households:
        return []
    shares, paid = _per_expense_shares(households, expenses)
    balances = {h.id: paid[h.id] - shares[h.id] for h in households}
    ids = {h.id for h in households}
    for t in transfers:
        if t.from_household_id not in ids or t.to_household_id not in ids:
            continue
        base = _base_cents(t.amount_cents, t.exchange_rate)
        balances[t.from_household_id] += base
        balances[t.to_household_id] -= base

    debtors = sorted([(hid, b) for hid, b in balances.items() if b < 0], key=lambda x: x[1])
    creditors = sorted([(hid, b) for hid, b in balances.items() if b > 0],
                       key=lambda x: x[1], reverse=True)
    settlements = []
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


def _category_breakdown(expenses):
    """Return {category: base_cents} sorted by amount desc."""
    totals = {}
    for exp in expenses:
        base = _base_cents(exp.amount_cents, exp.exchange_rate)
        cat = exp.category or "general"
        totals[cat] = totals.get(cat, 0) + base
    return sorted(totals.items(), key=lambda x: x[1], reverse=True)


# === Routes ===

@costs_bp.route("/e/<code>/costs")
def index(code):
    """Cost sharing dashboard."""
    event = _get_event_or_404(code)
    if not event:
        return "Not found", 404

    guest, is_creator, denied = _resolve_actor(event)
    if denied:
        return denied

    households = event.households.all()
    expenses = event.expenses.order_by(Expense.date.desc(), Expense.created_at.desc()).all()
    transfers = event.transfers.order_by(Transfer.created_at.desc()).all()
    payment_requests = (
        event.payment_requests.order_by(PaymentRequest.is_resolved.asc(),
                                        PaymentRequest.created_at.desc()).all()
    )

    settlements = _settlement(households, expenses, transfers)
    h_map = {h.id: h for h in households}
    settlement_display = [
        {"from": h_map.get(f), "to": h_map.get(t), "amount": a / 100.0}
        for f, t, a in settlements
    ]

    shares, paid = _per_expense_shares(households, expenses)
    h_summary = [
        {
            "household": h,
            "share": shares[h.id] / 100.0,
            "paid": paid[h.id] / 100.0,
            "balance": (paid[h.id] - shares[h.id]) / 100.0,
        }
        for h in households
    ]

    total_expenses = sum(_base_cents(e.amount_cents, e.exchange_rate) for e in expenses) / 100.0
    category_breakdown = [
        {"category": c, "amount": a / 100.0} for c, a in _category_breakdown(expenses)
    ]

    return render_template("costs/index.html",
                           event=event, guest=guest, is_creator=is_creator,
                           households=households, expenses=expenses,
                           transfers=transfers, payment_requests=payment_requests,
                           settlements=settlement_display, h_summary=h_summary,
                           total_expenses=total_expenses,
                           category_breakdown=category_breakdown,
                           currencies=CURRENCIES)


@costs_bp.route("/e/<code>/costs/households/new", methods=["GET", "POST"])
def add_household(code):
    """Add a household."""
    event = _get_event_or_404(code)
    if not event:
        return "Not found", 404

    guest, _is_creator, denied = _resolve_actor(event)
    if denied:
        return denied

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        num_adults = request.form.get("num_adults", "1")
        num_children = request.form.get("num_children", "0")
        adult_weight = request.form.get("adult_weight", "1.0")
        child_weight = request.form.get("child_weight", "0.5")

        errors = []
        if not name or len(name) < 2:
            errors.append("Nom du foyer requis (min 2 caractères).")
        try:
            num_adults = int(num_adults)
            num_children = int(num_children)
            adult_weight = float(adult_weight)
            child_weight = float(child_weight)
        except (ValueError, TypeError):
            errors.append("Valeurs numériques invalides.")
        if not errors:
            if num_adults < 1:
                errors.append("Au moins 1 adulte requis.")
            if num_children < 0:
                errors.append("Nombre d'enfants invalide.")
            if adult_weight <= 0 or child_weight < 0:
                errors.append("Poids invalides.")

        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            h = Household(
                name=name,
                num_adults=num_adults,
                num_children=num_children,
                adult_weight=adult_weight,
                child_weight=child_weight,
                event_id=event.id,
            )
            db.session.add(h)
            actor_name, actor_type = _actor(event, guest)
            log_action(db.session, event.id, actor_name, actor_type,
                       "household.created", target=name)
            db.session.commit()
            flash("Foyer ajouté.", "success")
            return redirect(url_for("costs.index", code=code))

    return render_template("costs/household_form.html", event=event, guest=guest)


@costs_bp.route("/e/<code>/costs/expenses/new", methods=["POST"])
def add_expense(code):
    """Add an expense."""
    event = _get_event_or_404(code)
    if not event:
        return "Not found", 404

    guest, _is_creator, denied = _resolve_actor(event)
    if denied:
        return denied

    description = request.form.get("description", "").strip()
    amount_str = request.form.get("amount", "").strip()
    household_id = request.form.get("household_id", "")
    exp_date = request.form.get("date", "")
    category = request.form.get("category", "general").strip() or "general"
    currency = request.form.get("currency", "EUR").strip().upper() or "EUR"
    rate_str = request.form.get("exchange_rate", "1.0").strip()

    errors = []
    if not description:
        errors.append("Description requise.")
    try:
        amount_cents = round(float(amount_str) * 100)
        if amount_cents <= 0:
            errors.append("Montant invalide.")
    except (ValueError, TypeError):
        errors.append("Montant invalide.")
    if not household_id:
        errors.append("Foyer payeur requis.")
    try:
        exchange_rate = float(rate_str) if rate_str else 1.0
        if exchange_rate <= 0:
            raise ValueError
    except (ValueError, TypeError):
        errors.append("Taux de change invalide.")
        exchange_rate = 1.0

    if errors:
        for e in errors:
            flash(e, "danger")
        return redirect(url_for("costs.index", code=code))

    d = None
    if exp_date:
        try:
            d = datetime.strptime(exp_date, "%Y-%m-%d").date()
        except ValueError:
            pass

    exp = Expense(
        description=description,
        amount_cents=amount_cents,
        currency=currency,
        exchange_rate=exchange_rate,
        category=category,
        paid_by_household_id=household_id,
        date=d,
        event_id=event.id,
    )
    db.session.add(exp)

    actor_name, actor_type = _actor(event, guest)
    log_action(db.session, event.id, actor_name, actor_type,
               "expense.created", target=description,
               details=f"{amount_cents/100:.2f} {currency}")
    db.session.commit()
    flash("Frais ajouté.", "success")
    return redirect(url_for("costs.index", code=code))


@costs_bp.route("/e/<code>/costs/expenses/<exp_id>/delete", methods=["POST"])
def delete_expense(code, exp_id):
    """Delete an expense (creator only)."""
    event = _get_event_or_404(code)
    if not event:
        return "Not found", 404

    guest, is_creator, denied = _resolve_actor(event)
    if denied:
        return denied

    if not is_creator:
        return "Pas autorisé.", 403

    exp = Expense.query.filter_by(id=exp_id, event_id=event.id).first()
    if not exp:
        return "Not found", 404

    desc = exp.description
    db.session.delete(exp)
    actor_name, actor_type = _actor(event, guest)
    log_action(db.session, event.id, actor_name, actor_type,
               "expense.deleted", target=desc)
    db.session.commit()
    flash("Frais supprimé.", "success")
    return redirect(url_for("costs.index", code=code))


@costs_bp.route("/e/<code>/costs/households/<h_id>/delete", methods=["POST"])
def delete_household(code, h_id):
    """Delete a household (creator only)."""
    event = _get_event_or_404(code)
    if not event:
        return "Not found", 404

    guest, is_creator, denied = _resolve_actor(event)
    if denied:
        return denied

    if not is_creator:
        return "Pas autorisé.", 403

    h = Household.query.filter_by(id=h_id, event_id=event.id).first()
    if not h:
        return "Not found", 404

    name = h.name
    db.session.delete(h)
    actor_name, actor_type = _actor(event, guest)
    log_action(db.session, event.id, actor_name, actor_type,
               "household.deleted", target=name)
    db.session.commit()
    flash("Foyer supprimé.", "success")
    return redirect(url_for("costs.index", code=code))


@costs_bp.route("/e/<code>/costs/transfers/new", methods=["POST"])
def add_transfer(code):
    """Record a transfer/repayment between two households."""
    event = _get_event_or_404(code)
    if not event:
        return "Not found", 404

    guest, _is_creator, denied = _resolve_actor(event)
    if denied:
        return denied

    from_id = request.form.get("from_household_id", "")
    to_id = request.form.get("to_household_id", "")
    amount_str = request.form.get("amount", "").strip()
    note = request.form.get("note", "").strip()
    t_date = request.form.get("date", "")

    errors = []
    if not from_id or not to_id:
        errors.append("Foyers d'origine et de destination requis.")
    elif from_id == to_id:
        errors.append("Le foyer d'origine et de destination doivent différer.")
    try:
        amount_cents = round(float(amount_str) * 100)
        if amount_cents <= 0:
            errors.append("Montant invalide.")
    except (ValueError, TypeError):
        errors.append("Montant invalide.")

    if errors:
        for e in errors:
            flash(e, "danger")
        return redirect(url_for("costs.index", code=code))

    d = None
    if t_date:
        try:
            d = datetime.strptime(t_date, "%Y-%m-%d").date()
        except ValueError:
            pass

    t = Transfer(
        from_household_id=from_id,
        to_household_id=to_id,
        amount_cents=amount_cents,
        note=note,
        date=d,
        event_id=event.id,
    )
    db.session.add(t)
    actor_name, actor_type = _actor(event, guest)
    log_action(db.session, event.id, actor_name, actor_type,
               "transfer.created", details=f"{amount_cents/100:.2f} €")
    db.session.commit()
    flash("Transfert enregistré.", "success")
    return redirect(url_for("costs.index", code=code))


@costs_bp.route("/e/<code>/costs/transfers/<t_id>/delete", methods=["POST"])
def delete_transfer(code, t_id):
    """Delete a transfer (creator only)."""
    event = _get_event_or_404(code)
    if not event:
        return "Not found", 404

    guest, is_creator, denied = _resolve_actor(event)
    if denied:
        return denied

    if not is_creator:
        return "Pas autorisé.", 403

    t = Transfer.query.filter_by(id=t_id, event_id=event.id).first()
    if not t:
        return "Not found", 404

    db.session.delete(t)
    actor_name, actor_type = _actor(event, guest)
    log_action(db.session, event.id, actor_name, actor_type, "transfer.deleted")
    db.session.commit()
    flash("Transfert supprimé.", "success")
    return redirect(url_for("costs.index", code=code))


@costs_bp.route("/e/<code>/costs/payment-requests/new", methods=["POST"])
def add_payment_request(code):
    """Create a payment request (reminder) from one household to another."""
    event = _get_event_or_404(code)
    if not event:
        return "Not found", 404

    guest, _is_creator, denied = _resolve_actor(event)
    if denied:
        return denied

    from_id = request.form.get("from_household_id", "")
    to_id = request.form.get("to_household_id", "")
    amount_str = request.form.get("amount", "").strip()
    message = request.form.get("message", "").strip()

    errors = []
    if not from_id or not to_id:
        errors.append("Foyers requis.")
    elif from_id == to_id:
        errors.append("Les foyers doivent différer.")
    try:
        amount_cents = round(float(amount_str) * 100)
        if amount_cents <= 0:
            errors.append("Montant invalide.")
    except (ValueError, TypeError):
        errors.append("Montant invalide.")

    if errors:
        for e in errors:
            flash(e, "danger")
        return redirect(url_for("costs.index", code=code))

    pr = PaymentRequest(
        from_household_id=from_id,
        to_household_id=to_id,
        amount_cents=amount_cents,
        message=message,
        event_id=event.id,
    )
    db.session.add(pr)
    actor_name, actor_type = _actor(event, guest)
    log_action(db.session, event.id, actor_name, actor_type,
               "payment_request.created", details=f"{amount_cents/100:.2f} €")
    db.session.commit()
    flash("Demande de paiement créée.", "success")
    return redirect(url_for("costs.index", code=code))


@costs_bp.route("/e/<code>/costs/payment-requests/<pr_id>/resolve", methods=["POST"])
def resolve_payment_request(code, pr_id):
    """Mark a payment request as resolved."""
    event = _get_event_or_404(code)
    if not event:
        return "Not found", 404

    guest, _is_creator, denied = _resolve_actor(event)
    if denied:
        return denied

    pr = PaymentRequest.query.filter_by(id=pr_id, event_id=event.id).first()
    if not pr:
        return "Not found", 404

    pr.is_resolved = True
    from datetime import UTC
    pr.resolved_at = datetime.now(UTC)
    actor_name, actor_type = _actor(event, guest)
    log_action(db.session, event.id, actor_name, actor_type, "payment_request.resolved")
    db.session.commit()
    flash("Demande marquée comme réglée.", "success")
    return redirect(url_for("costs.index", code=code))


@costs_bp.route("/e/<code>/costs/payment-requests/<pr_id>/delete", methods=["POST"])
def delete_payment_request(code, pr_id):
    """Delete a payment request (creator only)."""
    event = _get_event_or_404(code)
    if not event:
        return "Not found", 404

    guest, is_creator, denied = _resolve_actor(event)
    if denied:
        return denied

    if not is_creator:
        return "Pas autorisé.", 403

    pr = PaymentRequest.query.filter_by(id=pr_id, event_id=event.id).first()
    if not pr:
        return "Not found", 404

    db.session.delete(pr)
    actor_name, actor_type = _actor(event, guest)
    log_action(db.session, event.id, actor_name, actor_type, "payment_request.deleted")
    db.session.commit()
    flash("Demande supprimée.", "success")
    return redirect(url_for("costs.index", code=code))
