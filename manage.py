#!/usr/bin/env python3
"""
SaaS CLI Management Script
Usage: python manage.py <command>
"""

import os
import secrets
import signal
import subprocess
import sys
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

    # Warn if .env has insecure permissions
    import stat
    mode = env_file.stat().st_mode
    if mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH):
        print(f"[WARN] {env_file} has insecure permissions. Run: chmod 600 {env_file}")

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

def _generate_vapid_keys():
    """Generate VAPID key pair for Web Push notifications."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())

    # Private key: PKCS8 DER, base64url
    priv_der = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    vapid_private = base64.urlsafe_b64encode(priv_der).rstrip(b"=").decode()

    # Public key: raw uncompressed point (65 bytes), base64url
    pub_numbers = private_key.public_key().public_numbers()
    pub_bytes = b"\x04" + pub_numbers.x.to_bytes(32, "big") + pub_numbers.y.to_bytes(32, "big")
    vapid_public = base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode()

    return vapid_public, vapid_private


def _test_smtp(host, port, user, password):
    """Test SMTP connection and login."""
    import smtplib
    import ssl

    try:
        if port == 465:
            ctx = ssl.create_default_context()
            server = smtplib.SMTP_SSL(host, port, timeout=10, context=ctx)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()

        if user:
            server.login(user, password)
        server.quit()
        return True, ""
    except smtplib.SMTPAuthenticationError as e:
        return False, f"Auth failed: {e.code} {e.message}"
    except smtplib.SMTPConnectError as e:
        return False, f"Connection failed: {e}"
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {e}"
    except Exception as e:
        return False, f"Error: {e}"


def _interactive_env():
    """Create .env interactively, generating secrets on the fly."""
    env_file = ROOT / ".env"
    if env_file.exists():
        print("  [SKIP] .env already exists")
        return

    print("  Creating .env interactively...")
    print()

    # SECRET_KEY: always auto-generated
    secret_key = secrets.token_hex(32)
    print(f"  SECRET_KEY: auto-generated ({secret_key[:8]}...)")

    # SUPERADMIN_EMAIL
    while True:
        email = input("  Superadmin email [admin@example.com]: ").strip()
        if not email:
            email = "admin@example.com"
        if "@" in email:
            break
        print("  [ERROR] Invalid email, try again.")

    # SUPERADMIN_PASSWORD
    gen_pass = input("  Generate random password? [Y/n]: ").strip().lower()
    if gen_pass in ("", "y", "yes"):
        password = secrets.token_urlsafe(12)
        print(f"  SUPERADMIN_PASSWORD: {password}")
        print("  [!] Save this password, it won't be shown again.")
    else:
        while True:
            password = input("  Superadmin password (min 8 chars): ").strip()
            if len(password) >= 8:
                break
            print("  [ERROR] Password too short (min 8 chars).")

    # NGINX_PORT
    port = input("  Nginx port [8080]: ").strip()
    if not port or not port.isdigit():
        port = "8080"

    # APP_DOMAIN
    domain = input("  App domain [localhost]: ").strip()
    if not domain:
        domain = "localhost"

    # APP_URL
    scheme = "https" if domain != "localhost" else "http"
    app_url = f"{scheme}://{domain}:{port}"

    # VAPID keys (Web Push)
    print("  Generating VAPID keys (Web Push)...")
    vapid_public, vapid_private = _generate_vapid_keys()
    print(f"  VAPID_PUBLIC_KEY: {vapid_public[:16]}...")
    print(f"  VAPID_PRIVATE_KEY: {vapid_private[:16]}...")

    # SMTP
    print()
    smtp_enabled = input("  Configure SMTP email? [y/N]: ").strip().lower()
    smtp_host = smtp_user = smtp_pass = ""
    smtp_port_str = "587"

    if smtp_enabled in ("y", "yes"):
        smtp_host = input("  SMTP host [smtp.gmail.com]: ").strip() or "smtp.gmail.com"
        smtp_port_str = input("  SMTP port [587]: ").strip() or "587"
        smtp_user = input("  SMTP user (email): ").strip()
        smtp_pass = input("  SMTP password/app password: ").strip()

        # Test connection
        print("  Testing SMTP connection...")
        ok, err = _test_smtp(smtp_host, int(smtp_port_str), smtp_user, smtp_pass)
        if ok:
            print("  [OK] SMTP connection successful")
        else:
            print(f"  [WARN] SMTP test failed: {err}")
            retry = input("  Continue anyway? [Y/n]: ").strip().lower()
            if retry in ("n", "no"):
                print("  [SKIP] SMTP not configured")
                smtp_host = smtp_user = smtp_pass = ""

    env_content = f"""# === Holishared Configuration ===

# === Docker / Nginx ===
NGINX_PORT={port}

# === Serveur ===
APP_HOST=0.0.0.0
APP_PORT=8400
APP_THREADS=4

# === Sécurité ===
SECRET_KEY={secret_key}
SESSION_COOKIE_SECURE={'true' if domain != 'localhost' else 'false'}
SESSION_COOKIE_HTTPONLY=true
PERMANENT_SESSION_LIFETIME=86400

# === Base de données ===
DATABASE_URL=sqlite:///instance/holishared.db

# === Superadmin ===
SUPERADMIN_EMAIL={email}
SUPERADMIN_PASSWORD={password}

