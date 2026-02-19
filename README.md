# Financeiro do Magnata — R02 (Publicável) ✅
Flask + Login + Multiusuário + PostgreSQL (produção)

## Hospedagem gratuita escolhida: Render
- Render tem documentação oficial para deploy de Flask e possui plano gratuito para Web Services. 
- Também oferece Postgres gratuito (com limitações), ótimo para hobby/teste.

## Rodar local (SQLite)
1) python -m venv .venv
2) .\.venv\Scripts\activate
3) pip install -r requirements.txt
4) python app.py
5) http://127.0.0.1:5000

## Variáveis de ambiente (produção)
- SECRET_KEY
- DATABASE_URL (Postgres; Render injeta ao conectar o DB)
- ADMIN_EMAIL
- ADMIN_PASSWORD
- ALLOW_FIRST_ADMIN_FROM_REGISTER (opcional; `true` para mostrar opção de admin na tela de cadastro enquanto não existir admin)

## Bootstrap seguro do primeiro ADMIN (PLATFORM_ADMIN)
- O sistema cria o primeiro admin automaticamente **somente se não existir nenhum usuário com `is_admin=True`**.
- O bootstrap usa exclusivamente variáveis de ambiente (`ADMIN_EMAIL` e `ADMIN_PASSWORD`) e hash de senha com `generate_password_hash`.
- Também existe o comando manual:

```bash
flask create-admin
```

### Configurar variáveis de ambiente
Windows (PowerShell):

```powershell
setx ADMIN_EMAIL "seu_email"
setx ADMIN_PASSWORD "sua_senha"
```

Mac/Linux:

```bash
export ADMIN_EMAIL="seu_email"
export ADMIN_PASSWORD="sua_senha"
```

### Recomendações de segurança
1) Crie o admin apenas uma vez.
2) Após criar o admin, remova `ADMIN_PASSWORD` das variáveis de ambiente.
3) Se usar cadastro via tela, defina `ALLOW_FIRST_ADMIN_FROM_REGISTER=true` só temporariamente e volte para `false` após criar o primeiro admin.
4) Nunca suba senha no GitHub.
5) Sempre use `SECRET_KEY` forte.

## Deploy no Render (usando o banco existente `financeiro-magnata-db`)
1) Suba este projeto no GitHub.
2) No Render, garanta que o PostgreSQL `financeiro-magnata-db` já está criado.
3) Render -> New -> Web Service -> conecte o repositório.
4) O `render.yaml` já está pronto para vincular automaticamente `DATABASE_URL` ao banco `financeiro-magnata-db`.
5) Configure no Web Service:
   - `ADMIN_EMAIL`
   - `ADMIN_PASSWORD` (somente para bootstrap/criação inicial)
   - `ALLOW_FIRST_ADMIN_FROM_REGISTER=true` (opcional, se quiser aparecer checkbox de admin na tela `/register`)
6) Faça o primeiro deploy.
7) Após o admin ser criado, remova `ADMIN_PASSWORD` do ambiente e retorne `ALLOW_FIRST_ADMIN_FROM_REGISTER=false`.

Pronto: app no Render com o banco existente e bootstrap admin seguro.
