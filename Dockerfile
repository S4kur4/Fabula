FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --gid 10001 fabula \
    && useradd --uid 10001 --gid fabula --no-create-home --shell /usr/sbin/nologin fabula

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=fabula:fabula . .
RUN mkdir -p /app/var/media/original /app/var/media/thumbs /app/var/tmp \
    && chown -R fabula:fabula /app/var

USER fabula

EXPOSE 5000
VOLUME ["/app/var"]

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "120", "--no-control-socket", "--access-logfile", "-", "--error-logfile", "-", "wsgi:app"]
