# FastPilot backend image. Refined in Phase 5 (deployment); valid + buildable now.
FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b

WORKDIR /srv

# System deps kept minimal; slim base is enough for the pure-Python stack.
# constraints.txt pins every package to uv.lock (scripts/export_constraints.sh)
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

# Copy the backend package as `app/` so `import app.config` resolves.
COPY . ./app/

EXPOSE 8000

# Railway injects $PORT; default to 8000 locally. Bind 0.0.0.0 for the container.
ENV PORT=8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
