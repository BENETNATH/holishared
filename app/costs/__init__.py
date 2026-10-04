"""Costs blueprint - cost sharing by household with weighted settlement."""

from flask import (Blueprint, render_template, redirect, url_for, flash,
                   request, session)
from datetime import date, datetime
from app.extensions import db
from app.models import Event, Household, Expense, ActivityLog
from app.utils import log_action

costs_bp = Blueprint("costs", __name__)


def _get_event_or_404(code):
    event = Event.query.filter_by(code=code, is_active=True).first()
    if not event:
        return None
    return event


def _resolve_actor(event):
    """Return (guest, is_creator) or redirect to mycode."""
    from flask_login import current_user
    is_creator = (current_user.is_authenticated and current_user.id == event.creator_id)
    guest_id = session.get(f"guest_{event.code}")
    guest = None
    if guest_id:
        from app.models import Guest
        guest = Guest.query.filter_by(id=guest_id, event_id=event.id, is_active=True).first()
    if not guest and not is_creator:
        return None, False, redirect(url_for("events.guest_access", code=event.code))
    return guest, is_creator, None


def _settlement(households, expenses):
    """Calculate who pays whom.
    
    Returns list of (from_household, to_household, amount_cents).
    Uses the "minimum transactions" algorithm (greedy: match largest debtor with largest creditor).
    """
    if not households or not expenses:
        return []

    total_weight = sum(h.total_weight for h in households)
    if total_weight == 0:
        return []

    total_expenses = sum(e.amount_cents for e in expenses)

    # Calculate each household's share and what they paid
    balances = {}  # household_id -> net balance (positive = should receive, negative = should pay)
    for h in households:
        share = int(round(total_expenses * (h.total_weight / total_weight)))
        paid = sum(e.amount_cents for e in expenses if e.paid_by_household_id == h.id)
        balances[h.id] = paid - share  # positive = overpaid (should receive), negative = underpaid (should pay)

    # Fix rounding: adjust the last household so balances sum to 0
    diff = -sum(balances.values())
    if diff != 0 and households:
        balances[households[-1].id] += diff

    # Greedy settlement: match largest debtor with largest creditor
    debtors = [(hid, bal) for hid, bal in balances.items() if bal < 0]
    creditors = [(hid, bal) for hid, bal in balances.items() if bal > 0]
    debtors.sort(key=lambda x: x[1])  # most negative first
    creditors.sort(key=lambda x: x[1], reverse=True)  # most positive first

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
    settlements = _settlement(households, expenses)

    # Build settlement display
    h_map = {h.id: h for h in households}
    settlement_display = []
    for from_id, to_id, amount in settlements:
        settlement_display.append({
            "from": h_map.get(from_id),
            "to": h_map.get(to_id),
            "amount": amount / 100.0,
        })

    # Per-household summary
    total_weight = sum(h.total_weight for h in households)
    total_expenses = sum(e.amount_cents for e in expenses)
    h_summary = []
    for h in households:
        share = int(round(total_expenses * (h.total_weight / total_weight))) if total_weight > 0 else 0
        paid = sum(e.amount_cents for e in expenses if e.paid_by_household_id == h.id)
        h_summary.append({
            "household": h,
            "share": share / 100.0,
            "paid": paid / 100.0,
            "balance": (paid - share) / 100.0,
        })

    return render_template("costs/index.html",
                           event=event, guest=guest, is_creator=is_creator,
                           households=households, expenses=expenses,
                           settlements=settlement_display, h_summary=h_summary,
                           total_expenses=total_expenses / 100.0)


@costs_bp.route("/e/<code>/costs/households/new", methods=["GET", "POST"])
def add_household(code):
    """Add a household."""
    event = _get_event_or_404(code)
    if not event:
        return "Not found", 404

    guest, is_creator, denied = _resolve_actor(event)
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

            actor_name = guest.display_name if guest else "Créateur"
            actor_type = "guest" if guest else "creator"
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

    guest, is_creator, denied = _resolve_actor(event)
    if denied:
        return denied

    description = request.form.get("description", "").strip()
    amount_str = request.form.get("amount", "").strip()
    household_id = request.form.get("household_id", "")
    exp_date = request.form.get("date", "")

    errors = []
    if not description:
        errors.append("Description requise.")
    try:
        amount_cents = int(round(float(amount_str) * 100))
        if amount_cents <= 0:
            errors.append("Montant invalide.")
    except (ValueError, TypeError):
        errors.append("Montant invalide.")
    if not household_id:
        errors.append("Foyer payeur requis.")

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
        paid_by_household_id=household_id,
        date=d,
        event_id=event.id,
    )
    db.session.add(exp)

    actor_name = guest.display_name if guest else "Créateur"
    actor_type = "guest" if guest else "creator"
    log_action(db.session, event.id, actor_name, actor_type,
               "expense.created", target=description, details=f"{amount_cents/100:.2f}€")
    db.session.commit()
    flash("Frais ajouté.", "success")
    return redirect(url_for("costs.index", code=code))


@costs_bp.route("/e/<code>/costs/expenses/<exp_id>/delete", methods=["POST"])
def delete_expense(code, exp_id):
    """Delete an expense."""
    event = _get_event_or_404(code)
    if not event:
        return "Not found", 404

    guest, is_creator, denied = _resolve_actor(event)
    if denied:
        return denied

    exp = Expense.query.filter_by(id=exp_id, event_id=event.id).first()
    if not exp:
        return "Not found", 404

    # Only creator can delete
    if not is_creator:
        return "Pas autorisé.", 403

    desc = exp.description
    db.session.delete(exp)

    actor_name = guest.display_name if guest else "Créateur"
    actor_type = "guest" if guest else "creator"
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

    actor_name = guest.display_name if guest else "Créateur"
    actor_type = "guest" if guest else "creator"
    log_action(db.session, event.id, actor_name, actor_type,
               "household.deleted", target=name)
    db.session.commit()
    flash("Foyer supprimé.", "success")
    return redirect(url_for("costs.index", code=code))
