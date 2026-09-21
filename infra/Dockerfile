FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml ./
COPY packages ./packages
COPY fixtures ./fixtures
COPY apps/control_api ./apps/control_api
COPY apps/maintenance_worker ./apps/maintenance_worker
COPY suites ./suites
COPY docs ./docs
COPY assure.yaml ./
RUN uv sync --no-dev
ENV PATH="/app/.venv/bin:$PATH"
CMD ["assure-api"]
