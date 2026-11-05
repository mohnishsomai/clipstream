# ClipStream – scalable short-video sharing (COM769 Coursework 2)

TikTok-style web app: sign up / log in, upload videos, like, comment (with AI sentiment tagging), share.

| Layer | Local dev | Azure production |
|---|---|---|
| Web/API | Flask + Gunicorn (Docker) | Azure Container Apps, autoscale 1–10 replicas |
| Media | local disk | Azure Blob Storage |
| Data | SQLite | Azure Cosmos DB (serverless, partitioned) |
| AI | built-in lexicon | Azure AI Language sentiment |
| CI/CD | pytest | GitHub Actions → ACR → Container Apps |

Run locally: `pip install -r requirements.txt && python app/main.py` → http://localhost:8000
Tests: `python -m pytest -q`  ·  Multi-container: `docker compose up --build --scale web=3`
Deploy: see **DEPLOY.md**.
