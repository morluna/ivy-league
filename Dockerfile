FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 DATABASE_PATH=/data/sessions.sqlite3
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home rally && mkdir /data && chown rally:rally /data
COPY pickleball ./pickleball
COPY static ./static
COPY wsgi.py ./
COPY scripts ./scripts
EXPOSE 8000
CMD ["python", "scripts/container_start.py"]