# === Domaine ===
APP_DOMAIN={domain}
APP_URL={app_url}

# === Freemium ===
MAX_GUESTS_PER_EVENT=10
MAX_DURATION_DAYS=30
MAX_EVENTS_PER_CREATOR=3
ENABLED_MODULES=planning,lists,logistics,voting,media,chat,costs

# === Push notifications (Web Push) ===
VAPID_PUBLIC_KEY={vapid_public}
VAPID_PRIVATE_KEY={vapid_private}
VAPID_CLAIMS_SUBJECT=mailto:{email}

# === Anti-abus ===
RATE_LIMIT_CREATE=5/hour
RATE_LIMIT_INVITE=20/hour
BLOCKED_EMAIL_DOMAINS=mailinator.com,temp-mail.com,10minutemail.com,guerrillamail.com,yopmail.com,throwaway.email

# === Email (SMTP) ===
SMTP_HOST={smtp_host}
SMTP_PORT={smtp_port_str}
SMTP_USER={smtp_user}
SMTP_PASSWORD={smtp_pass}
SMTP_FROM=holishared@{domain}

# === i18n ===
DEFAULT_LANGUAGE=fr
SUPPORTED_LANGUAGES=fr,en

# === Logs ===
LOG_LEVEL=INFO
LOG_FILE=logs/app.log
"""
    env_file.write_text(env_content)
    env_file.chmod(0o600)  # owner read/write only
    print(f"  [OK] .env created: {env_file} (chmod 600)")


def cmd_init():
    """Initialize the project: .env, venv, deps, DB."""
    print("[1/5] Creating .env (interactive)...")
    _interactive_env()

    print("[2/5] Creating virtualenv...")
    if VENV.exists():
        print("  [SKIP] .venv already exists")
    else:
        run([sys.executable, "-m", "venv", str(VENV)])

    print("[3/5] Installing dependencies...")
    run([str(venv_pip()), "install", "-q", "-r", str(ROOT / "requirements.txt")])

    print("[4/5] Creating directories...")
    LOG_DIR.mkdir(exist_ok=True)
    (ROOT / "instance").mkdir(exist_ok=True)

    print("[5/5] Initializing database...")
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
    print("Next: python manage.py run  (dev)  or  docker compose up -d  (prod)")


def cmd_run():
    """Run dev server (no debug, localhost only)."""
    load_env()
    run([str(venv_python()), "-m", "flask", "--app", "app", "run",
         "-h", "127.0.0.1",
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
    db_path = ROOT / "instance" / "holishared.db"
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
    add_col("creators", "tier", "VARCHAR(20) DEFAULT 'free'")
    add_col("expenses", "is_shared", "BOOLEAN DEFAULT 1")

    # creators.email: NOT NULL -> NULL (opt-out of storing the creator email).
    # SQLite cannot ALTER a column's nullability, so rebuild the table.
    # (SQL kept on single lines: this whole block is a -c string literal.)
    creators_cols = {c["name"]: c for c in insp.get_columns("creators")}
    if creators_cols.get("email", {}).get("nullable") is False:
        with db.engine.begin() as conn:
            conn.execute(text("CREATE TABLE creators_new (id VARCHAR(32) NOT NULL, email VARCHAR(255), email_verified BOOLEAN, verification_token VARCHAR(64), verification_sent_at DATETIME, display_name VARCHAR(100), personal_code VARCHAR(8), created_at DATETIME, PRIMARY KEY (id), UNIQUE (email), UNIQUE (personal_code))"))
            conn.execute(text("INSERT INTO creators_new SELECT id, email, email_verified, verification_token, verification_sent_at, display_name, personal_code, created_at FROM creators"))
            conn.execute(text("DROP TABLE creators"))
            conn.execute(text("ALTER TABLE creators_new RENAME TO creators"))
        print("[OK] creators.email made nullable (table rebuilt)")
    else:
        print("[skip] creators.email already nullable")
    from app.migrations import prune_backups, run_identity_migration, run_lists_migration, run_meals_migration
    print('[OK] meals', run_meals_migration(app))
    print('[OK] lists', run_lists_migration(app))
    print('[OK] identity', run_identity_migration(app))
    print('[OK] backups pruned', prune_backups(app.instance_path))
    print("[OK] Migrations applied")
"""])


def cmd_check_identity():
    """Read-only check of participant identity consistency."""
    load_env()
    sys.exit(run([str(venv_python()), "-m", "app.migrations", "check"]))


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
    "run": (cmd_run, "Run dev server (localhost, no debug)"),
    "start": (cmd_start, "Start production server (Waitress)"),
    "stop": (cmd_stop, "Stop the server"),
    "status": (cmd_status, "Show server status"),
    "db-init": (cmd_db_init, "Create database tables"),
    "migrate": (cmd_migrate, "Apply schema migrations to existing DB"),
    "check-identity": (cmd_check_identity, "Check participant identity consistency"),
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
        sys.exit(0)

    if cmd not in COMMANDS:
        print(f"[ERROR] Unknown command: {cmd}")
        print(f"Available: {', '.join(COMMANDS.keys())}")
        sys.exit(1)

    func, _ = COMMANDS[cmd]
    func()


if __name__ == "__main__":
    main()
