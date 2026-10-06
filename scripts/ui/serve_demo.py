"""Serve the app on the disposable demo database (B017, spec §9.3).

CLI : python scripts/ui/serve_demo.py [--demo-dir DIR]
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from flask import Flask
from seed_demo import DEFAULT_DEMO_DIR, REPO_ROOT, demo_env


def build_app(fixtures: dict[str, Any]) -> Flask:
    """Demo app: demo environment, redirected instance path, rate limiter off."""
    out_dir = Path(fixtures["database_path"]).parent
    os.environ.update(
        demo_env(out_dir, fixtures["secret_key"], fixtures["superadmin_password"], fixtures["port"])
    )
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from app import create_app
    from app.extensions import limiter

    app = create_app()
    app.instance_path = fixtures["instance_path"]
    limiter.enabled = False
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Serveur de démo de la garde UI (B017)")
    parser.add_argument(
        "--demo-dir", type=Path, default=Path(os.environ.get("UI_DEMO_DIR") or DEFAULT_DEMO_DIR)
    )
    args = parser.parse_args()
    path = args.demo_dir / "fixtures.json"
    if not path.is_file():
        print(f"{path} absent : lancer npm run ui:seed", file=sys.stderr)
        return 2
    fixtures = json.loads(path.read_text(encoding="utf-8"))
    from waitress import serve

    serve(build_app(fixtures), host="127.0.0.1", port=fixtures["port"], threads=4)
    return 0


if __name__ == "__main__":
    sys.exit(main())
