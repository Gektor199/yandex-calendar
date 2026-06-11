FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="calendar-viewer" \
      org.opencontainers.image.description="Yandex Calendar Viewer"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_CONTAINER_NAME=calendar-viewer

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY templates ./templates
COPY pytest.ini .
COPY tests ./tests

EXPOSE 8083

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8083"]
