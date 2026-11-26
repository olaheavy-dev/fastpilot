# FastPilot frontend image (Streamlit). Refined in Phase 2/5; valid + buildable now.

# --- Monaco editor files, served from our own site instead of jsDelivr (#65) -----------------
# streamlit-monaco 0.1.3 is built for monaco-editor 0.36.1. Change MONACO_VERSION and
# MONACO_SHA256 only together with streamlit-monaco (#69), and re-check monaco_patch.py.
FROM python:3.12-slim AS monaco
ARG MONACO_VERSION=0.36.1
ARG MONACO_SHA256=0ffa1c42ef6939339031a1e9c72af6cc863773febe992b85a746dc24a6e07251
RUN python - <<EOF
import hashlib, io, sys, tarfile, urllib.request
url = "https://registry.npmjs.org/monaco-editor/-/monaco-editor-${MONACO_VERSION}.tgz"
data = urllib.request.urlopen(url, timeout=120).read()
got = hashlib.sha256(data).hexdigest()
if got != "${MONACO_SHA256}":
    sys.exit(f"monaco-editor ${MONACO_VERSION}: SHA-256 mismatch: expected ${MONACO_SHA256}, got {got}")
with tarfile.open(fileobj=io.BytesIO(data)) as tar:
    members = [m for m in tar.getmembers() if m.name.startswith("package/min/vs/")]
    for m in members:
        m.name = "vs/" + m.name.removeprefix("package/min/vs/")
    tar.extractall("/monaco", members=members, filter="data")
print(f"monaco-editor ${MONACO_VERSION}: {len(members)} files, SHA-256 checked")
EOF

# --- The app ----------------------------------------------------------------------------------
FROM python:3.12-slim

WORKDIR /srv

# constraints.txt pins every package to uv.lock (scripts/export_constraints.sh)
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

# Monaco next to streamlit-monaco's built page (Streamlit serves that folder to the browser).
COPY --from=monaco /monaco/vs /usr/local/lib/python3.12/site-packages/streamlit_monaco/frontend/build/monaco/vs

COPY . ./

# Rewrite the jsDelivr address to ./monaco/vs; fails the build if the address moved (#65).
RUN python monaco_patch.py

EXPOSE 8501

# Railway injects $PORT; default 8501 locally. Bind 0.0.0.0 + disable CORS prompt.
ENV PORT=8501
CMD ["sh", "-c", "streamlit run app.py --server.port ${PORT} --server.address 0.0.0.0"]
