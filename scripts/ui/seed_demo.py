"""Disposable demo database for the UI guard (B017, spec §9.2).

Creates, OUTSIDE the repository, a SQLite database, an ``instance_path`` and
``fixtures.json`` (signed session cookies per role, placeholders).

CLI : python scripts/ui/seed_demo.py [--out DIR] [--port N]
"""

import argparse
import json
import os
import secrets
import shutil
import sys
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEMO_DIR = Path(tempfile.gettempdir()) / "holishared-ui" / "demo"
LONG_TITLE = (
    "Réveillon de la Saint-Sylvestre chez Jean-Baptiste, Marie-Charlotte et toute la "
    "famille Delacroix-Montgomery à Saint-Rémy-de-Provence"
)


def demo_env(out_dir: Path, secret_key: str, superadmin_password: str, port: int) -> dict[str, str]:
    """Environment of the demo app (wins over the developer's ``.env``)."""
    return {
        "SECRET_KEY": secret_key,
        "SUPERADMIN_EMAIL": "admin@demo.invalid",
        "SUPERADMIN_PASSWORD": superadmin_password,
        "DATABASE_URL": f"sqlite:///{Path(out_dir).resolve() / 'demo.db'}",
        "ENABLED_MODULES": "planning,meals,lists,logistics,voting,media,chat,costs",
        "MAX_GUESTS_PER_EVENT": "10",
        "MAX_DURATION_DAYS": "30",
        "MAX_EVENTS_PER_CREATOR": "10",
        "SESSION_COOKIE_SECURE": "false",
        "REDIS_URL": "",
        "SMTP_HOST": "",
        "SMTP_USER": "",
        "SMTP_PASSWORD": "",
        "DEFAULT_LANGUAGE": "fr",
        "SUPPORTED_LANGUAGES": "fr,en",
        "APP_URL": f"http://127.0.0.1:{port}",
        "UI_CATALOG_ENABLED": "true",
        "SW_ENABLED": "true",
    }


