from __future__ import annotations

import re
from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..decorators import active_org_id, billing_required, require_org
from ..extensions import db
from ..models import Lancamento, OrgConfig

bp = Blueprint("finance", __name__)
COMP_RE = re.compile(r"^\d{4}-\d{2}$")


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


def get_org_config(org_id: int) -> OrgConfig:
    cfg = OrgConfig.query.filter_by(org_id=org_id).first()
    if not cfg:
        cfg = OrgConfig(org_id=org_id, saldo_inicial=0.0, competencia_inicio=datetime.now().strftime("%Y-%m"))
        db.session.add(cfg)
        db.session.commit()
    if not cfg.competencia_inicio:
        cfg.competencia_inicio = datetime.now().strftime("%Y-%m")
        db.session.commit()
    return cfg


def saldo_acumulado_ate(org_id: int, competencia: str) -> tuple[float, float, float]:
    cfg = get_org_config(org_id)
    saldo0 = float(cfg.saldo_inicial or 0.0)
    comp_ini = cfg.competencia_inicio

    if competencia < comp_ini:
        return saldo0, 0.0, saldo0

    def sum_mes(comp: str) -> float:
        rows = Lancamento.query.filter_by(org_id=org_id, competencia=comp, status="BAIXADO").all()
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


@bp.route("/")
def root():
    return redirect(url_for("finance.home" if current_user.is_authenticated else "auth.login"))


@bp.route("/home")
@login_required
@require_org
@billing_required
def home():
    hoje = datetime.now().strftime("%Y-%m")
    return redirect(url_for("finance.mes", competencia=hoje))


@bp.route("/config", methods=["GET", "POST"])
@login_required
@require_org
@billing_required
def config():
    org_id = active_org_id()
    cfg = get_org_config(org_id)

    if request.method == "POST":
        saldo_inicial = request.form.get("saldo_inicial", "0").replace(",", ".").strip()
        competencia_inicio = request.form.get("competencia_inicio", "").strip()
        if not COMP_RE.match(competencia_inicio):
            flash("Competência de início inválida. Use AAAA-MM (ex.: 2026-02).")
            return redirect(url_for("finance.config"))

        try:
            saldo_val = float(saldo_inicial)
        except Exception:
            saldo_val = 0.0

        cfg.saldo_inicial = saldo_val
        cfg.competencia_inicio = competencia_inicio
        db.session.commit()
        flash("Configurações salvas.")
        return redirect(url_for("finance.home"))

    return render_template("config.html", cfg=cfg)


@bp.route("/mes/<competencia>")
@login_required
@require_org
@billing_required
def mes(competencia):
    org_id = active_org_id()
    competencia = parse_competencia(competencia)
    prev_comp = month_add(competencia, -1)
    next_comp = month_add(competencia, 1)

    rows = (
        Lancamento.query.filter_by(org_id=org_id, competencia=competencia)
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
        (passivo if d["tipo"] == "PASSIVO" else ativo).append(d)

    total_passivo_baixado = sum(l["valor"] for l in passivo if l["status"] == "BAIXADO")
    total_ativo_baixado = sum(l["valor"] for l in ativo if l["status"] == "BAIXADO")
    passivo_pendente = sum(l["valor"] for l in passivo if l["status"] != "BAIXADO")
    ativo_pendente = sum(l["valor"] for l in ativo if l["status"] != "BAIXADO")

    resultado_baixado = total_ativo_baixado - total_passivo_baixado
    resultado_projetado = (total_ativo_baixado + ativo_pendente) - (total_passivo_baixado + passivo_pendente)

    saldo_ini_mes, _res_mes, saldo_final_mes = saldo_acumulado_ate(org_id, competencia)

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


@bp.route("/novo/<competencia>", methods=["GET", "POST"])
@login_required
@require_org
@billing_required
def novo(competencia):
    org_id = active_org_id()
    competencia = parse_competencia(competencia)

    if request.method == "POST":
        l = Lancamento(
            user_id=current_user.id,
            created_by_user_id=current_user.id,
            org_id=org_id,
            tipo=request.form["tipo"],
            descricao=request.form["descricao"].strip(),
            categoria=request.form.get("categoria", "").strip() or None,
            competencia=competencia,
            data_evento=request.form["data_evento"],
            valor=float(request.form["valor"]),
            status="PENDENTE",
            data_baixa=None,
        )
        db.session.add(l)
        db.session.commit()
        return redirect(url_for("finance.mes", competencia=competencia))

    return render_template("novo_lancamento.html", competencia=competencia)


@bp.route("/editar/<int:id>/<competencia>", methods=["GET", "POST"])
@login_required
@require_org
@billing_required
def editar(id, competencia):
    org_id = active_org_id()
    competencia = parse_competencia(competencia)
    l = Lancamento.query.filter_by(id=id, org_id=org_id).first_or_404()

    if request.method == "POST":
        l.tipo = request.form["tipo"]
        l.descricao = request.form["descricao"].strip()
        l.categoria = request.form.get("categoria", "").strip() or None
        l.data_evento = request.form["data_evento"]
        l.valor = float(request.form["valor"])
        l.status = request.form.get("status", l.status)
        l.data_baixa = today_iso() if l.status == "BAIXADO" else None
        db.session.commit()
        return redirect(url_for("finance.mes", competencia=competencia))

    return render_template("editar_lancamento.html", competencia=competencia, l=l)


@bp.route("/toggle/<int:id>/<competencia>")
@login_required
@require_org
@billing_required
def toggle(id, competencia):
    org_id = active_org_id()
    competencia = parse_competencia(competencia)
    l = Lancamento.query.filter_by(id=id, org_id=org_id).first_or_404()
    l.status = "PENDENTE" if l.status == "BAIXADO" else "BAIXADO"
    l.data_baixa = today_iso() if l.status == "BAIXADO" else None
    db.session.commit()
    return redirect(url_for("finance.mes", competencia=competencia))


@bp.route("/excluir/<int:id>/<competencia>", methods=["POST"])
@login_required
@require_org
@billing_required
def excluir(id, competencia):
    org_id = active_org_id()
    competencia = parse_competencia(competencia)
    l = Lancamento.query.filter_by(id=id, org_id=org_id).first_or_404()
    db.session.delete(l)
    db.session.commit()
    return redirect(url_for("finance.mes", competencia=competencia))


@bp.route("/resumo/<ano>")
@login_required
@require_org
@billing_required
def resumo(ano):
    org_id = active_org_id()
    if not re.match(r"^\d{4}$", ano):
        abort(404)

    q = (
        db.session.query(Lancamento.competencia)
        .filter(Lancamento.org_id == org_id, Lancamento.competencia.like(f"{ano}-%"), Lancamento.status == "BAIXADO")
        .distinct()
        .order_by(Lancamento.competencia.asc())
    )

    months, total_recebido, total_pago = [], 0.0, 0.0
    for (comp,) in q.all():
        rows = Lancamento.query.filter_by(org_id=org_id, competencia=comp, status="BAIXADO").all()
        recebido = sum(r.valor for r in rows if r.tipo == "ATIVO")
        pago = sum(r.valor for r in rows if r.tipo == "PASSIVO")
        months.append({"competencia": comp, "recebido": float(recebido), "pago": float(pago), "resultado": float(recebido - pago)})
        total_recebido += float(recebido)
        total_pago += float(pago)

    return render_template(
        "resumo_anual.html",
        ano=ano,
        months=months,
        total_pago=total_pago,
        total_recebido=total_recebido,
        resultado=total_recebido - total_pago,
    )
