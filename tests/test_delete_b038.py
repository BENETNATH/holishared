"""Tests B038-L2 — suppression d'un membre avec réattribution (WP2).

TDD : écrits AVANT le code (spec ``specs/b038-identity-recovery-spec.md`` §4, §9.2).
Le POST ``action=delete`` de la page Participants n'existe pas encore ; ces tests
doivent échouer à l'état rouge.
"""

from datetime import date

import pytest

from app.models import (
    Activity,
    ActivityLog,
    ActivityRSVP,
    ApiKey,
    ChatMessage,
    Expense,
    Guest,
    Household,
    ListActivityCoverage,
    ListItem,
    ListMealCoverage,
    Meal,
    PaymentRequest,
    Poll,
    PollOption,
    PollVote,
    PushSubscription,
    SharedList,
    Transfer,
)


def _post_delete(client, event, guest_id, reassign_to):
    return client.post(
        f"/e/{event.code}/members",
        data={"action": "delete", "guest_id": guest_id, "reassign_to": reassign_to},
    )


def _flashes(client):
    with client.session_transaction() as s:
        return [msg for _cat, msg in s.get("_flashes", [])]


def _switch_device():
    """Flask-Login caches the user in ``g``; the fixtures share one app context across requests,
    so a request from another device must start without that cache."""
    from flask import g

    g.pop("_login_user", None)


def _commit(db, *objs):
    for obj in objs:
        db.session.add(obj)
    db.session.commit()


def _items(db, event, list_title, owner_id, names=("Miel", "Sucre")):
    sl = SharedList(title=list_title, list_type="shopping", event_id=event.id)
    db.session.add(sl)
    db.session.commit()
    items = []
    for name in names:
        it = ListItem(name=name, list_id=sl.id, assigned_to_id=owner_id)
        db.session.add(it)
        items.append(it)
    db.session.commit()
    return items


def _household(db, event, owner_id, name):
    h = Household(name=name, event_id=event.id, guest_id=owner_id)
    db.session.add(h)
    db.session.commit()
    return h


