"""Flask extensions."""

import os
from typing import Any

from flask_babel import Babel
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = None  # We handle messages in templates
babel = Babel()


def _create_limiter() -> Limiter:
    """Create the rate limiter with Redis storage if available."""
    redis_url = os.environ.get("REDIS_URL", "")
    kwargs: dict[str, Any] = {
        "key_func": get_remote_address,
        "default_limits": ["100 per hour"],
    }
    if redis_url:
        kwargs["storage_uri"] = redis_url
    return Limiter(**kwargs)


limiter = _create_limiter()
