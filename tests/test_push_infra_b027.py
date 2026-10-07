"""B027 — configuration Docker et documentation du worker d'envoi."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _service(name: str) -> str:
    text = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    block = text.split(f"\n  {name}:\n")[1]
    return block.split("\n\n")[0]


def test_worker_skips_startup_migration():
    assert "SKIP_STARTUP_MIGRATION=1" in _service("worker")


def test_worker_receives_database_url():
    assert "DATABASE_URL=" in _service("worker")


def test_worker_receives_vapid_private_key():
    assert "VAPID_PRIVATE_KEY=" in _service("worker")


def test_worker_shares_the_database_volume():
    assert "saas_data:/app/instance" in _service("worker")


def test_app_receives_public_vapid_key():
    assert "VAPID_PUBLIC_KEY=" in _service("app")


def test_env_example_documents_vapid_variables():
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    assert [
        k
        for k in ("VAPID_PUBLIC_KEY=", "VAPID_PRIVATE_KEY=", "VAPID_CLAIMS_SUBJECT=")
        if k not in text
    ] == []


def test_pywebpush_is_declared_in_requirements():
    assert "pywebpush" in (REPO / "requirements.txt").read_text(encoding="utf-8")


def test_pywebpush_is_declared_in_pyproject():
    assert "pywebpush" in (REPO / "pyproject.toml").read_text(encoding="utf-8")
