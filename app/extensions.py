from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

try:
    from flask_migrate import Migrate
except Exception:  # pragma: no cover
    class Migrate:  # fallback when dependency is unavailable in restricted env
        def init_app(self, app, db):
            return None


db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
