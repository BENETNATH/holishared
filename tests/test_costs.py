"""Tests for costs blueprint — cost sharing by household."""

from app.models import ActivityLog, Expense, Household


def _login_creator(client, creator):
    with client.session_transaction() as sess:
        sess["_user_id"] = creator.id
        sess["_fresh"] = True


def _login_guest(client, event, guest):
    with client.session_transaction() as sess:
        sess[f"guest_{event.code}"] = guest.id


def _make_household(db, event, name="Famille A", adults=2, children=1, aw=1.0, cw=0.5):
    h = Household(
        name=name, num_adults=adults, num_children=children,
        adult_weight=aw, child_weight=cw, event_id=event.id,
    )
    db.session.add(h)
    db.session.commit()
    return h


def _make_expense(db, event, household, desc="Loyer", amount_cents=10000):
    e = Expense(
        description=desc, amount_cents=amount_cents,
        paid_by_household_id=household.id, event_id=event.id,
    )
    db.session.add(e)
    db.session.commit()
    return e


class TestCostsIndex:
    def test_index_renders_for_creator(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/costs")
        assert resp.status_code == 200
        assert b"Partage de frais" in resp.data

    def test_index_renders_for_guest(self, client, event, guest):
        _login_guest(client, event, guest)
        resp = client.get(f"/e/{event.code}/costs")
        assert resp.status_code == 200

    def test_index_404_invalid_code(self, client, creator):
        _login_creator(client, creator)
        resp = client.get("/e/xxxxxx/costs")
        assert resp.status_code == 404

    def test_index_redirects_no_access(self, client, event):
        resp = client.get(f"/e/{event.code}/costs")
        assert resp.status_code == 302
        assert "/join" in resp.headers["Location"] or "/mycode" in resp.headers["Location"]


class TestHouseholds:
    def test_add_household_success(self, client, creator, event, db):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/costs/households/new", data={
            "name": "Famille Dupont",
            "num_adults": "2",
            "num_children": "2",
            "adult_weight": "1.0",
            "child_weight": "0.5",
        })
        assert resp.status_code == 302
        h = Household.query.filter_by(name="Famille Dupont").first()
        assert h is not None
        assert h.total_weight == 3.0  # 2*1.0 + 2*0.5

    def test_add_household_missing_name(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/costs/households/new", data={
            "name": "",
            "num_adults": "2",
        }, follow_redirects=True)
        assert b"requis" in resp.data.lower() or b"Nom" in resp.data

    def test_add_household_invalid_adults(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/costs/households/new", data={
            "name": "Test",
            "num_adults": "0",
        }, follow_redirects=True)
        assert b"entre 1 et 50" in resp.data or b"Adultes" in resp.data

    def test_add_household_logs(self, client, creator, event, db):
        _login_creator(client, creator)
        client.post(f"/e/{event.code}/costs/households/new", data={
            "name": "Logged HH",
            "num_adults": "1",
        })
        log = ActivityLog.query.filter_by(event_id=event.id, action="household.created").first()
        assert log is not None
        assert log.target == "Logged HH"

    def test_delete_household_as_creator(self, client, creator, event, db):
        _login_creator(client, creator)
        h = _make_household(db, event, "ToDelete")
        resp = client.post(f"/e/{event.code}/costs/households/{h.id}/delete")
        assert resp.status_code == 302
        assert Household.query.get(h.id) is None

    def test_delete_household_forbidden_for_guest(self, client, event, guest, db):
        _login_guest(client, event, guest)
        h = _make_household(db, event, "Protected")
        resp = client.post(f"/e/{event.code}/costs/households/{h.id}/delete")
        assert resp.status_code == 403


