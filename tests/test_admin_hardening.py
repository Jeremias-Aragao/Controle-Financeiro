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

    def test_bootstrap_creates_single_admin(self):
        fd, db_path = tempfile.mkstemp(prefix="cf_boot_", suffix=".db")
        os.close(fd)
        os.unlink(db_path)
        code = r'''
from app import app, db
with app.app_context():
    rows = db.session.execute(db.text("select email, is_admin from users")).fetchall()
    print(rows)
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
            self.assertIn("('admin@example.com', 1)", result.stdout)
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_register_first_admin_flag_is_one_time(self):
        fd, db_path = tempfile.mkstemp(prefix="cf_reg_", suffix=".db")
        os.close(fd)
        os.unlink(db_path)
        code = r'''
from app import app, db
client = app.test_client()
resp = client.get('/register')
assert b'Criar como ADMIN inicial' in resp.data
client.post('/register', data={
    'name': 'Admin One',
    'email': 'admin.one@example.com',
    'password': 'Strong123!',
    'create_as_admin': 'on',
}, follow_redirects=True)
with app.app_context():
    total_admin = db.session.execute(db.text('select count(*) from users where is_admin = 1')).scalar_one()
    print('admins', total_admin)
resp2 = client.get('/register')
assert b'Criar como ADMIN inicial' not in resp2.data
'''
        result = self.run_python(
            code,
            {
                "DATABASE_URL": f"sqlite:///{db_path}",
                "ALLOW_FIRST_ADMIN_FROM_REGISTER": "true",
                "FLASK_ENV": "development",
                "SECRET_KEY": "dev-secret",
            },
        )
        try:
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("admins 1", result.stdout)
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_secret_key_required_in_production(self):
        code = "import app"
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