class TestDeleteReassignItems:
    def test_delete_reassigns_items_to_target(
        self, db, client, event, guest, other_guest_c, creator, creator_client
    ):
        items = _items(db, event, "Courses", guest.id, names=("Miel", "Sucre", "Farine"))
        resp = creator_client.post(
            f"/e/{event.code}/members",
            data={"action": "delete", "guest_id": guest.id, "reassign_to": other_guest_c.id},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert guest.is_active is False
        for it in items:
            assert it.assigned_to_id == other_guest_c.id

    def test_delete_no_reassign_nulls_items(
        self, db, client, event, guest, creator, creator_client
    ):
        items = _items(db, event, "Courses", guest.id)
        resp = _post_delete(creator_client, event, guest.id, "")
        assert resp.status_code == 302
        assert guest.is_active is False
        for it in items:
            assert it.assigned_to_id is None

    def test_delete_reassigns_meal_and_activity_coverages(
        self, db, client, event, guest, other_guest_c, creator, creator_client
    ):
        sl = SharedList(title="Repas de Noël", list_type="buffet", event_id=event.id)
        meal = Meal(
            title="Dîner", date=date(2026, 12, 25), slot="dinner", position=0, event_id=event.id
        )
        act = Activity(title="Vigil", date=date(2026, 12, 25), event_id=event.id)
        db.session.add(sl)
        db.session.add(meal)
        db.session.add(act)
        db.session.commit()
        meal_cov = ListMealCoverage(list_id=sl.id, meal_id=meal.id, covered_by=guest.id)
        act_cov = ListActivityCoverage(list_id=sl.id, activity_id=act.id, covered_by=guest.id)
        db.session.add(meal_cov)
        db.session.add(act_cov)
        db.session.commit()
        _post_delete(creator_client, event, guest.id, other_guest_c.id)
        assert meal_cov.covered_by == other_guest_c.id
        assert act_cov.covered_by == other_guest_c.id


class TestDeleteHousehold:
    def test_delete_transfers_household_when_target_has_none(
        self, db, client, event, guest, other_guest_c, creator, creator_client
    ):
        hh = _household(db, event, guest.id, "Famille Test")
        exp = Expense(
            description="Courses", amount_cents=5000, paid_by_household_id=hh.id, event_id=event.id
        )
        _commit(db, exp)
        _post_delete(creator_client, event, guest.id, other_guest_c.id)
        assert Household.query.get(hh.id).guest_id == other_guest_c.id
        assert exp.paid_by_household_id == hh.id  # dépenses intactes, foyer transféré

    def test_delete_keeps_source_household_orphaned_when_target_has_one(
        self, db, client, event, guest, other_guest_c, creator, creator_client
    ):
        """R5 : pas de fusion — le foyer source est détaché, jamais supprimé ni recollé."""
        hh_target = _household(db, event, other_guest_c.id, "Famille Cible")
        hh_src = _household(db, event, guest.id, "Famille Test")
        exp_src = Expense(
            description="A", amount_cents=1000, paid_by_household_id=hh_src.id, event_id=event.id
        )
        exp_tgt = Expense(
            description="B", amount_cents=2000, paid_by_household_id=hh_target.id, event_id=event.id
        )
        _commit(db, exp_src, exp_tgt)
        _post_delete(creator_client, event, guest.id, other_guest_c.id)
        assert Household.query.get(hh_src.id) is not None
        assert Household.query.get(hh_src.id).guest_id is None
        assert exp_src.paid_by_household_id == hh_src.id
        assert exp_tgt.paid_by_household_id == hh_target.id
        assert Household.query.get(hh_target.id).guest_id == other_guest_c.id
        assert ActivityLog.query.filter_by(action="household.merged").count() == 0

    def test_delete_no_reassign_keeps_household_orphan(
        self, db, client, event, guest, creator, creator_client
    ):
        hh = _household(db, event, guest.id, "Famille Test")
        exp = Expense(
            description="A", amount_cents=1000, paid_by_household_id=hh.id, event_id=event.id
        )
        _commit(db, exp)
        _post_delete(creator_client, event, guest.id, "")
        assert Household.query.get(hh.id).guest_id is None
        assert exp.paid_by_household_id == hh.id

    def test_costs_index_shows_removed_participant_label(
        self, db, client, event, guest, creator, creator_client
    ):
        hh = _household(db, event, guest.id, "Famille Test")
        exp = Expense(
            description="A", amount_cents=1000, paid_by_household_id=hh.id, event_id=event.id
        )
        _commit(db, exp)
        _post_delete(creator_client, event, guest.id, "")
        # Les cartes « Soldes par foyer » sont dans le segment Équilibre.
        html = creator_client.get(f"/e/{event.code}/costs?tab=balance").get_data(as_text=True)
        assert "Participant retiré" in html
        assert "Famille Test" in html  # le nom du foyer reste visible

    @pytest.mark.parametrize("reassign", ["target", "nobody"])
    def test_delete_preserves_every_settlement(
        self, db, client, event, guest, other_guest_c, creator, creator_client, reassign
    ):
        """R5 : dépenses inégales + Transfer + PaymentRequest ; les soldes ne bougent pas."""
        from app.costs import _settlement

        third = Guest(code="third01", display_name="Troisieme", event_id=event.id)
        _commit(db, third)
        hh_src = _household(db, event, guest.id, "Famille A")
        hh_tgt = _household(db, event, other_guest_c.id, "Famille B")
        hh_third = _household(db, event, third.id, "Famille C")
        tr = Transfer(
            from_household_id=hh_third.id,
            to_household_id=hh_src.id,
            amount_cents=1000,
            event_id=event.id,
        )
        req = PaymentRequest(
            from_household_id=hh_third.id,
            to_household_id=hh_src.id,
            amount_cents=3000,
            event_id=event.id,
        )
        _commit(
            db,
            Expense(
                description="Gîte",
                amount_cents=9000,
                paid_by_household_id=hh_src.id,
                event_id=event.id,
            ),
            Expense(
                description="Courses",
                amount_cents=3000,
                paid_by_household_id=hh_tgt.id,
                event_id=event.id,
            ),
            tr,
            req,
        )

        def settle():
            return _settlement(
                Household.query.filter_by(event_id=event.id).order_by(Household.name).all(),
                Expense.query.filter_by(event_id=event.id).all(),
                Transfer.query.filter_by(event_id=event.id).all(),
            )

        before = settle()
        assert before  # le scénario produit des remboursements
        _post_delete(
            creator_client, event, guest.id, other_guest_c.id if reassign == "target" else ""
        )
        assert settle() == before
        assert Household.query.get(hh_src.id).guest_id is None
        assert Expense.query.filter_by(paid_by_household_id=hh_src.id).count() == 1
        assert Transfer.query.get(tr.id).to_household_id == hh_src.id
        assert PaymentRequest.query.get(req.id).to_household_id == hh_src.id


class TestDeleteWhatIsUntouched:
    def test_delete_votes_and_rsvps_unchanged(
        self, db, client, event, guest, creator, creator_client
    ):
        act = Activity(title="Pique-nique", date=date(2026, 12, 2), event_id=event.id)
        db.session.add(act)
        db.session.commit()
        rsvp = ActivityRSVP(activity_id=act.id, guest_id=guest.id, status="yes")
        poll = Poll(question="Mer ou montagne ?", event_id=event.id)
        db.session.add(poll)
        db.session.commit()
        opt = PollOption(label="Mer", poll_id=poll.id)
        db.session.add(opt)
        db.session.commit()
        vote = PollVote(option_id=opt.id, guest_id=guest.id)
        _commit(db, rsvp, vote)
        _post_delete(creator_client, event, guest.id, "")
        assert rsvp.status == "yes"  # jamais transféré (D4)
        assert PollVote.query.get(vote.id).option_id == opt.id

    def test_delete_history_unchanged(self, db, client, event, guest, creator, creator_client):
        msg = ChatMessage(
            content="Salut tout le monde",
            guest_id=guest.id,
            author_name=guest.display_name,
            author_type="guest",
            event_id=event.id,
        )
        _commit(db, msg)
        _post_delete(creator_client, event, guest.id, "")
        assert ChatMessage.query.get(msg.id).content == "Salut tout le monde"
        # Le journal garde la trace de la suppression.
        assert ActivityLog.query.filter_by(action="participant.deleted").count() == 1

    def test_delete_revokes_push_and_api_keys(
        self, db, client, event, guest, creator, creator_client
    ):
        sub = PushSubscription(
            guest_id=guest.id,
            event_id=event.id,
            endpoint="https://push.example/1",
            p256dh="A" * 66,
            auth="B" * 32,
        )
        _commit(db, sub)
        from app.apikeys import create_api_key

        _key, _ = create_api_key(event, guest=guest)
        db.session.commit()
        _post_delete(creator_client, event, guest.id, "")
        assert PushSubscription.query.count() == 0
        assert ApiKey.query.filter_by(owner_guest_id=guest.id).count() == 0

    def test_delete_deactivates_guest_session(
        self, app, db, client, event, guest, creator, creator_client
    ):
        from tests.test_identity_b038 import _login_guest

        _household(db, event, guest.id, "Famille Test")
        device = app.test_client()  # appareil de l'invité, distinct de celui du créateur
        _login_guest(device, event, guest)
        assert device.get(f"/e/{event.code}").status_code == 200
        _switch_device()
        assert _post_delete(creator_client, event, guest.id, "").status_code == 302
        assert guest.is_active is False
        _switch_device()
        resp = device.get(f"/e/{event.code}")
        # Le profil n'est plus actif : l'appareil est renvoyé sur l'écran de code.
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(f"/e/{event.code}/mycode")


class TestDeleteClearsRecoveryToken:
    """R6a : plus aucun lien en vol pour un profil supprimé/retiré."""

    def _with_token(self, db, guest):
        from app.access import issue_recovery_token

        guest.email = "g@test.com"
        issue_recovery_token(guest)
        db.session.commit()
        assert guest.recovery_token is not None

    def test_delete_clears_token(self, db, client, event, guest, creator, creator_client):
        self._with_token(db, guest)
        _post_delete(creator_client, event, guest.id, "")
        db.session.rollback()
        assert guest.is_active is False
        assert guest.recovery_token is None
        assert guest.recovery_token_expires is None

    def test_remove_clears_token(self, db, client, event, guest, creator, creator_client):
        self._with_token(db, guest)
        creator_client.post(
            f"/e/{event.code}/members", data={"action": "remove", "guest_id": guest.id}
        )
        db.session.rollback()
        assert guest.is_active is False
        assert guest.recovery_token is None
        assert guest.recovery_token_expires is None


class TestDeleteIsTranslated:
    """R6g : flash et détails du journal passent par gettext avec placeholders nommés."""

    FRENCH = ("supprimé", "réattribué", "transféré", "fusionné", "conservé", "désassigné", "foyer")

    def test_delete_with_reassignment_speaks_english(
        self, db, client, event, guest, other_guest_c, creator, creator_client
    ):
        _items(db, event, "Courses", guest.id, names=("Miel", "Sucre"))
        _household(db, event, guest.id, "Famille Test")
        creator_client.post(
            f"/e/{event.code}/members?lang=en",
            data={"action": "delete", "guest_id": guest.id, "reassign_to": other_guest_c.id},
        )
        (flash_msg,) = _flashes(creator_client)
        log = ActivityLog.query.filter_by(action="participant.deleted").one()
        for text in (flash_msg, log.details):
            assert not any(word in text.lower() for word in self.FRENCH), text
        assert guest.display_name in flash_msg
        assert other_guest_c.display_name in flash_msg

    def test_delete_without_reassignment_speaks_english(
        self, db, client, event, guest, creator, creator_client
    ):
        _household(db, event, guest.id, "Famille Test")
        creator_client.post(
            f"/e/{event.code}/members?lang=en",
            data={"action": "delete", "guest_id": guest.id, "reassign_to": ""},
        )
        (flash_msg,) = _flashes(creator_client)
        log = ActivityLog.query.filter_by(action="participant.deleted").one()
        for text in (flash_msg, log.details):
            assert not any(word in text.lower() for word in self.FRENCH), text


class TestDeletePermissions:
    def test_delete_requires_creator(self, db, client, event, guest, other_guest_c, guest_client):
        _household(db, event, guest.id, "Famille Test")
        resp = _post_delete(guest_client, event, guest.id, other_guest_c.id)
        assert resp.status_code == 403
        assert guest.is_active is True

    def test_delete_unknown_guest_404(self, db, client, event, guest, creator, creator_client):
        resp = _post_delete(creator_client, event, "nope", "")
        assert resp.status_code == 404

    def test_delete_cannot_target_creator_participant(
        self, db, client, event, guest, creator_guest, creator, creator_client
    ):
        """Forged POST: the creator's own participant is never deactivated (404)."""
        resp = _post_delete(creator_client, event, creator_guest.id, guest.id)
        assert resp.status_code == 404
        assert creator_guest.is_active is True

    def test_remove_still_works(self, db, client, event, guest, creator, creator_client):
        """Le retrait simple (action=remove) reste disponible et inchangé."""
        _household(db, event, guest.id, "Famille Test")
        resp = creator_client.post(
            f"/e/{event.code}/members",
            data={"action": "remove", "guest_id": guest.id},
        )
        assert resp.status_code == 302
        assert guest.is_active is False

    def test_members_page_offers_delete_sheet(
        self, db, client, event, guest, creator, creator_client
    ):
        html = creator_client.get(f"/e/{event.code}/members").get_data(as_text=True)
        assert 'data-testid="delete-participant"' in html

    def test_delete_flash_reassignment_count(
        self, db, client, event, guest, other_guest_c, creator, creator_client
    ):
        _items(db, event, "Courses", guest.id, names=("Miel", "Sucre"))
        _post_delete(creator_client, event, guest.id, other_guest_c.id)
        # Le récap indique le nombre d'articles transférés et le destinataire.
        (flash_msg,) = _flashes(creator_client)
        assert flash_msg == (
            "Test Guest supprimé·e de l'événement. 2 articles transférés à Other Guest."
        )
        logs = ActivityLog.query.filter_by(action="participant.deleted").all()
        assert len(logs) == 1
        assert other_guest_c.display_name in logs[0].details


# ---------------------------------------------------------------------------
# Suppression d'un foyer avec réaffectation (spec §4.6)
# ---------------------------------------------------------------------------


def _delete_household(client, event, source, target=""):
    return client.post(
        f"/e/{event.code}/costs/households/{source.id}/delete",
        data={"reassign_to": target.id if hasattr(target, "id") else target, "tab": "balance"},
    )


def _net_balances(event):
    """Paid - share + transfers per household id (the quantity _settlement settles)."""
    from app.costs import _base_cents, _per_expense_shares

    households = Household.query.filter_by(event_id=event.id).order_by(Household.name).all()
    shares, paid = _per_expense_shares(households, Expense.query.filter_by(event_id=event.id).all())
    balances = {h.id: paid[h.id] - shares[h.id] for h in households}
    for t in Transfer.query.filter_by(event_id=event.id).all():
        base = _base_cents(t.amount_cents, t.exchange_rate)
        balances[t.from_household_id] += base
        balances[t.to_household_id] -= base
    return balances


class TestDeleteHouseholdReassign:
    @pytest.fixture
    def scene(self, db, event, guest, other_guest_c, creator):
        """S (guest) pays 9000, X (other_guest_c) 3000, T 1500; transfers and requests around S."""
        third = Guest(code="third01", display_name="Troisieme", event_id=event.id)
        _commit(db, third)
        s = _household(db, event, guest.id, "Famille S")
        x = _household(db, event, other_guest_c.id, "Famille X")
        t = _household(db, event, third.id, "Famille T")
        rows = [
            Expense(
                description="Gîte", amount_cents=9000, paid_by_household_id=s.id, event_id=event.id
            ),
            Expense(
                description="Courses",
                amount_cents=3000,
                paid_by_household_id=x.id,
                event_id=event.id,
            ),
            Expense(
                description="Essence",
                amount_cents=1500,
                paid_by_household_id=t.id,
                event_id=event.id,
            ),
            Transfer(
                from_household_id=t.id, to_household_id=s.id, amount_cents=1000, event_id=event.id
            ),
            Transfer(
                from_household_id=x.id, to_household_id=s.id, amount_cents=500, event_id=event.id
            ),
            PaymentRequest(
                from_household_id=t.id, to_household_id=s.id, amount_cents=3000, event_id=event.id
            ),
            PaymentRequest(
                from_household_id=s.id, to_household_id=x.id, amount_cents=200, event_id=event.id
            ),
        ]
        for row in rows:
            db.session.add(row)
        db.session.commit()
        return s, x, t

    def test_shares_are_recomputed_over_the_remaining_households(
        self, db, event, guest, other_guest_c, creator, creator_client, scene
    ):
        """By hand: X and T remain (weight 1 each). Total 13500 -> 6750 each; X paid 9000+3000,
        T paid 1500. Transfer T->S (1000) becomes T->X; X->S (500) becomes X->X and vanishes.
        X = 12000 - 6750 - 1000 = +4250 ; T = 1500 - 6750 + 1000 = -4250."""
        s, x, t = scene
        item = _items(db, event, "Courses", guest.id, names=("Miel",))[0]
        done = _items(db, event, "Autre", guest.id, names=("Sucre",))[0]
        done.is_done = True
        sl = SharedList(title="Repas", list_type="buffet", event_id=event.id)
        meal = Meal(
            title="Dîner", date=date(2026, 12, 2), slot="dinner", position=0, event_id=event.id
        )
        db.session.add_all([sl, meal])
        db.session.commit()
        cov = ListMealCoverage(list_id=sl.id, meal_id=meal.id, covered_by=guest.id)
        _commit(db, cov)
        s_id, x_id, t_id = s.id, x.id, t.id
        resp = _delete_household(creator_client, event, s, x)
        assert resp.status_code == 302
        assert _net_balances(event) == {x_id: 4250, t_id: -4250}
        assert Household.query.get(s_id) is None
        household_x = Household.query.get(x_id)
        assert (household_x.num_adults, household_x.num_children) == (1, 0)  # no absorption
        # Work attached to S's owner (done or not) goes to X's owner.
        assert item.assigned_to_id == other_guest_c.id
        assert done.assigned_to_id == other_guest_c.id
        assert cov.covered_by == other_guest_c.id

    def test_recompute_uses_the_weights_of_the_remaining_households(
        self, db, event, creator, creator_client, scene
    ):
        """By hand: X has 2 adults (weight 2), T weight 1, S's weight 1 disappears.
        Total 13500 -> X 9000, T 4500. X = 12000 - 9000 - 1000 = +2000 ; T = 1500 - 4500 + 1000 = -2000."""
        s, x, t = scene
        x.num_adults = 2
        db.session.commit()
        x_id, t_id = x.id, t.id
        _delete_household(creator_client, event, s, x)
        assert _net_balances(event) == {x_id: 2000, t_id: -2000}

    def test_self_pairs_are_deleted_and_the_rest_moves_to_the_target(
        self, db, event, creator, creator_client, scene
    ):
        s, x, t = scene
        _delete_household(creator_client, event, s, x)
        pairs = {(r.from_household_id, r.to_household_id) for r in Transfer.query.all()}
        reqs = {(r.from_household_id, r.to_household_id) for r in PaymentRequest.query.all()}
        assert pairs == {(t.id, x.id)}
        assert reqs == {(t.id, x.id)}
        assert {e.paid_by_household_id for e in Expense.query.all()} == {x.id, t.id}
        assert Expense.query.filter_by(paid_by_household_id=x.id).count() == 2

    def test_flash_recaps_counts_and_logs_the_merge(
        self, db, event, guest, creator, creator_client, scene
    ):
        s, x, _t = scene
        _items(db, event, "Courses", guest.id, names=("Miel", "Sucre", "Farine"))
        _delete_household(creator_client, event, s, x)
        flash_msg = " ".join(_flashes(creator_client))
        assert "1 dépense" in flash_msg
        assert "3 articles" in flash_msg
        assert "Famille X" in flash_msg
        log = ActivityLog.query.filter_by(action="household.merged").one()
        assert log.target == "Famille X"

    def test_custom_split_key_is_summed_into_the_target(
        self, db, event, creator, creator_client, scene
    ):
        import json

        s, x, t = scene
        exp = Expense.query.filter_by(description="Gîte").one()
        exp.custom_split = json.dumps({s.id: 1.0, x.id: 1.0, t.id: 1.0})
        db.session.commit()
        _delete_household(creator_client, event, s, x)
        assert json.loads(exp.custom_split) == {x.id: 2.0, t.id: 1.0}

    def test_orphan_household_can_be_reassigned(
        self, db, event, guest, other_guest_c, creator, creator_client
    ):
        orphan = _household(db, event, None, "Ancien foyer")
        x = _household(db, event, other_guest_c.id, "Famille X")
        item = _items(db, event, "Courses", guest.id, names=("Miel",))[0]
        exp = Expense(
            description="A", amount_cents=1000, paid_by_household_id=orphan.id, event_id=event.id
        )
        _commit(db, exp)
        orphan_id = orphan.id
        resp = _delete_household(creator_client, event, orphan, x)
        assert resp.status_code == 302
        assert Household.query.get(orphan_id) is None
        assert exp.paid_by_household_id == x.id
        assert item.assigned_to_id == guest.id  # nothing to reassign on the owner side

    def test_target_without_owner_unassigns_the_work(
        self, db, event, guest, creator, creator_client
    ):
        s = _household(db, event, guest.id, "Famille S")
        x = _household(db, event, None, "Foyer orphelin")
        item = _items(db, event, "Courses", guest.id, names=("Miel",))[0]
        _delete_household(creator_client, event, s, x)
        assert item.assigned_to_id is None

    @pytest.mark.parametrize("target", ["other_event", "self", "unknown"])
    def test_forbidden_targets_mutate_nothing(
        self, db, event, other_event, guest, creator, creator_client, scene, target
    ):
        s, x, _t = scene
        foreign = _household(db, other_event, None, "Foyer ailleurs")
        ids = {"other_event": foreign.id, "self": s.id, "unknown": "nope"}
        before = _net_balances(event)
        resp = creator_client.post(
            f"/e/{event.code}/costs/households/{s.id}/delete", data={"reassign_to": ids[target]}
        )
        assert resp.status_code == 404
        assert Household.query.get(s.id) is not None
        assert Household.query.get(x.id).num_adults == 1
        assert Expense.query.filter_by(paid_by_household_id=s.id).count() == 1
        assert _net_balances(event) == before

    def test_non_creator_gets_403_and_nothing_changes(
        self, db, event, guest, other_guest_c, guest_client, scene
    ):
        s, x, _t = scene
        resp = _delete_household(guest_client, event, s, x)
        assert resp.status_code == 403
        assert Household.query.get(s.id) is not None

    def test_without_target_a_used_household_is_still_blocked(
        self, db, event, creator, creator_client, scene
    ):
        s, _x, _t = scene
        _delete_household(creator_client, event, s)
        assert Household.query.get(s.id) is not None
        assert any("supprimez-les d'abord" in m for m in _flashes(creator_client))

    def test_without_target_an_unused_household_is_deleted(
        self, db, event, guest, creator, creator_client
    ):
        s = _household(db, event, guest.id, "Famille S")
        s_id = s.id
        _delete_household(creator_client, event, s)
        assert Household.query.get(s_id) is None
        assert ActivityLog.query.filter_by(action="household.deleted").count() == 1

    def test_edit_sheet_offers_a_labelled_select_of_the_other_households(
        self, db, event, creator, creator_client, scene
    ):
        s, x, _t = scene
        html = creator_client.get(f"/e/{event.code}/costs?edit_household={s.id}").get_data(
            as_text=True
        )
        assert 'name="reassign_to"' in html
        assert 'for="reassign-to"' in html
        select = html[html.index('<select id="reassign-to"') :].split("</select>")[0]
        assert f'<option value="{x.id}"' in select
        assert f'<option value="{s.id}"' not in select
