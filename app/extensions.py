"""Flask extensions."""

from flask_babel import Babel
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
limiter = Limiter(key_func=get_remote_address, default_limits=["100 per hour"])
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = None  # We handle messages in templates
babel = Babel()
