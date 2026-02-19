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
from app.extensions import db
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
