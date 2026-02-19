# Controle Financeiro SaaS (Flask + SQLAlchemy)

## O que existe agora
- Arquitetura em pacote Flask (`app/`) com blueprints (`auth`, `finance`, `org`, `admin`, `billing`, `webhooks`).
- Multi-tenant real por organização com `Membership` e organização ativa em sessão (`active_org_id`).
- Painel `/admin` exclusivo para `PLATFORM_ADMIN`.
- Billing por organização com checkout PIX Mercado Pago + webhook de confirmação.
- Guardas de acesso por login, organização ativa, role e status de billing.
- Compatível com SQLite (dev) e Postgres (Render).

## Setup local
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

## Variáveis de ambiente
Obrigatórias:
- `SECRET_KEY`

Opcionais/recomendadas:
- `DATABASE_URL` (default: sqlite:///local.db)
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`
- `ALLOW_FIRST_ADMIN_FROM_REGISTER` (`true/false`)
- `MP_ACCESS_TOKEN`
- `MP_WEBHOOK_SECRET`
- `MP_NOTIFICATION_URL` (URL pública do webhook)

Exemplo Linux/macOS:
```bash
export SECRET_KEY="uma-chave-forte"
export ADMIN_EMAIL="admin@seu-dominio.com"
export ADMIN_PASSWORD="senha-super-forte"
export MP_ACCESS_TOKEN="APP_USR-***"
export MP_WEBHOOK_SECRET="seu_secret"
export MP_NOTIFICATION_URL="https://seu-app.onrender.com/webhooks/mercadopago"
```

## Migrações (Flask-Migrate / Alembic)
```bash
flask --app app.py db init      # apenas 1x
flask --app app.py db migrate -m "init saas"
flask --app app.py db upgrade
```

## Rodar local
```bash
flask --app app.py run
```

## Bootstrap admin
Auto-bootstrap na inicialização:
- se não existir `PLATFORM_ADMIN` e `ADMIN_EMAIL` + `ADMIN_PASSWORD` estiverem definidos, cria usuário admin + organização platform.

Comandos CLI:
```bash
flask --app app.py create-admin
flask --app app.py promote-admin --email usuario@empresa.com
```

## Fluxo multi-tenant
1. Login.
2. Selecionar organização em `/org/select` (automático se tiver apenas 1).
3. Usar financeiro normalmente com isolamento por org.

## Billing PIX Mercado Pago
- Tela: `/billing`
- Checkout: `POST /billing/checkout?plan=PRO|AGENCY|ENTERPRISE`
- Status: `/billing/status`
- Webhook: `POST /webhooks/mercadopago`

### Teste manual de webhook (sem expor segredo)
> Gere a assinatura HMAC com `MP_WEBHOOK_SECRET` localmente e envie no header `x-signature`.

```bash
PAYLOAD='{"data":{"id":"123456789"}}'
SIG=$(python - <<'PY'
import hmac, hashlib, os
payload = '{"data":{"id":"123456789"}}'.encode()
secret = os.getenv('MP_WEBHOOK_SECRET','dev-secret').encode()
print(hmac.new(secret, payload, hashlib.sha256).hexdigest())
PY
)

curl -X POST http://127.0.0.1:5000/webhooks/mercadopago \
  -H "Content-Type: application/json" \
  -H "x-signature: $SIG" \
  -d "$PAYLOAD"
```

## Render
- Use `DATABASE_URL` apontando para seu Postgres do Render.
- Configure `SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `MP_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET`.
- Recomendações:
  1. Criar admin apenas uma vez.
  2. Remover `ADMIN_PASSWORD` após bootstrap.
  3. Não versionar segredos.
