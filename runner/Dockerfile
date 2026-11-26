# FastPilot runner sidecar: runs untrusted code for /execute and the Agent.
# Build from the repo root (context ".") because it needs app/augmentations/code_executor.py:
#   docker build -f runner/Dockerfile .
# Hardening (no network, read-only root, dropped capabilities, no keys) lives in docker-compose.yml.
FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# app/constraints.txt pins every package to uv.lock (scripts/export_constraints.sh)
COPY runner/requirements.txt ./requirements.txt
COPY app/constraints.txt ./constraints.txt
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

# Only the executor and its package imports: no config, no services, nothing that reads keys.
COPY app/__init__.py ./app/__init__.py
COPY app/augmentations/__init__.py app/augmentations/code_executor.py app/augmentations/security.py ./app/augmentations/
COPY runner/__init__.py runner/server.py runner/slots.py ./runner/

# The socket folder. Compose mounts the runner_sock volume here; a fresh named volume copies this
# folder's owner and mode (root:root 0755), and the runner sets them again when it binds.
RUN mkdir -p /run/fastpilot && chmod 0755 /run/fastpilot

# Runs as root on purpose: root (with only SETUID/SETGID/CHOWN/KILL) switches each run to a slot uid.
CMD ["python", "-m", "runner.server"]
