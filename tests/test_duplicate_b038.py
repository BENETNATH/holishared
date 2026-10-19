"""Tests B038-L3 — anti-doublon au re-join & fusion de profils (WP3).

TDD : écrits AVANT le code (spec ``specs/b038-identity-recovery-spec.md`` §5, §9.3).
Un événement a un seul ``Guest`` par email non nul (actif ou inactif, hors
``merged_into_id``) ; les points d'entrée verrouillés : ``guest_access`` (re-join),
``_add_participant`` (ajout créateur), ``invite_email`` (invitation).
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    ActivityLog,
    Expense,
    Guest,
    Household,
    ListItem,
    PaymentRequest,
    SharedList,
    Transfer,
)

NEUTRAL_JOIN = "Si cette adresse est connue, un lien de connexion vient d'être envoyé."


def _commit(db, *objs):
    for obj in objs:
        db.session.add(obj)
    db.session.commit()


def _flashes(client):
    with client.session_transaction() as s:
        return [msg for _cat, msg in s.get("_flashes", [])]


def _join(client, event, display_name, code, email, follow=True, **extra):
    data = {
        "display_name": display_name,
        "code": code,
        "email": email,
        "num_adults": "1",
        "num_children": "0",
    }
    data.update(extra)
    return client.post(f"/e/{event.code}/join", data=data, follow_redirects=follow)


def _new_items(db, event, owner_id, names):
    sl = SharedList(title="Courses L3", list_type="shopping", event_id=event.id)
    db.session.add(sl)
    db.session.commit()
    items = [ListItem(name=name, list_id=sl.id, assigned_to_id=owner_id) for name in names]
    for it in items:
        db.session.add(it)
    db.session.commit()
    return items


def _household(db, event, owner_id, name):
    h = Household(name=name, event_id=event.id, guest_id=owner_id)
    db.session.add(h)
    db.session.commit()
    return h


def _ledger(db, event, hh_a, hh_b, hh_c):
    """Dépenses inégales + un Transfer + une PaymentRequest (tous vers/depuis ``hh_a``)."""
    rows = [
        Expense(
            description="Gîte", amount_cents=9000, paid_by_household_id=hh_a.id, event_id=event.id
        ),
        Expense(
            description="Courses",
            amount_cents=3000,
            paid_by_household_id=hh_b.id,
            event_id=event.id,
        ),
        Transfer(
            from_household_id=hh_c.id,
            to_household_id=hh_a.id,
            amount_cents=1000,
            event_id=event.id,
        ),
        PaymentRequest(
            from_household_id=hh_c.id,
            to_household_id=hh_a.id,
            amount_cents=3000,
            event_id=event.id,
        ),
    ]
    for row in rows:
        db.session.add(row)
    db.session.commit()


def _settle(event):
    from app.costs import _settlement

    return _settlement(
        Household.query.filter_by(event_id=event.id).order_by(Household.name).all(),
        Expense.query.filter_by(event_id=event.id).all(),
        Transfer.query.filter_by(event_id=event.id).all(),
    )


# ---------------------------------------------------------------------------
# Re-join (guest_access) — unicité logique de l'email
# ---------------------------------------------------------------------------


class TestJoinDuplicateEmail:
    """R3 : e-mail déjà connu (actif OU retiré) => réponse neutre, aucune fuite, aucune création."""

    def _post_known(self, client, event, email="dup@test.com", **extra):
        return _join(client, event, "Nouveau", "newg123", email, follow=False, **extra)

    def test_known_active_email_gets_neutral_redirect_without_creation(
        self, client, db, event, guest, queue
    ):
        guest.email = "dup@test.com"
        _commit(db)
        before = Guest.query.filter_by(event_id=event.id).count()
        resp = self._post_known(client, event)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(f"/e/{event.code}/join")
        assert _flashes(client) == [NEUTRAL_JOIN]
        assert Guest.query.filter_by(event_id=event.id).count() == before
        assert Guest.query.filter_by(event_id=event.id, code="newg123").first() is None
        with client.session_transaction() as s:
            assert f"guest_{event.code}" not in s

    def test_known_active_email_gets_a_hashed_persisted_login_link(
        self, client, db, event, guest, queue
    ):
        import hashlib

        guest.email = "dup@test.com"
        _commit(db)
        self._post_known(client, event)
        db.session.rollback()  # R2 : seul le committé survit
        assert len(queue.guest_recovery()) == 1
        email, _title, link = queue.guest_recovery()[0]
        raw = link.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        assert email == "dup@test.com"
        assert f"/e/{event.code}/guest-recover/" in link
        assert guest.recovery_token == hashlib.sha256(raw.encode()).hexdigest()

    def test_known_active_email_gets_one_link_per_cooldown_window(
        self, client, db, event, guest, queue
    ):
        """Anti mail-bomb : un 2e join < 5 min plus tard n'envoie rien et ne ré-émet aucun token."""
        guest.email = "dup@test.com"
        _commit(db)
        self._post_known(client, event)
        token = guest.recovery_token
        resp = self._post_known(client, event)
        db.session.rollback()
        assert resp.status_code == 302
        assert _flashes(client) == [NEUTRAL_JOIN] * 2  # same neutral answer both times
        assert len(queue.guest_recovery()) == 1
        assert guest.recovery_token == token

    def test_known_active_email_never_flashes_the_live_link_even_in_debug(
        self, app, client, db, event, guest
    ):
        """R3 : même avec DEV_SHOW_SECRETS + debug, la réponse reste la neutre (pas de lien)."""
        guest.email = "dup@test.com"
        _commit(db)
        app.config["SMTP_HOST"] = ""
        app.config["DEV_SHOW_SECRETS"] = True
        app.debug = True
        resp = self._post_known(client, event)
        assert resp.status_code == 302
        assert _flashes(client) == [NEUTRAL_JOIN]
        assert "/guest-recover/" not in client.get(f"/e/{event.code}/join").get_data(as_text=True)

    def test_known_email_links_are_capped_per_ip_without_changing_the_response(
        self, client, db, event, queue
    ):
        """Un seul IP ne peut pas mitrailler d'e-mails : au-delà de 10/h, plus d'envoi, même réponse."""
        members = [
            Guest(
                code=f"cap{i:02d}",
                display_name=f"Cap {i}",
                email=f"c{i}@test.com",
                event_id=event.id,
            )
            for i in range(12)
        ]
        db.session.add_all(members)
        db.session.commit()
        responses = [self._post_known(client, event, email=f"c{i}@test.com") for i in range(12)]
        assert all(r.status_code == 302 for r in responses)
        assert all(r.headers["Location"].endswith(f"/e/{event.code}/join") for r in responses)
        assert len(queue.guest_recovery()) == 10

    def test_known_email_response_identical_for_active_and_retired(
        self, app, db, event, guest, other_guest_c, queue
    ):
        guest.email = "active@test.com"
        other_guest_c.email = "retired@test.com"
        other_guest_c.is_active = False
        _commit(db)
        before = Guest.query.filter_by(event_id=event.id).count()
        c_active, c_retired = app.test_client(), app.test_client()
        r_active = self._post_known(c_active, event, "active@test.com")
        r_retired = self._post_known(c_retired, event, "retired@test.com")
        assert (r_active.status_code, r_active.headers["Location"]) == (
            r_retired.status_code,
            r_retired.headers["Location"],
        )
        assert _flashes(c_active) == _flashes(c_retired) == [NEUTRAL_JOIN]
        assert Guest.query.filter_by(event_id=event.id).count() == before

    def test_retired_email_sends_nothing_and_stays_retired(self, client, db, event, guest, queue):
        guest.email = "dup@test.com"
        guest.is_active = False
        _commit(db)
        self._post_known(client, event)
        db.session.rollback()
        assert queue.jobs == []
        assert guest.recovery_token is None
        assert guest.is_active is False
        with client.session_transaction() as s:
            assert f"guest_{event.code}" not in s

    @pytest.mark.parametrize("retired", [False, True])
    def test_known_email_leaks_nothing(self, client, db, event, guest, retired):
        guest.display_name = "Zorglub Unique"
        guest.email = "dup@test.com"
        guest.is_active = not retired
        _new_items(db, event, guest.id, ("Miel", "Sucre"))
        _household(db, event, guest.id, "Famille Zorglub")
        posted = self._post_known(client, event)
        page = client.get(f"/e/{event.code}/join").get_data(as_text=True)
        for body in (posted.get_data(as_text=True), page):
            assert "Zorglub" not in body  # ni pseudo ni foyer
            assert guest.id not in body
            assert guest.code not in body
            masked = guest.code[:1] + "*" * (len(guest.code) - 1)
            assert masked not in body  # pas d'indice sur le code
            assert 'name="guest_id"' not in body
            assert 'data-testid="merge-existing"' not in body
            assert 'data-testid="dup-profile"' not in body
            assert 'value="merge"' not in body
            assert 'value="new"' not in body
            assert "article(s)" not in body

    @pytest.mark.parametrize("action", ["merge", "new"])
    def test_legacy_merge_and_new_actions_are_ignored(self, client, db, event, guest, action):
        guest.email = "dup@test.com"
        guest.is_active = False
        _commit(db)
        before = Guest.query.filter_by(event_id=event.id).count()
        resp = self._post_known(
            client, event, action=action, guest_id=guest.id, email_suppressed="1"
        )
        db.session.rollback()
        assert resp.status_code == 302
        assert _flashes(client) == [NEUTRAL_JOIN]
        assert guest.is_active is False
        assert Guest.query.filter_by(event_id=event.id).count() == before
        assert Guest.query.filter_by(event_id=event.id, code="newg123").first() is None

    def test_unknown_email_still_creates_the_profile(self, client, db, event, guest):
        resp = _join(client, event, "Nouveau", "newg123", "fresh@test.com", follow=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(f"/e/{event.code}")
        created = Guest.query.filter_by(event_id=event.id, code="newg123").first()
        assert created is not None
        assert created.email == "fresh@test.com"

    def test_join_race_on_unique_index_gives_the_neutral_response(
        self, client, db, event, guest, monkeypatch
    ):
        """R6e : la course (contrôle applicatif contourné) est rattrapée par l'index."""
        guest.email = "dup@test.com"
        _commit(db)
        monkeypatch.setattr("app.events._email_guest", lambda *a, **k: None)
        resp = self._post_known(client, event)
        db.session.rollback()
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(f"/e/{event.code}/join")
        assert Guest.query.filter_by(event_id=event.id, email="dup@test.com").count() == 1


# ---------------------------------------------------------------------------
# Ajout par le créateur (_add_participant)
# ---------------------------------------------------------------------------


class TestAddParticipantDuplicateEmail:
    def test_add_participant_duplicate_email_rejected(
        self, client, db, event, guest, creator, creator_client
    ):
        guest.email = "dup@test.com"
        _commit(db)
        before = Guest.query.filter_by(event_id=event.id, creator_id=None).count()
        resp = creator_client.post(
            f"/e/{event.code}/members",
            data={"action": "add", "display_name": "Dup", "email": "dup@test.com"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert Guest.query.filter_by(event_id=event.id, creator_id=None).count() == before
        assert "Cette adresse a déjà un profil dans cet événement." in resp.get_data(as_text=True)

    def test_add_participant_duplicate_inactive_email_rejected(
        self, client, db, event, guest, other_guest_c, creator, creator_client
    ):
        other_guest_c.email = "dup@test.com"
        other_guest_c.is_active = False
        _commit(db)
        before = Guest.query.filter_by(event_id=event.id, creator_id=None).count()
        resp = creator_client.post(
            f"/e/{event.code}/members",
            data={"action": "add", "display_name": "Dup", "email": "dup@test.com"},
        )
        assert resp.status_code == 200
        assert Guest.query.filter_by(event_id=event.id, creator_id=None).count() == before
        assert "Cette adresse a déjà un profil dans cet événement." in resp.get_data(as_text=True)

    def test_add_participant_race_on_unique_index_is_a_field_error_not_a_500(
        self, client, db, event, guest, creator, creator_client, monkeypatch
    ):
        """R6e : contrôle applicatif contourné => IntegrityError rattrapée proprement."""
        guest.email = "dup@test.com"
        _commit(db)
        monkeypatch.setattr("app.events._email_guest", lambda *a, **k: None)
        resp = creator_client.post(
            f"/e/{event.code}/members",
            data={"action": "add", "display_name": "Dup", "email": "dup@test.com"},
        )
        db.session.rollback()
        assert resp.status_code == 200
        assert "Cette adresse a déjà un profil dans cet événement." in resp.get_data(as_text=True)
        assert Guest.query.filter_by(event_id=event.id, email="dup@test.com").count() == 1


# ---------------------------------------------------------------------------
# Invitation par email (invite_email)
# ---------------------------------------------------------------------------


class TestInviteEmailDuplicate:
    def test_invite_email_active_profile_no_send(
        self, client, db, event, guest, creator, creator_client, queue
    ):
        guest.email = "dup@test.com"
        _commit(db)
        resp = creator_client.post(
            f"/e/{event.code}/invite/email", data={"email": "dup@test.com"}, follow_redirects=True
        )
        assert resp.status_code == 200
        assert "participe déjà à cet événement" in resp.get_data(as_text=True)
        db.session.rollback()
        # Ni invitation ni lien de récupération envoyés, aucun token.
        assert queue.jobs == []
        assert guest.recovery_token is None

    def test_invite_email_retired_profile_sends_nothing_and_does_not_reactivate(
        self, client, db, event, guest, creator, creator_client, queue
    ):
        """R4 : pas d'auto-réactivation ; le créateur doit utiliser « Réinviter »."""
        guest.email = "dup@test.com"
        guest.is_active = False
        _commit(db)
        resp = creator_client.post(f"/e/{event.code}/invite/email", data={"email": "dup@test.com"})
        db.session.rollback()
        assert resp.status_code == 302
        assert _flashes(creator_client) == [
            "Un profil retiré existe pour cette adresse : utilisez « Réinviter » dans les "
            "participants retirés."
        ]
        assert queue.jobs == []
        assert guest.recovery_token is None
        assert guest.is_active is False


# ---------------------------------------------------------------------------
# Badge « email dupliqué » + fusion de profils (merge_profiles)
# ---------------------------------------------------------------------------


@pytest.fixture
def legacy_duplicates(db):
    """Les doublons d'email n'existent que sur des données antérieures à l'index unique."""
    db.session.execute(db.text("DROP INDEX IF EXISTS uq_guest_event_email_active"))
    db.session.commit()


@pytest.mark.usefixtures("legacy_duplicates")
class TestMergeProfiles:
    def test_members_shows_duplicate_email_badge(
        self, client, db, event, guest, other_guest_c, creator, creator_client
    ):
        guest.email = "dup@test.com"
        other_guest_c.email = "dup@test.com"
        _commit(db)
        html = creator_client.get(f"/e/{event.code}/members").get_data(as_text=True)
        assert html.count('data-testid="duplicate-email-badge"') == 2

    def test_merge_profiles_migrates_items_and_household(
        self, client, db, event, guest, other_guest_c, creator, creator_client
    ):
        """source=guest (absorbé), target=other_guest_c (conservé)."""
        from app.access import issue_recovery_token

        guest.email = other_guest_c.email = "dup@test.com"
        issue_recovery_token(guest)
        items = _new_items(db, event, guest.id, ("Miel", "Sucre"))
        hh_src = _household(db, event, guest.id, "Famille Source")
        hh_tgt = _household(db, event, other_guest_c.id, "Famille Cible")
        exp = Expense(
            description="A", amount_cents=1000, paid_by_household_id=hh_src.id, event_id=event.id
        )
        _commit(db, exp)
        resp = creator_client.post(
            f"/e/{event.code}/members",
            data={
                "action": "merge_profiles",
                "source_id": guest.id,
                "target_id": other_guest_c.id,
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        for it in items:
            assert it.assigned_to_id == other_guest_c.id
        # R5 : le foyer source n'est pas supprimé, il est détaché ; ses liens restent.
        assert Household.query.get(hh_src.id) is not None
        assert Household.query.get(hh_src.id).guest_id is None
        assert exp.paid_by_household_id == hh_src.id
        assert Household.query.get(hh_tgt.id).guest_id == other_guest_c.id
        assert ActivityLog.query.filter_by(action="household.merged").count() == 0
        # Source absorbé : inactif, marqué, email effacé.
        assert guest.merged_into_id == other_guest_c.id
        assert guest.is_active is False
        assert guest.email is None
        assert guest.recovery_token is None  # plus de lien en vol pour le profil absorbé
        # L'identité du profil conservé est intacte.
        assert other_guest_c.display_name == "Other Guest"
        assert ActivityLog.query.filter_by(action="participant.merged").count() == 1

    def test_retired_and_active_duplicates_are_visible_and_mergeable_then_index_is_created(
        self, client, db, event, guest, other_guest_c, creator, creator_client
    ):
        """Legacy C4 case: a retired profile and an active one share an address."""
        from app.migrations import migrate_guest_email_unique

        guest.email = other_guest_c.email = "dup@test.com"
        guest.is_active = False  # retired
        _commit(db)
        assert migrate_guest_email_unique(db.engine) == 0  # duplicates block the index
        html = creator_client.get(f"/e/{event.code}/members").get_data(as_text=True)
        assert html.count('data-testid="duplicate-email-badge"') == 2  # active row + retired row
        form = html[html.index('data-testid="merge-profiles-form"') :].split("</form>")[0]
        source = form.split('name="source_id"')[1].split("</select>")[0]
        target = form.split('name="target_id"')[1].split("</select>")[0]
        assert f'value="{guest.id}"' in source  # the retired profile can be absorbed
        assert f'value="{guest.id}"' not in target  # but never kept
        assert "dup@test.com" not in form  # address masked in the explanation
        resp = creator_client.post(
            f"/e/{event.code}/members",
            data={
                "action": "merge_profiles",
                "source_id": guest.id,
                "target_id": other_guest_c.id,
            },
        )
        assert resp.status_code == 302
        assert guest.merged_into_id == other_guest_c.id
        assert migrate_guest_email_unique(db.engine) == 1

    def test_two_retired_duplicates_can_be_merged_from_the_members_page(
        self, client, db, event, guest, other_guest_c, creator, creator_client
    ):
        """Legacy retired/retired pair: a form on each retired row, targets active or retired."""
        from app.migrations import migrate_guest_email_unique

        guest.email = other_guest_c.email = "dup@test.com"
        guest.is_active = other_guest_c.is_active = False
        _commit(db)
        assert migrate_guest_email_unique(db.engine) == 0
        html = creator_client.get(f"/e/{event.code}/members").get_data(as_text=True)
        assert html.count('data-testid="retired-merge-form"') == 2
        form = html[html.index('data-testid="retired-merge-form"') :].split("</form>")[0]
        assert "dup@test.com" not in form  # address masked
        assert '<label class="block text-small text-ink-2" for="retired-merge-target-' in form
        first_target = form.split('name="target_id"')[1].split("</select>")[0]
        assert (
            f'value="{guest.id}"' in first_target or f'value="{other_guest_c.id}"' in first_target
        )
        resp = creator_client.post(
            f"/e/{event.code}/members",
            data={
                "action": "merge_profiles",
                "source_id": guest.id,
                "target_id": other_guest_c.id,
            },
        )
        assert resp.status_code == 302
        assert guest.merged_into_id == other_guest_c.id
        assert migrate_guest_email_unique(db.engine) == 1

    def test_merge_profiles_preserves_settlements(
        self, client, db, event, guest, other_guest_c, creator, creator_client
    ):
        """R5 : dépenses inégales + Transfer + PaymentRequest, soldes identiques après fusion."""
        guest.email = other_guest_c.email = "dup@test.com"
        third = Guest(code="third01", display_name="Troisieme", event_id=event.id)
        _commit(db, third)
        hh_src = _household(db, event, guest.id, "Famille Source")
        hh_tgt = _household(db, event, other_guest_c.id, "Famille Cible")
        hh_third = _household(db, event, third.id, "Famille Tierce")
        _ledger(db, event, hh_src, hh_tgt, hh_third)
        before = _settle(event)
        resp = creator_client.post(
            f"/e/{event.code}/members",
            data={
                "action": "merge_profiles",
                "source_id": guest.id,
                "target_id": other_guest_c.id,
            },
        )
        assert resp.status_code == 302
        assert guest.merged_into_id == other_guest_c.id
        assert _settle(event) == before
        assert before  # le scénario produit bien des remboursements
        assert Household.query.get(hh_src.id) is not None
        assert Transfer.query.filter_by(event_id=event.id).first().to_household_id == hh_src.id
        assert PaymentRequest.query.filter_by(event_id=event.id).first().to_household_id == (
            hh_src.id
        )

    def test_merge_profiles_rejects_different_emails(
        self, client, db, event, guest, other_guest_c, creator, creator_client
    ):
        guest.email = "a@test.com"
        other_guest_c.email = "b@test.com"
        _commit(db)
        creator_client.post(
            f"/e/{event.code}/members",
            data={
                "action": "merge_profiles",
                "source_id": guest.id,
                "target_id": other_guest_c.id,
            },
        )
        assert guest.merged_into_id is None
        assert guest.is_active is True

    def test_merge_profiles_rejects_active_source_into_inactive_target(
        self, client, db, event, guest, other_guest_c, creator, creator_client
    ):
        """R6c, POST forgé : un profil actif ne peut pas être absorbé par un profil retiré."""
        guest.email = other_guest_c.email = "dup@test.com"
        other_guest_c.is_active = False
        _commit(db)
        resp = creator_client.post(
            f"/e/{event.code}/members",
            data={
                "action": "merge_profiles",
                "source_id": guest.id,
                "target_id": other_guest_c.id,
            },
        )
        db.session.rollback()
        assert resp.status_code == 422
        assert guest.merged_into_id is None
        assert guest.is_active is True
        assert guest.email == "dup@test.com"
        assert other_guest_c.is_active is False

    @pytest.mark.parametrize("target_active", [True, False])
    def test_merge_profiles_accepts_inactive_source(
        self, client, db, event, guest, other_guest_c, creator, creator_client, target_active
    ):
        """Spec §5.5 : source retiré permis, cible active ou non."""
        guest.email = other_guest_c.email = "dup@test.com"
        guest.is_active = False
        other_guest_c.is_active = target_active
        _commit(db)
        resp = creator_client.post(
            f"/e/{event.code}/members",
            data={
                "action": "merge_profiles",
                "source_id": guest.id,
                "target_id": other_guest_c.id,
            },
        )
        db.session.rollback()
        assert resp.status_code == 302
        assert guest.merged_into_id == other_guest_c.id
        assert guest.is_active is False

    def test_merge_profiles_rejects_creator_participant(
        self, client, db, event, guest, creator_guest, creator, creator_client
    ):
        guest.email = creator_guest.email = "dup@test.com"
        _commit(db)
        creator_client.post(
            f"/e/{event.code}/members",
            data={
                "action": "merge_profiles",
                "source_id": guest.id,
                "target_id": creator_guest.id,
            },
        )
        assert guest.merged_into_id is None

    def test_merge_profiles_requires_creator(
        self, client, db, event, guest, other_guest_c, guest_client
    ):
        guest.email = other_guest_c.email = "dup@test.com"
        _commit(db)
        resp = guest_client.post(
            f"/e/{event.code}/members",
            data={
                "action": "merge_profiles",
                "source_id": guest.id,
                "target_id": other_guest_c.id,
            },
        )
        assert resp.status_code == 403
        assert guest.merged_into_id is None


# ---------------------------------------------------------------------------
# Exclusion des profils fusionnés
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("legacy_duplicates")
class TestMergedExclusion:
    def _merge(self, client, db, event, guest, other_guest_c, creator, creator_client):
        # Nom d'affichage unique (sinon « Guest » est sous-chaîne de « Other Guest »).
        guest.display_name = "Absorbe"
        guest.email = other_guest_c.email = "dup@test.com"
        _commit(db)
        creator_client.post(
            f"/e/{event.code}/members",
            data={
                "action": "merge_profiles",
                "source_id": guest.id,
                "target_id": other_guest_c.id,
            },
        )

    def test_merged_guest_excluded_from_members_and_api(
        self, client, db, event, guest, other_guest_c, creator, creator_client
    ):
        self._merge(client, db, event, guest, other_guest_c, creator, creator_client)
        # First GET: consumes the "fusionné" flash (intentional, not a participant).
        creator_client.get(f"/e/{event.code}/members")
        html = creator_client.get(f"/e/{event.code}/members").get_data(as_text=True)
        assert guest.display_name not in html
        # API v1 : le profil absorbé n'apparaît plus.
        from app.apikeys import create_api_key

        _, key = create_api_key(event, creator=creator)
        body = client.get(
            f"/api/events/{event.code}", headers={"Authorization": f"Bearer {key}"}
        ).get_data(as_text=True)
        assert guest.display_name not in body

    def test_guest_count_ignores_merged(
        self, client, db, event, guest, other_guest_c, creator, creator_client
    ):
        self._merge(client, db, event, guest, other_guest_c, creator, creator_client)
        active = Guest.query.filter_by(event_id=event.id, is_active=True).count()
        assert active == 2  # Test Guest (absorbé, inactif) + Other Guest
        assert event.guest_count == active
        assert guest.merged_into_id == other_guest_c.id


# ---------------------------------------------------------------------------
# Index unique partiel (event_id, email) — R6e
# ---------------------------------------------------------------------------


class TestEmailUniqueIndex:
    def test_model_declares_the_partial_unique_index(self, db):
        from sqlalchemy import inspect

        indexes = {ix["name"]: ix for ix in inspect(db.engine).get_indexes("guests")}
        assert "uq_guest_event_email_active" in indexes
        assert indexes["uq_guest_event_email_active"]["unique"]
        assert indexes["uq_guest_event_email_active"]["column_names"] == ["event_id", "email"]

    def test_second_profile_with_same_email_is_rejected_by_the_database(self, db, event):
        db.session.add(Guest(code="aaaa1", display_name="A", email="x@test.com", event_id=event.id))
        db.session.commit()
        db.session.add(Guest(code="bbbb2", display_name="B", email="x@test.com", event_id=event.id))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_retired_profile_still_blocks_a_duplicate(self, db, event):
        db.session.add(
            Guest(
                code="aaaa1",
                display_name="A",
                email="x@test.com",
                event_id=event.id,
                is_active=False,
            )
        )
        db.session.commit()
        db.session.add(Guest(code="bbbb2", display_name="B", email="x@test.com", event_id=event.id))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_index_does_not_block_legitimate_duplicates(
        self, db, event, other_event, guest, creator
    ):
        first = Guest(code="aaaa1", display_name="A", email="x@test.com", event_id=event.id)
        db.session.add(first)
        db.session.commit()
        db.session.add_all(
            [
                # même adresse dans un autre événement
                Guest(code="bbbb2", display_name="B", email="x@test.com", event_id=other_event.id),
                # profil absorbé (merged_into_id non nul)
                Guest(
                    code="cccc3",
                    display_name="C",
                    email="x@test.com",
                    event_id=event.id,
                    is_active=False,
                    merged_into_id=first.id,
                ),
                # participant créateur
                Guest(
                    code="dddd4",
                    display_name="D",
                    email="x@test.com",
                    event_id=event.id,
                    creator_id=creator.id,
                ),
                # e-mails absents
                Guest(code="eeee5", display_name="E", email=None, event_id=event.id),
                Guest(code="ffff6", display_name="F", email=None, event_id=event.id),
            ]
        )
        db.session.commit()
        assert Guest.query.filter_by(email="x@test.com").count() == 4


# ---------------------------------------------------------------------------
# i18n — chaînes L3
# ---------------------------------------------------------------------------


class TestL3I18n:
    MSGIDS = (
        "Cette adresse a déjà un profil dans cet événement.",
        "Si cette adresse est connue, un lien de connexion vient d'être envoyé.",
        "Un profil actif ne peut pas être fusionné dans un profil retiré.",
        "Un profil retiré existe pour cette adresse : utilisez « Réinviter » dans les "
        "participants retirés.",
        "%(name)s a été réinvité·e.",
    )

    @staticmethod
    def _catalog(lang):
        import gettext
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent / "translations"
        return gettext.translation("messages", str(root), languages=[lang])

    def test_b038_l3_strings_translated_to_english(self):
        cat = self._catalog("en")
        for msgid in self.MSGIDS:
            assert cat.gettext(msgid) != msgid, msgid

    def test_b038_l3_strings_are_french_source_in_fr(self):
        cat = self._catalog("fr")
        for msgid in self.MSGIDS:
            assert cat.gettext(msgid) == msgid, msgid
