# ---- ClipStream container image ----
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
RUN useradd -m appuser && mkdir -p /srv/media && chown -R appuser /srv
USER appuser

EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/healthz')"
# 2 worker processes x 4 threads per container; more containers are added by the autoscaler
CMD ["gunicorn", "--chdir", "app", "-w", "2", "--threads", "4", "-b", "0.0.0.0:8000", "main:app"]
