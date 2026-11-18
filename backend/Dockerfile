FROM python:3.12-slim-bookworm
WORKDIR /srv
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock && pip check
COPY . .
CMD ["sh","-ec","alembic upgrade head && python -m app.seed && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
