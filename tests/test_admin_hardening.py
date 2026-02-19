import os
import subprocess
import sys
import tempfile
import unittest


class AdminHardeningTests(unittest.TestCase):
    def run_python(self, code: str, extra_env: dict[str, str]) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.update(extra_env)
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)

    def test_bootstrap_creates_platform_admin_membership(self):
        fd, db_path = tempfile.mkstemp(prefix="cf_boot_", suffix=".db")
        os.close(fd)
        os.unlink(db_path)
        code = r'''
from app import create_app
from app.models import Membership

app = create_app()
with app.app_context():
    total = Membership.query.filter_by(role="PLATFORM_ADMIN").count()
    print("platform_admin_memberships", total)
'''
        result = self.run_python(
            code,
            {
                "DATABASE_URL": f"sqlite:///{db_path}",
                "ADMIN_EMAIL": "admin@example.com",
                "ADMIN_PASSWORD": "Strong123!",
                "FLASK_ENV": "development",
                "SECRET_KEY": "dev-secret",
            },
        )
        try:
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("platform_admin_memberships 1", result.stdout)
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_invite_accept_redirects_to_login_when_anonymous(self):
        fd, db_path = tempfile.mkstemp(prefix="cf_inv_", suffix=".db")
        os.close(fd)
        os.unlink(db_path)
        code = r'''
from datetime import datetime, timedelta
import hashlib
from app import create_app
from app.extensions import db
from app.models import InviteToken, Organization, User

app = create_app()
with app.app_context():
    u = User(name='A', email='a@a.com', password_hash='x')
    o = Organization(name='Org', slug='org')
    db.session.add_all([u, o])
    db.session.commit()
    token='abc123'
    db.session.add(InviteToken(org_id=o.id, invited_by_user_id=u.id, token_hash=hashlib.sha256(token.encode()).hexdigest(), role='ORG_USER', expires_at=datetime.utcnow()+timedelta(days=1)))
    db.session.commit()

client = app.test_client()
resp = client.get('/org/invite/accept/abc123', follow_redirects=False)
print(resp.status_code, resp.headers.get('Location',''))
'''
        result = self.run_python(
            code,
            {"DATABASE_URL": f"sqlite:///{db_path}", "FLASK_ENV": "development", "SECRET_KEY": "dev-secret"},
        )
        try:
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("302 /login?next=/org/invite/accept/abc123", result.stdout)
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_secret_key_required_in_production(self):
        code = "from app import create_app\ncreate_app()"
        env = {
            "FLASK_ENV": "production",
            "SECRET_KEY": "",
            "DATABASE_URL": "sqlite:////tmp/cf_prod_check.db",
            "RENDER": "true",
        }
        result = self.run_python(code, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY é obrigatória em produção", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
