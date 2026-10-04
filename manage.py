#!/usr/bin/env python3
"""
SaaS CLI Management Script
Usage: python manage.py <command>
"""

import os
import sys
import subprocess
import shutil
import signal
import time
from pathlib import Path

# Project root
ROOT = Path(__file__).parent.resolve()
VENV = ROOT / ".venv"
BIN = VENV / "bin"
PID_FILE = ROOT / ".saas.pid"
LOG_DIR = ROOT / "logs"


def load_env():
    """Load .env into os.environ."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        print(f"[ERROR] {env_file} not found. Run 'python manage.py init' first.")
        sys.exit(1)
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ[key.strip()] = value.strip()


def venv_python():
    """Return path to venv python."""
    if sys.platform == "win32":
        return BIN / "python.exe"
    return BIN / "python"


def venv_pip():
    """Return path to venv pip."""
    if sys.platform == "win32":
        return BIN / "Scripts" / "pip.exe"
    return BIN / "pip"


def run(cmd, cwd=ROOT, shell=False, **kwargs):
    """Run a command, stream output."""
    print(f"  $ {cmd}" if isinstance(cmd, str) else f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, shell=shell, **kwargs)
    return result.returncode


# === Commands ===

def cmd_init():
    """Initialize the project: venv, deps, DB."""
    print("[1/4] Creating virtualenv...")
    if VENV.exists():
        print("  [SKIP] .venv already exists")
    else:
        run([sys.executable, "-m", "venv", str(VENV)])

    print("[2/4] Installing dependencies...")
    run([str(venv_pip()), "install", "-q", "-r", str(ROOT / "requirements.txt")])

    print("[3/4] Creating logs directory...")
    LOG_DIR.mkdir(exist_ok=True)

    print("[4/4] Initializing database...")
    run([str(venv_python()), "-c", """
import sys; sys.path.insert(0, '.')
from app import create_app
app = create_app()
with app.app_context():
    from app.extensions import db
    db.create_all()
    print('  [OK] Database initialized')
"""])
    print("\n[OK] Init complete.")
    print("Next: edit .env (SECRET_KEY, SUPERADMIN_*) then 'python manage.py run'")


def cmd_run():
    """Run dev server (Flask debug mode)."""
    load_env()
    os.environ["FLASK_DEBUG"] = "1"
    run([str(venv_python()), "-m", "flask", "--app", "app", "run",
         "-h", os.environ.get("APP_HOST", "127.0.0.1"),
         "-p", os.environ.get("APP_PORT", "8400")])


def cmd_start():
    """Start production server (Waitress)."""
    load_env()
    if is_running():
        print("[WARN] Already running (PID", get_pid(), ")")
        return
    print(f"Starting Waitress on {os.environ.get('APP_HOST')}:{os.environ.get('APP_PORT')}...")
    log_file = open(LOG_DIR / "waitress.log", "a")
    proc = subprocess.Popen(
        [str(venv_python()), "-m", "waitress",
         "--listen", f"{os.environ.get('APP_HOST', '127.0.0.1')}:{os.environ.get('APP_PORT', '8400')}",
         "--threads", os.environ.get("APP_THREADS", "4"),
         "--call", "app:create_app"],
        cwd=ROOT,
        stdout=log_file,
        stderr=log_file,
        start_new_session=True,
    )
    PID_FILE.write_text(str(proc.pid))
    print(f"[OK] Started (PID {proc.pid}). Logs: {LOG_DIR / 'waitress.log'}")


def cmd_stop():
    """Stop the server."""
    if not is_running():
        print("[INFO] Not running.")
        return
    pid = get_pid()
    print(f"Stopping PID {pid}...")
    os.kill(pid, signal.SIGTERM)
    for _ in range(10):
        time.sleep(0.5)
        if not is_running():
            break
    else:
        print("[WARN] Force killing...")
        os.kill(pid, signal.SIGKILL)
    PID_FILE.unlink(missing_ok=True)
    print("[OK] Stopped.")


def cmd_status():
    """Show server status."""
    if is_running():
        pid = get_pid()
        port = os.environ.get("APP_PORT", "8400") if os.path.exists(ROOT / ".env") else "8400"
        print(f"[RUNNING] PID {pid}, port {port}")
    else:
        print("[STOPPED]")


def cmd_db_init():
    """Create database tables."""
    load_env()
    run([str(venv_python()), "-c", """
import sys; sys.path.insert(0, '.')
from app import create_app
app = create_app()
with app.app_context():
    from app.extensions import db
    db.create_all()
    print('[OK] Tables created')
"""])


def cmd_db_shell():
    """Open SQLite shell."""
    load_env()
    db_path = ROOT / "saas.db"
    run(["sqlite3", str(db_path)])


def cmd_migrate():
    """Apply lightweight schema migrations to an existing SQLite DB.

    ``db.create_all()`` only creates missing tables; it does not add new
    columns to existing ones. This command adds the columns introduced
    after the initial schema, idempotently.
    """
    load_env()
    run([str(venv_python()), "-c", """
