FROM docker:27.5.1-cli@sha256:851f91d241214e7c6db86513b270d58776379aacc5eb9c4a87e5b47115e3065c AS docker-cli

FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.control.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.control.lock

COPY pyproject.toml ./
COPY sandbox_service ./sandbox_service
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY sandbox_runtime/seccomp.json ./sandbox_runtime/seccomp.json
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

RUN groupadd --gid 10001 sandbox \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin sandbox \
    && mkdir -p /var/lib/research-sandbox/workspaces \
    && chown -R 10001:10001 /var/lib/research-sandbox

USER 10001:10001

EXPOSE 8080
CMD ["uvicorn", "sandbox_service.main:app", "--host", "0.0.0.0", "--port", "8080"]
