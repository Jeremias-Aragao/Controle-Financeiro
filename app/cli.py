from __future__ import annotations

import os

import click
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash

from .extensions import db
from .models import Membership, Organization, User


def _platform_org() -> Organization:
    org = Organization.query.filter_by(slug="platform").first()
    if not org:
        org = Organization(name="Admin Org", slug="platform", plan="ENTERPRISE", status="active")
        db.session.add(org)
        db.session.commit()
    return org


@click.command("create-admin")
@with_appcontext
def create_admin() -> None:
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    if not email or not password:
        click.echo("Defina ADMIN_EMAIL e ADMIN_PASSWORD.")
        return

    if Membership.query.filter_by(role="PLATFORM_ADMIN").first():
        click.echo("Já existe PLATFORM_ADMIN. Operação cancelada.")
        return

    user = User.query.filter_by(email=email.strip().lower()).first()
    if not user:
        user = User(name="Platform Admin", email=email.strip().lower(), password_hash=generate_password_hash(password), is_admin=True)
        db.session.add(user)
        db.session.commit()

    org = _platform_org()
    db.session.add(Membership(user_id=user.id, org_id=org.id, role="PLATFORM_ADMIN"))
    db.session.commit()
    click.echo("PLATFORM_ADMIN criado com sucesso.")


@click.command("promote-admin")
@click.option("--email", required=True)
@with_appcontext
def promote_admin(email: str) -> None:
    user = User.query.filter_by(email=email.strip().lower()).first()
    if not user:
        click.echo("Usuário não encontrado.")
        return

    org = _platform_org()
    membership = Membership.query.filter_by(user_id=user.id, org_id=org.id, role="PLATFORM_ADMIN").first()
    if membership:
        click.echo("Usuário já é PLATFORM_ADMIN.")
        return

    user.is_admin = True
    db.session.add(Membership(user_id=user.id, org_id=org.id, role="PLATFORM_ADMIN"))
    db.session.commit()
    click.echo("Usuário promovido a PLATFORM_ADMIN.")
