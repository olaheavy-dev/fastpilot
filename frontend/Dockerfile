# FastPilot frontend image (Streamlit). Refined in Phase 2/5; valid + buildable now.
FROM python:3.12-slim

WORKDIR /srv

# constraints.txt pins every package to uv.lock (scripts/export_constraints.sh)
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

COPY . ./

EXPOSE 8501

# Railway injects $PORT; default 8501 locally. Bind 0.0.0.0 + disable CORS prompt.
ENV PORT=8501
CMD ["sh", "-c", "streamlit run app.py --server.port ${PORT} --server.address 0.0.0.0"]
