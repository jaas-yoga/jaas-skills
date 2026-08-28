FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY src/ ./src/
COPY examples/ ./examples/
COPY README.md ./

# --frozen uses the committed uv.lock as-is rather than re-resolving, so the
# image gets the exact versions tested in CI (matches jaas-guardrails'
# Dockerfile convention). No --extra dev: excludes pytest/ruff/pip-audit.
RUN uv sync --frozen

# storage_root/policy_dir (common/config.py) default to relative paths that
# resolve against the process's cwd — WORKDIR /app makes that
# /app/.local_registry, which deploy/docker-compose.yml mounts as a volume
# so registry data survives container restarts/redeploys.

EXPOSE 8027

CMD ["uv", "run", "jaasctl", "serve", "--host", "0.0.0.0", "--port", "8027"]