def _reset(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("demo.db", "demo.db-wal", "demo.db-shm", "fixtures.json"):
        (out_dir / name).unlink(missing_ok=True)
    shutil.rmtree(out_dir / "instance", ignore_errors=True)


def _populate_rich(db: Any, models: Any, rich: Any, creator_guest: Any) -> dict[str, Any]:
    """Full content of the ``rich`` event; returns the objects used later."""
    m = models
    today = date.today()
    guests = {}
    for name, code in (
        ("Antoine", "antoine1"),
        ("Chloé", "chloe001"),
        ("Dimitri", "dimitri1"),
        ("Béatrice", "beatrice"),
    ):
        guests[name] = m.Guest(code=code, display_name=name, event_id=rich.id)
        db.session.add(guests[name])
    db.session.flush()
    antoine, chloe = guests["Antoine"], guests["Chloé"]
    antoine_household = m.Household(
        name="Antoine and Bea", num_adults=2, guest_id=antoine.id, event_id=rich.id
    )
    db.session.add(antoine_household)

    for title, offset, start, extra in (
        (
            "Randonnée Grande Moucherolle",
            0,
            time(9, 0),
            {
                "description": "Départ du parking de la Molière.",
                "location": "Corrençon-en-Vercors",
                "bring_items": "Eau, chaussures de marche, pique-nique",
                "min_headcount": 3,
            },
        ),
        ("Piscine", 1, time(14, 30), {}),
        ("Visite des grottes de Choranche", 2, None, {}),
        ("Soirée jeux de société", 2, time(21, 0), {}),
    ):
        db.session.add(
            m.Activity(
                title=title,
                date=today + timedelta(days=offset),
                start_time=start,
                created_by=antoine.id,
                event_id=rich.id,
                **extra,
            )
        )

    db.session.flush()
    hike = m.Activity.query.filter_by(event_id=rich.id).order_by(m.Activity.date).first()
    for who, status in ((antoine, "yes"), (chloe, "yes"), (guests["Dimitri"], "maybe")):
        db.session.add(m.ActivityRSVP(activity_id=hike.id, guest_id=who.id, status=status))
    meal_titles = ("Raclette", "Pique-nique", "Spaghetti pesto")
    index = 0
    for offset in range(-1, 5):
        slots = ["lunch", "dinner"] if offset % 2 == 0 else ["dinner"]
        for slot in slots:
            db.session.add(
                m.Meal(
                    title=meal_titles[index % 3],
                    date=today + timedelta(days=offset),
                    slot=slot,
                    created_by=antoine.id,
                    event_id=rich.id,
                )
            )
            index += 1
    # Plusieurs repas dans une même case (B022) : aujourd'hui, midi.
    db.session.add(
        m.Meal(
            title="Salade de fruits",
            date=today,
            slot="lunch",
            position=1,
            created_by=antoine.id,
            event_id=rich.id,
        )
    )

    shopping = m.SharedList(title="Courses", list_type="shopping", event_id=rich.id)
    db.session.add(shopping)
    db.session.flush()
    for item in (
        {"name": "Pâtes", "quantity": "2", "section": "Épicerie", "created_by": antoine.id},
        {"name": "Fromage à raclette", "section": "Crèmerie", "created_by": chloe.id},
        {"name": "Pain", "section": "Boulangerie", "created_by": antoine.id},
        {
            "name": "Vin rouge",
            "assigned_to": "Antoine",
            "assigned_to_id": antoine.id,
            "created_by": antoine.id,
        },
        {"name": "Sel", "is_done": True, "section": "Épicerie", "created_by": chloe.id},
    ):
        db.session.add(m.ListItem(list_id=shopping.id, **item))
    # Couverture (B023) : la liste de courses prend en compte les trois premiers repas et une activité.
    first_meals = (
        m.Meal.query.filter_by(event_id=rich.id).order_by(*m.Meal.ordering()).limit(3).all()
    )
    for meal in first_meals:
        db.session.add(
            m.ListMealCoverage(list_id=shopping.id, meal_id=meal.id, covered_by=antoine.id)
        )
    first_activity = m.Activity.query.filter_by(event_id=rich.id).order_by(m.Activity.date).first()
    db.session.add(
        m.ListActivityCoverage(
            list_id=shopping.id, activity_id=first_activity.id, covered_by=antoine.id
        )
    )

    # Liste annexe (B023) : les scènes qui modifient des articles (cocher, supprimer puis annuler) s'y limitent.
    packing = m.SharedList(title="Valise", list_type="packing", event_id=rich.id)
    db.session.add(packing)
    db.session.flush()
    for name in ("Maillot de bain", "Crème solaire"):
        db.session.add(m.ListItem(list_id=packing.id, name=name, created_by=antoine.id))

    poll = m.Poll(question="Quel jour pour la grande randonnée ?", event_id=rich.id)
    db.session.add(poll)
    db.session.flush()
    options = []
    for order, label in enumerate(("Mardi", "Mercredi", "Jeudi")):
        option = m.PollOption(label=label, order=order, poll_id=poll.id)
        db.session.add(option)
        options.append(option)
    db.session.flush()
    db.session.add(m.PollVote(option_id=options[1].id, guest_id=antoine.id))

    # Sondage d'activités ouvert (B025) : badge « En vote » dans le Planning, Antoine n'a pas voté.
    pool = m.Activity.query.filter_by(event_id=rich.id, title="Piscine").one()
    caves = m.Activity.query.filter_by(event_id=rich.id, title="Visite des grottes de Choranche").one()
    activities_poll = m.Poll(
        question="Quelle activité pour mardi ?",
        kind="activities",
        created_by=antoine.id,
        event_id=rich.id,
    )
    db.session.add(activities_poll)
    db.session.flush()
    for order, act in enumerate((pool, caves)):
        db.session.add(
            m.PollOption(label=act.title, order=order, poll_id=activities_poll.id, activity_id=act.id)
        )
    # Sondage clos (B025) : résultats visibles à tous, option gagnante mise en évidence.
    closed = m.Poll(question="Où dîner samedi ?", is_closed=True, event_id=rich.id)
    db.session.add(closed)
    db.session.flush()
    closed_options = []
    for order, label in enumerate(("Pizzeria", "Crêperie")):
        option = m.PollOption(label=label, order=order, poll_id=closed.id)
        db.session.add(option)
        closed_options.append(option)
    db.session.flush()
    for who, pick in ((antoine, 0), (chloe, 0), (guests["Dimitri"], 1)):
        db.session.add(m.PollVote(option_id=closed_options[pick].id, guest_id=who.id))

    db.session.add(
        m.LogisticsItem(
            title="Adresse du gîte",
            content="12 chemin des Bruyères, 38250 Villard-de-Lans",
            category="address",
            event_id=rich.id,
        )
    )
    db.session.add(
        m.LogisticsItem(
            title="Code d'accès",
            content="Boîte à clés : 4821",
            category="access",
            event_id=rich.id,
        )
    )
    db.session.add(
        m.LogisticsItem(
            title="Arrivée et départ",
            content="Arrivée samedi dès 16 h\nDépart dimanche avant 10 h",
            category="timing",
            event_id=rich.id,
        )
    )
    db.session.add(
        m.LogisticsItem(
            title="Réservation",
            content="Confirmation : https://example.org/reservation/4821 (à présenter à l'arrivée).",
            category="docs",
            event_id=rich.id,
        )
    )

    archive_start = datetime.utcnow() - timedelta(days=2)
    for i in range(55):  # historique ancien : fait apparaître « Messages précédents »
        who, who_id = ("Antoine", antoine.id) if i % 3 else ("Chloé", chloe.id)
        db.session.add(
            m.ChatMessage(
                content=f"Message d'archive {i + 1}",
                created_at=archive_start + timedelta(minutes=7 * i),
                author_name=who,
                guest_id=who_id,
                author_type="guest",
                event_id=rich.id,
            )
        )
    for content, author, guest_id, author_type in (
        ("On part à quelle heure samedi ?", "Antoine", antoine.id, "guest"),
        ("Vers 9 h, ça vous va ?", "Chloé", chloe.id, "guest"),
        ("Parfait, je réserve le gîte.", "Camille", None, "creator"),
    ):
        db.session.add(
            m.ChatMessage(
                content=content,
                author_name=author,
                guest_id=guest_id,
                author_type=author_type,
                event_id=rich.id,
            )
        )

    # Journal (B020) : de quoi voir les groupes par jour, les icônes par module et les filtres.
    yesterday = datetime.utcnow().replace(hour=18, minute=30, second=0, microsecond=0) - timedelta(days=1)
    for hours, name, kind, action, target, details in (
        (0, "Camille", "creator", "activity.created", "Randonnée au lac", None),
        (1, "Antoine", "guest", "list_item.created", "Pain", "Courses"),
        (2, "Chloé", "guest", "rsvp.updated", "Randonnée au lac", "maybe"),
        (20, "Antoine", "guest", "meal.created", "Raclette du samedi", None),
        (21, "Camille", "creator", "poll.created", "Quel jour pour la grande randonnée ?", None),
        (22, "Chloé", "guest", "expense.created", None, None),
        (23, "Antoine", "guest", "participant.renamed", "Antoine", None),
    ):
        db.session.add(
            m.ActivityLog(
                event_id=rich.id,
                actor_name=name,
                actor_type=kind,
                action=action,
                target=target,
                details=details,
                created_at=yesterday + timedelta(hours=hours),
            )
        )

    creator_household = m.Household.query.filter_by(
        guest_id=creator_guest.id, event_id=rich.id
    ).one()
    # Noms de foyers neutres : ce sont des données saisies, la garde « pas de français en EN » les lit telles quelles.
    creator_household.name = "Camille family"
    db.session.flush()
    for description, cents, category, household in (
        ("Courses supermarché", 14250, "food", creator_household),
        ("Location gîte", 84000, "lodging", antoine_household),
    ):
        db.session.add(
            m.Expense(
                description=description,
                amount_cents=cents,
                category=category,
                paid_by_household_id=household.id,
                date=today,
                created_by=antoine.id,
                event_id=rich.id,
            )
        )
    # Frais (B024) : une dépense en devise étrangère, un remboursement, une demande avec note.
    db.session.add(
        m.Expense(
            description="Péage et essence (aller)",
            amount_cents=6000,
            currency="USD",
            exchange_rate=0.92,
            category="transport",
            paid_by_household_id=antoine_household.id,
            date=today - timedelta(days=1),
            created_by=antoine.id,
            event_id=rich.id,
        )
    )
    db.session.add(
        m.Expense(
            description="Cadeau surprise",
            amount_cents=2500,
            category="other",
            is_shared=False,
            paid_by_household_id=antoine_household.id,
            date=today,
            created_by=antoine.id,
            event_id=rich.id,
        )
    )
    db.session.add(
        m.Transfer(
            from_household_id=creator_household.id,
            to_household_id=antoine_household.id,
            amount_cents=3000,
            note="Acompte",
            date=today,
            created_by=antoine.id,
            event_id=rich.id,
        )
    )
    db.session.add(
        m.PaymentRequest(
            from_household_id=antoine_household.id,
            to_household_id=creator_household.id,
            amount_cents=4500,
            message="Pour la location du gîte, merci !",
            created_by=antoine.id,
            event_id=rich.id,
        )
    )
    db.session.commit()
    return {
        "antoine": antoine,
        "chloe": chloe,
        "list": shopping,
        "packing": packing,
        "poll": poll,
        "activities_poll": activities_poll,
    }


def seed(out_dir: Path, port: int = 8499) -> dict[str, Any]:
    """Create the demo database and return (and write) ``fixtures.json``."""
    out_dir = Path(out_dir).resolve()
    if out_dir.is_relative_to(REPO_ROOT):
        raise ValueError(f"le dossier de démo doit être hors du dépôt : {out_dir}")
    _reset(out_dir)
    secret_key = secrets.token_hex(32)
    superadmin_password = secrets.token_urlsafe(16)
    os.environ.update(demo_env(out_dir, secret_key, superadmin_password, port))
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from app import create_app
    from app import models as m
    from app.extensions import db
    from app.freemium import can_add_guest
    from app.utils import ensure_creator_guest

    app = create_app()
    instance_path = out_dir / "instance"
    instance_path.mkdir(parents=True, exist_ok=True)
    app.instance_path = str(instance_path)

    today = date.today()
    now = datetime.utcnow()
    with app.app_context():
        creator = m.Creator(
            email="camille@demo.invalid",
            email_verified=True,
            display_name="Camille",
            personal_code="camille1",
        )
        db.session.add(creator)
        db.session.commit()

        specs = {
            "rich": ("Vacances au Vercors", -1, 5, "Villard-de-Lans"),
            "empty": ("Week-end en Bretagne", 40, 42, "Quiberon"),
            "full": ("Anniversaire de Léa", 20, 22, "Lyon"),
            "unverified": ("Séjour à confirmer", 60, 63, "Annecy"),
            "past": ("Ski à Chamrousse", -20, -14, "Chamrousse"),
            "long": (LONG_TITLE, 80, 83, "Saint-Rémy-de-Provence"),
        }
        events = {}
        for key, (title, start, end, location) in specs.items():
            unverified = key == "unverified"
            event = m.Event(
                title=title,
                start_date=today + timedelta(days=start),
                end_date=today + timedelta(days=end),
                location=location,
                creator_id=creator.id,
                creator_email=creator.email,
                verified_at=None if unverified else now,
                verification_token=secrets.token_hex(32) if unverified else None,
            )
            if key == "rich":
                event.description = "Une semaine entre amis dans le Vercors."
            db.session.add(event)
            events[key] = event
        db.session.commit()

        creator_guests = {key: ensure_creator_guest(ev, creator) for key, ev in events.items()}
        db.session.commit()

        full = events["full"]
        number = 1
        while can_add_guest(full):
            db.session.add(
                m.Guest(
                    code=f"full{number:04d}",
                    display_name=f"Invité {number:02d}",
                    event_id=full.id,
                )
            )
            db.session.commit()
            number += 1

        rich = events["rich"]
        objects = _populate_rich(db, m, rich, creator_guests["rich"])

        ser = app.session_interface.get_signing_serializer(app)  # type: ignore[attr-defined]
        cookies = {
            "creator": ser.dumps({"_user_id": creator.id, "_fresh": True}),
            "guest_household": ser.dumps({f"guest_{rich.code}": objects["antoine"].id}),
            "guest_solo": ser.dumps({f"guest_{rich.code}": objects["chloe"].id}),
        }
        placeholders = {f"event.{key}": ev.code for key, ev in events.items()}
        placeholders["list.rich"] = objects["list"].id
        placeholders["list.packing"] = objects["packing"].id
        placeholders["poll.rich"] = objects["poll"].id
        placeholders["poll.activities"] = objects["activities_poll"].id
        placeholders["token.unverified"] = events["unverified"].verification_token

    fixtures: dict[str, Any] = {
        "version": 1,
        "port": port,
        "secret_key": secret_key,
        "superadmin_password": superadmin_password,
        "database_path": str(out_dir / "demo.db"),
        "instance_path": str(instance_path),
        "roles": ["anonymous", "creator", "guest_household", "guest_solo"],
        "cookies": cookies,
        "placeholders": placeholders,
    }
    path = out_dir / "fixtures.json"
    path.write_text(json.dumps(fixtures, indent=2, ensure_ascii=False), encoding="utf-8")
    path.chmod(0o600)
    return fixtures


def main() -> int:
    parser = argparse.ArgumentParser(description="Graine de démo de la garde UI (B017)")
    parser.add_argument(
        "--out", type=Path, default=Path(os.environ.get("UI_DEMO_DIR") or DEFAULT_DEMO_DIR)
    )
    parser.add_argument("--port", type=int, default=int(os.environ.get("UI_PORT") or 8499))
    args = parser.parse_args()
    try:
        seed(args.out, args.port)
    except ValueError as exc:
        print(f"seed_demo : {exc}", file=sys.stderr)
        return 2
    print(Path(args.out).resolve() / "fixtures.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