import sys; sys.path.insert(0, '.')
from app import create_app
app = create_app()
with app.app_context():
    from app.extensions import db
    from sqlalchemy import text, inspect
    insp = inspect(db.engine)

    def add_col(table, col, decl):
        cols = {c["name"] for c in insp.get_columns(table)}
        if col not in cols:
            db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {decl}"))
            db.session.commit()
            print(f"[OK] {table}.{col} added")
        else:
            print(f"[skip] {table}.{col} exists")

    add_col("guests", "email", "VARCHAR(255)")
    add_col("events", "creator_email", "VARCHAR(255)")
    print("[OK] Migrations applied")
"""])


def cmd_deploy():
    """Deploy: nginx + systemd (requires root)."""
    load_env()
    print("Deploying...")

    # Nginx
    nginx_conf = ROOT / "nginx" / "saas.conf"
    target = "/etc/nginx/sites-available/saas"
    print(f"  Nginx: {nginx_conf} -> {target}")
    if os.geteuid() != 0:
        print("  [WARN] Need root for nginx/systemd. Run: sudo python manage.py deploy")
        print("  Manual steps:")
        print(f"    sudo cp {nginx_conf} /etc/nginx/sites-available/saas")
        print("    sudo ln -sf /etc/nginx/sites-available/saas /etc/nginx/sites-enabled/saas")
        print("    sudo nginx -t && sudo systemctl reload nginx")
        print(f"    sudo cp {ROOT / 'systemd' / 'saas.service'} /etc/systemd/system/saas.service")
        print("    sudo systemctl daemon-reload && sudo systemctl enable saas")
        return

    run(["sudo", "cp", str(nginx_conf), target])
    run(["sudo", "ln", "-sf", target, "/etc/nginx/sites-enabled/saas"])
    run(["sudo", "nginx", "-t"])
    run(["sudo", "systemctl", "reload", "nginx"])

    # Systemd
    svc = ROOT / "systemd" / "saas.service"
    run(["sudo", "cp", str(svc), "/etc/systemd/system/saas.service"])
    run(["sudo", "systemctl", "daemon-reload"])
    run(["sudo", "systemctl", "enable", "saas"])
    run(["sudo", "systemctl", "restart", "saas"])

    print("[OK] Deployed. Check: sudo systemctl status saas")


def cmd_logs():
    """Tail logs."""
    log = LOG_DIR / "waitress.log"
    if not log.exists():
        print("[INFO] No logs yet.")
        return
    run(["tail", "-f", str(log)])


def cmd_reset_admin():
    """Reset superadmin password (generates new random)."""
    import secrets
    new_pass = secrets.token_urlsafe(12)
    env_file = ROOT / ".env"
    content = env_file.read_text()
    lines = []
    for line in content.splitlines():
        if line.startswith("SUPERADMIN_PASSWORD="):
            lines.append(f"SUPERADMIN_PASSWORD={new_pass}")
        else:
            lines.append(line)
    env_file.write_text("\n".join(lines) + "\n")
    print(f"[OK] New password: {new_pass}")
    print("Update .env and restart the server.")


# === Helpers ===

def get_pid():
    if PID_FILE.exists():
        return int(PID_FILE.read_text().strip())
    return None


def is_running():
    pid = get_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# === Main ===

COMMANDS = {
    "init": (cmd_init, "Initialize project (venv, deps, DB)"),
    "run": (cmd_run, "Run dev server (Flask debug)"),
    "start": (cmd_start, "Start production server (Waitress)"),
    "stop": (cmd_stop, "Stop the server"),
    "status": (cmd_status, "Show server status"),
    "db-init": (cmd_db_init, "Create database tables"),
    "migrate": (cmd_migrate, "Apply schema migrations to existing DB"),
    "db-shell": (cmd_db_shell, "Open SQLite shell"),
    "deploy": (cmd_deploy, "Deploy nginx + systemd"),
    "logs": (cmd_logs, "Tail server logs"),
    "reset-admin": (cmd_reset_admin, "Generate new superadmin password"),
}


def main():
    if len(sys.argv) < 2:
        print("SaaS Management CLI\n")
        print("Usage: python manage.py <command>\n")
        for name, (_, desc) in COMMANDS.items():
            print(f"  {name:<14} {desc}")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd in ("help", "--help", "-h"):
        main.__defaults__  # trigger above
        sys.exit(0)

    if cmd not in COMMANDS:
        print(f"[ERROR] Unknown command: {cmd}")
        print(f"Available: {', '.join(COMMANDS.keys())}")
        sys.exit(1)

    func, _ = COMMANDS[cmd]
    func()


if __name__ == "__main__":
    main()