class TestExpenses:
    def test_add_expense_success(self, client, creator, event, db):
        _login_creator(client, creator)
        h = _make_household(db, event)
        resp = client.post(f"/e/{event.code}/costs/expenses/new", data={
            "description": "Loyer",
            "amount": "500.00",
            "household_id": h.id,
            "date": "2026-12-01",
        })
        assert resp.status_code == 302
        exp = Expense.query.filter_by(description="Loyer").first()
        assert exp is not None
        assert exp.amount_cents == 50000

    def test_add_expense_missing_description(self, client, creator, event, db):
        _login_creator(client, creator)
        h = _make_household(db, event)
        resp = client.post(f"/e/{event.code}/costs/expenses/new", data={
            "description": "",
            "amount": "100",
            "household_id": h.id,
        }, follow_redirects=True)
        assert b"Description" in resp.data or b"requise" in resp.data

    def test_add_expense_invalid_amount(self, client, creator, event, db):
        _login_creator(client, creator)
        h = _make_household(db, event)
        resp = client.post(f"/e/{event.code}/costs/expenses/new", data={
            "description": "Test",
            "amount": "-5",
            "household_id": h.id,
        }, follow_redirects=True)
        assert b"invalide" in resp.data.lower()

    def test_add_expense_logs(self, client, creator, event, db):
        _login_creator(client, creator)
        h = _make_household(db, event)
        client.post(f"/e/{event.code}/costs/expenses/new", data={
            "description": "Logged Expense",
            "amount": "100",
            "household_id": h.id,
        })
        log = ActivityLog.query.filter_by(event_id=event.id, action="expense.created").first()
        assert log is not None
        assert log.target == "Logged Expense"

    def test_delete_expense_as_creator(self, client, creator, event, db):
        _login_creator(client, creator)
        h = _make_household(db, event)
        exp = _make_expense(db, event, h, "ToDelete", 10000)
        resp = client.post(f"/e/{event.code}/costs/expenses/{exp.id}/delete")
        assert resp.status_code == 302
        assert Expense.query.get(exp.id) is None

    def test_delete_expense_forbidden_for_guest(self, client, event, guest, db):
        _login_guest(client, event, guest)
        h = _make_household(db, event)
        exp = _make_expense(db, event, h, "Protected", 10000)
        resp = client.post(f"/e/{event.code}/costs/expenses/{exp.id}/delete")
        assert resp.status_code == 403


class TestSettlement:
    def test_settlement_equal_split(self, client, creator, event, db):
        """Two households, equal weight, one expense → 50/50 split."""
        _login_creator(client, creator)
        h1 = _make_household(db, event, "A", adults=2, children=0)
        _make_household(db, event, "B", adults=2, children=0)
        _make_expense(db, event, h1, "Total", 10000)  # 100€ paid by A

        resp = client.get(f"/e/{event.code}/costs")
        assert resp.status_code == 200
        # B should receive 50€ from A
        assert b"B" in resp.data

    def test_settlement_weighted(self, client, creator, event, db):
        """Household A (2 adults) vs B (1 adult + 1 child @ 0.5) → 2:1.5 ratio."""
        _login_creator(client, creator)
        h1 = _make_household(db, event, "A", adults=2, children=0, aw=1.0, cw=0.5)
        _make_household(db, event, "B", adults=1, children=1, aw=1.0, cw=0.5)
        # Total weight: A=2.0, B=1.5, total=3.5
        # Expense: 70€ paid by A
        _make_expense(db, event, h1, "Total", 7000)
        # A share: 70 * (2/3.5) = 40€, B share: 70 * (1.5/3.5) = 30€
        # A paid 70, owes 30. B paid 0, should receive 30.
        # Settlement: A → B: 30€

        resp = client.get(f"/e/{event.code}/costs")
        assert resp.status_code == 200
        assert b"30.00" in resp.data

    def test_settlement_no_expenses(self, client, creator, event, db):
        _login_creator(client, creator)
        _make_household(db, event, "A")
        resp = client.get(f"/e/{event.code}/costs")
        assert resp.status_code == 200
        # No settlement section
        assert "Règlement".encode() not in resp.data or b"settlement" not in resp.data

    def test_settlement_multiple_expenses(self, client, creator, event, db):
        """Multiple expenses across households."""
        _login_creator(client, creator)
        h1 = _make_household(db, event, "A", adults=1, children=0)
        h2 = _make_household(db, event, "B", adults=1, children=0)
        # A pays 60€, B pays 40€ → total 100€, each owes 50€
        _make_expense(db, event, h1, "Exp1", 6000)
        _make_expense(db, event, h2, "Exp2", 4000)
        # A paid 60, owes 50 → net +10 (should receive 10)
        # B paid 40, owes 50 → net -10 (should pay 10)
        # Settlement: B → A: 10€

        resp = client.get(f"/e/{event.code}/costs")
        assert resp.status_code == 200
        assert b"10.00" in resp.data


