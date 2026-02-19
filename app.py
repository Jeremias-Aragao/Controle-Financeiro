from __future__ import annotations

import os
import re
from datetime import datetime, date

from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash, check_password_hash

COMP_RE = re.compile(r"^\d{4}-\d{2}$")

db = SQLAlchemy()
login_manager = LoginManager()


def create_app() -> Flask:
    app = Flask(__name__)

    database_url = os.getenv("DATABASE_URL", "sqlite:///local.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "magnata-r02-dev-change-me")

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login"

    # ---------------- Models ----------------
    class User(db.Model):
        __tablename__ = "users"
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(120), nullable=False)
        email = db.Column(db.String(180), unique=True, nullable=False, index=True)
        password_hash = db.Column(db.String(255), nullable=False)
        is_admin = db.Column(db.Boolean, nullable=False, default=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow)

        def set_password(self, password: str) -> None:
            self.password_hash = generate_password_hash(password)

        def check_password(self, password: str) -> bool:
            return check_password_hash(self.password_hash, password)

        @property
        def is_active(self):  # pragma: no cover
            return True

        @property
        def is_authenticated(self):  # pragma: no cover
            return True

        @property
        def is_anonymous(self):  # pragma: no cover
            return False

        def get_id(self):  # pragma: no cover
            return str(self.id)

    class UserConfig(db.Model):
        __tablename__ = "user_config"
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
        saldo_inicial = db.Column(db.Float, default=0.0)
        competencia_inicio = db.Column(db.String(7), nullable=False)

    class Lancamento(db.Model):
        __tablename__ = "lancamentos"
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=False)

        tipo = db.Column(db.String(20), nullable=False)  # ATIVO | PASSIVO
        descricao = db.Column(db.String(255), nullable=False)
        categoria = db.Column(db.String(120))
        competencia = db.Column(db.String(7), index=True, nullable=False)  # AAAA-MM
        data_evento = db.Column(db.String(10), nullable=False)  # YYYY-MM-DD
        valor = db.Column(db.Float, nullable=False)

        status = db.Column(db.String(20), nullable=False, default="PENDENTE")  # PENDENTE | BAIXADO
        data_baixa = db.Column(db.String(10))

        created_at = db.Column(db.DateTime, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            uid = int(user_id)
        except Exception:
            return None
        return User.query.get(uid)

    with app.app_context():
        def ensure_users_admin_column() -> None:
            inspector = inspect(db.engine)
            columns = {column["name"] for column in inspector.get_columns("users")}
            if "is_admin" in columns:
                return

            db.session.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE"))
            db.session.commit()

        def bootstrap_admin() -> None:
            admin_exists = User.query.filter_by(is_admin=True).first()
            if admin_exists:
                print("Admin bootstrap ignorado: já existe usuário admin.")
                return

            email = os.getenv("ADMIN_EMAIL")
            password = os.getenv("ADMIN_PASSWORD")

            if not email or not password:
                print("Nenhum ADMIN criado. Defina ADMIN_EMAIL e ADMIN_PASSWORD.")
                return

            admin = User(name="Platform Admin", email=email.strip().lower(), is_admin=True)
            admin.password_hash = generate_password_hash(password)
            db.session.add(admin)
            db.session.commit()
            print("Admin bootstrap criado com sucesso.")

        @app.cli.command("create-admin")
        def create_admin() -> None:
            email = os.getenv("ADMIN_EMAIL")
            password = os.getenv("ADMIN_PASSWORD")

            if not email or not password:
                print("Defina ADMIN_EMAIL e ADMIN_PASSWORD.")
                return

            if User.query.filter_by(is_admin=True).first():
                print("Já existe um usuário admin. Operação cancelada.")
                return

            normalized_email = email.strip().lower()
            if User.query.filter_by(email=normalized_email).first():
                print("Usuário com este e-mail já existe.")
                return

            admin = User(name="Platform Admin", email=normalized_email, is_admin=True)
            admin.password_hash = generate_password_hash(password)
            db.session.add(admin)
            db.session.commit()
            print("Admin criado com sucesso via CLI.")

        db.create_all()
        ensure_users_admin_column()
        bootstrap_admin()

    @app.context_processor
    def inject_datetime():
        return {"datetime": datetime}    

    # ---------------- Helpers ----------------
    def parse_competencia(comp: str) -> str:
        if not COMP_RE.match(comp):
            abort(404)
        return comp

    def month_add(comp: str, delta: int) -> str:
        y, m = map(int, comp.split("-"))
        m += delta
        while m <= 0:
            m += 12
            y -= 1
        while m >= 13:
            m -= 12
            y += 1
        return f"{y:04d}-{m:02d}"

    def today_iso() -> str:
        return date.today().isoformat()

    def days_to(date_iso: str) -> int:
        try:
            d = date.fromisoformat(date_iso)
        except Exception:
            return 0
        return (d - date.today()).days

    def get_user_config(user_id: int) -> UserConfig:
        cfg = UserConfig.query.filter_by(user_id=user_id).first()
        if not cfg:
            now_comp = datetime.now().strftime("%Y-%m")
            cfg = UserConfig(user_id=user_id, saldo_inicial=0.0, competencia_inicio=now_comp)
            db.session.add(cfg)
            db.session.commit()
        if not cfg.competencia_inicio:
            cfg.competencia_inicio = datetime.now().strftime("%Y-%m")
            db.session.commit()
        return cfg

    def saldo_acumulado_ate(user_id: int, competencia: str) -> tuple[float, float, float]:
        cfg = get_user_config(user_id)
        saldo0 = float(cfg.saldo_inicial or 0.0)
        comp_ini = cfg.competencia_inicio

        if competencia < comp_ini:
            return saldo0, 0.0, saldo0

        def sum_mes(comp: str) -> float:
            rows = Lancamento.query.filter_by(user_id=user_id, competencia=comp, status="BAIXADO").all()
            rec = sum(r.valor for r in rows if r.tipo == "ATIVO")
            pag = sum(r.valor for r in rows if r.tipo == "PASSIVO")
            return float(rec - pag)

        comp_cursor = comp_ini
        total = 0.0
        while comp_cursor < competencia:
            total += sum_mes(comp_cursor)
            comp_cursor = month_add(comp_cursor, 1)

        saldo_ini_mes = saldo0 + total
        resultado_mes = sum_mes(competencia)
        saldo_final = saldo_ini_mes + resultado_mes
        return float(saldo_ini_mes), float(resultado_mes), float(saldo_final)

    # ---------------- Auth ----------------
    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("home"))

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            if not name or not email or not password:
                flash("Preencha nome, e-mail e senha.")
                return redirect(url_for("register"))

            if User.query.filter_by(email=email).first():
                flash("Este e-mail já está cadastrado. Faça login.")
                return redirect(url_for("login"))

            u = User(name=name, email=email)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()

            get_user_config(u.id)

            flash("Conta criada! Agora faça login.")
            return redirect(url_for("login"))

        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("home"))

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            user = User.query.filter_by(email=email).first()
            if not user or not user.check_password(password):
                flash("E-mail ou senha inválidos.")
                return redirect(url_for("login"))

            login_user(user)
            return redirect(url_for("home"))

        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        flash("Você saiu.")
        return redirect(url_for("login"))

    # ---------------- App ----------------
    @app.route("/")
    def root():
        return redirect(url_for("home" if current_user.is_authenticated else "login"))

    @app.route("/home")
    @login_required
    def home():
        hoje = datetime.now().strftime("%Y-%m")
        return redirect(url_for("mes", competencia=hoje))

    @app.route("/config", methods=["GET", "POST"])
    @login_required
    def config():
        cfg = get_user_config(current_user.id)

        if request.method == "POST":
            saldo_inicial = request.form.get("saldo_inicial", "0").replace(",", ".").strip()
            competencia_inicio = request.form.get("competencia_inicio", "").strip()
            if not COMP_RE.match(competencia_inicio):
                flash("Competência de início inválida. Use AAAA-MM (ex.: 2026-02).")
                return redirect(url_for("config"))

            try:
                saldo_val = float(saldo_inicial)
            except Exception:
                saldo_val = 0.0

            cfg.saldo_inicial = saldo_val
            cfg.competencia_inicio = competencia_inicio
            db.session.commit()
            flash("Configurações salvas.")
            return redirect(url_for("home"))

        return render_template("config.html", cfg=cfg)

    @app.route("/mes/<competencia>")
    @login_required
    def mes(competencia):
        competencia = parse_competencia(competencia)
        prev_comp = month_add(competencia, -1)
        next_comp = month_add(competencia, 1)

        rows = (
            Lancamento.query.filter_by(user_id=current_user.id, competencia=competencia)
            .order_by(Lancamento.data_evento.asc(), Lancamento.id.asc())
            .all()
        )

        passivo, ativo = [], []
        for r in rows:
            d = {
                "id": r.id,
                "tipo": r.tipo,
                "descricao": r.descricao,
                "categoria": r.categoria,
                "competencia": r.competencia,
                "data_evento": r.data_evento,
                "valor": float(r.valor),
                "status": r.status,
                "data_baixa": r.data_baixa,
            }
            d["dias"] = days_to(d["data_evento"])

            if d["tipo"] == "PASSIVO":
                passivo.append(d)
            else:
                ativo.append(d)

        total_passivo_baixado = sum(l["valor"] for l in passivo if l["status"] == "BAIXADO")
        total_ativo_baixado = sum(l["valor"] for l in ativo if l["status"] == "BAIXADO")
        passivo_pendente = sum(l["valor"] for l in passivo if l["status"] != "BAIXADO")
        ativo_pendente = sum(l["valor"] for l in ativo if l["status"] != "BAIXADO")

        resultado_baixado = total_ativo_baixado - total_passivo_baixado
        resultado_projetado = (total_ativo_baixado + ativo_pendente) - (total_passivo_baixado + passivo_pendente)

        saldo_ini_mes, _res_mes, saldo_final_mes = saldo_acumulado_ate(current_user.id, competencia)

        return render_template(
            "mes.html",
            competencia=competencia,
            prev_comp=prev_comp,
            next_comp=next_comp,
            passivo=passivo,
            ativo=ativo,
            total_passivo_baixado=total_passivo_baixado,
            total_ativo_baixado=total_ativo_baixado,
            passivo_pendente=passivo_pendente,
            ativo_pendente=ativo_pendente,
            resultado_baixado=resultado_baixado,
            resultado_projetado=resultado_projetado,
            saldo_ini_mes=saldo_ini_mes,
            saldo_final_mes=saldo_final_mes,
            hoje=today_iso(),
        )

    @app.route("/novo/<competencia>", methods=["GET", "POST"])
    @login_required
    def novo(competencia):
        competencia = parse_competencia(competencia)

        if request.method == "POST":
            tipo = request.form["tipo"]
            descricao = request.form["descricao"].strip()
            categoria = request.form.get("categoria", "").strip() or None
            data_evento = request.form["data_evento"]
            valor = float(request.form["valor"])

            l = Lancamento(
                user_id=current_user.id,
                tipo=tipo,
                descricao=descricao,
                categoria=categoria,
                competencia=competencia,
                data_evento=data_evento,
                valor=valor,
                status="PENDENTE",
                data_baixa=None,
            )
            db.session.add(l)
            db.session.commit()
            return redirect(url_for("mes", competencia=competencia))

        return render_template("novo_lancamento.html", competencia=competencia)

    @app.route("/editar/<int:id>/<competencia>", methods=["GET", "POST"])
    @login_required
    def editar(id, competencia):
        competencia = parse_competencia(competencia)
        l = Lancamento.query.filter_by(id=id, user_id=current_user.id).first_or_404()

        if request.method == "POST":
            l.tipo = request.form["tipo"]
            l.descricao = request.form["descricao"].strip()
            l.categoria = request.form.get("categoria", "").strip() or None
            l.data_evento = request.form["data_evento"]
            l.valor = float(request.form["valor"])
            l.status = request.form.get("status", l.status)

            if l.status == "BAIXADO" and not l.data_baixa:
                l.data_baixa = today_iso()
            if l.status != "BAIXADO":
                l.data_baixa = None

            db.session.commit()
            return redirect(url_for("mes", competencia=competencia))

        return render_template("editar_lancamento.html", competencia=competencia, l=l)

    @app.route("/toggle/<int:id>/<competencia>")
    @login_required
    def toggle(id, competencia):
        competencia = parse_competencia(competencia)
        l = Lancamento.query.filter_by(id=id, user_id=current_user.id).first_or_404()

        l.status = "PENDENTE" if l.status == "BAIXADO" else "BAIXADO"
        l.data_baixa = today_iso() if l.status == "BAIXADO" else None
        db.session.commit()
        return redirect(url_for("mes", competencia=competencia))

    @app.route("/excluir/<int:id>/<competencia>", methods=["POST"])
    @login_required
    def excluir(id, competencia):
        competencia = parse_competencia(competencia)
        l = Lancamento.query.filter_by(id=id, user_id=current_user.id).first_or_404()
        db.session.delete(l)
        db.session.commit()
        return redirect(url_for("mes", competencia=competencia))

    @app.route("/resumo/<ano>")
    @login_required
    def resumo(ano):
        if not re.match(r"^\d{4}$", ano):
            abort(404)

        q = (
            db.session.query(Lancamento.competencia)
            .filter(
                Lancamento.user_id == current_user.id,
                Lancamento.competencia.like(f"{ano}-%"),
                Lancamento.status == "BAIXADO",
            )
            .distinct()
            .order_by(Lancamento.competencia.asc())
        )

        months = []
        total_recebido = 0.0
        total_pago = 0.0

        for (comp,) in q.all():
            rows = Lancamento.query.filter_by(user_id=current_user.id, competencia=comp, status="BAIXADO").all()
            recebido = sum(r.valor for r in rows if r.tipo == "ATIVO")
            pago = sum(r.valor for r in rows if r.tipo == "PASSIVO")

            months.append({"competencia": comp, "recebido": float(recebido), "pago": float(pago), "resultado": float(recebido - pago)})
            total_recebido += float(recebido)
            total_pago += float(pago)

        resultado = total_recebido - total_pago

        return render_template(
            "resumo_anual.html",
            ano=ano,
            months=months,
            total_pago=total_pago,
            total_recebido=total_recebido,
            resultado=resultado,
        )

    return app


app = create_app()
