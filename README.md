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

## Deploy no Render (passo a passo)
1) Suba este projeto no GitHub
2) Render -> New -> Web Service -> conecte o repo
3) Build: pip install -r requirements.txt
4) Start: gunicorn app:app
5) Render -> New -> PostgreSQL (free)
6) Conecte o DB ao Web Service (o Render injeta DATABASE_URL)
7) Em Environment do Web Service, crie SECRET_KEY

Pronto: URL pública com cadastro e login.