class TestTransfers:
    def test_add_transfer(self, client, creator, event, db):
        from app.models import Transfer
        _login_creator(client, creator)
        h1 = _make_household(db, event, "A")
        h2 = _make_household(db, event, "B")
        resp = client.post(f"/e/{event.code}/costs/transfers/new", data={
            "from_household_id": h1.id, "to_household_id": h2.id,
            "amount": "20.00", "note": "remboursement",
        })
        assert resp.status_code == 302
        t = Transfer.query.filter_by(event_id=event.id).first()
        assert t is not None
        assert t.amount_cents == 2000

    def test_add_transfer_same_household_rejected(self, client, creator, event, db):
        _login_creator(client, creator)
        h1 = _make_household(db, event, "A")
        resp = client.post(f"/e/{event.code}/costs/transfers/new", data={
            "from_household_id": h1.id, "to_household_id": h1.id, "amount": "10",
        }, follow_redirects=True)
        assert b"diff\u00e9rer" in resp.data or b"doivent" in resp.data

    def test_delete_transfer_as_creator(self, client, creator, event, db):
        from app.models import Transfer
        _login_creator(client, creator)
        h1 = _make_household(db, event, "A")
        h2 = _make_household(db, event, "B")
        t = Transfer(from_household_id=h1.id, to_household_id=h2.id,
                     amount_cents=1000, event_id=event.id)
        db.session.add(t)
        db.session.commit()
        resp = client.post(f"/e/{event.code}/costs/transfers/{t.id}/delete")
        assert resp.status_code == 302
        assert Transfer.query.get(t.id) is None

    def test_settlement_accounts_for_transfer(self, client, creator, event, db):
        """A owes B 30; a 30 transfer A->B settles it to zero."""
        from app.models import Transfer
        _login_creator(client, creator)
        h1 = _make_household(db, event, "A", adults=2, children=0)
        h2 = _make_household(db, event, "B", adults=2, children=0)
        _make_expense(db, event, h1, "Total", 10000)  # A paid 100, each owes 50
        # B owes A 50. Transfer B->A of 50 settles it.
        t = Transfer(from_household_id=h2.id, to_household_id=h1.id,
                     amount_cents=5000, event_id=event.id)
        db.session.add(t)
        db.session.commit()
        resp = client.get(f"/e/{event.code}/costs")
        assert resp.status_code == 200
        # No outstanding settlement (the transfer covered it)
        assert b"Qui rembourse qui" not in resp.data


class TestPaymentRequests:
    def test_add_payment_request(self, client, creator, event, db):
        from app.models import PaymentRequest
        _login_creator(client, creator)
        h1 = _make_household(db, event, "A")
        h2 = _make_household(db, event, "B")
        resp = client.post(f"/e/{event.code}/costs/payment-requests/new", data={
            "from_household_id": h1.id, "to_household_id": h2.id,
            "amount": "15.00", "message": "pour le loyer",
        })
        assert resp.status_code == 302
        pr = PaymentRequest.query.filter_by(event_id=event.id).first()
        assert pr is not None
        assert pr.amount_cents == 1500
        assert pr.is_resolved is False

    def test_resolve_payment_request(self, client, creator, event, db):
        from app.models import PaymentRequest
        _login_creator(client, creator)
        h1 = _make_household(db, event, "A")
        h2 = _make_household(db, event, "B")
        pr = PaymentRequest(from_household_id=h1.id, to_household_id=h2.id,
                            amount_cents=1000, event_id=event.id)
        db.session.add(pr)
        db.session.commit()
        resp = client.post(f"/e/{event.code}/costs/payment-requests/{pr.id}/resolve")
        assert resp.status_code == 302
        db.session.refresh(pr)
        assert pr.is_resolved is True

    def test_delete_payment_request_forbidden_for_guest(self, client, event, guest, db):
        from app.models import PaymentRequest
        _login_guest(client, event, guest)
        h1 = _make_household(db, event, "A")
        h2 = _make_household(db, event, "B")
        pr = PaymentRequest(from_household_id=h1.id, to_household_id=h2.id,
                            amount_cents=1000, event_id=event.id)
        db.session.add(pr)
        db.session.commit()
        resp = client.post(f"/e/{event.code}/costs/payment-requests/{pr.id}/delete")
        assert resp.status_code == 403
