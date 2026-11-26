"""FastPilot backend — FastAPI service for the learning-companion RAG product.

Package layout (filled phase by phase, plan §3):
  config.py        settings (Phase 0)
  models.py        request/response schemas (Phase 0)
  main.py          endpoints + SSE + lifespan (Phase 0 skeleton → Phase 1/3)
  prompts/         templates + Opik registry (Phase 1)
  components/      Qdrant hybrid retriever + Voyage reranker (Phase 1)
  services/        rag_pipeline, query_router, conversation, semantic_cache (Phase 1)
  augmentations/   security, code_executor, agent_orchestrator (Phase 1/3) — Week-6 components
"""

import os

__version__ = "0.0.0"

# No third-party telemetry from the backend (founder, 25 Nov 2026; #64): Haystack's usage
# events to PostHog ("Turn it off (Recommended)"), Opik's own crash reports to Sentry ("Turn
# it off too (Recommended)"; Opik traces are unaffected) and Hugging Face Hub telemetry.
# Forced, not defaulted ("Force off (Recommended)"): an env file can't switch them back on.
# The libraries read these when first imported, so every entry point imports `app` first
# (wiki/coding-conventions.md). Qdrant's telemetry is off in the Compose file.
os.environ["HAYSTACK_TELEMETRY_ENABLED"] = "False"
os.environ["OPIK_SENTRY_ENABLE"] = "false"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

# Opik's connection monitor pings `is-alive/ping` every 10 s per client, traffic or not; with two
# clients (ours and @track's) that was about 15,850 pings a day (#62). After any failed send or
# ping, Opik holds every trace locally until the next successful ping, and loses them if the
# backend stops first; 60 s keeps that wait to a minute at about 2,880 pings a day (founder,
# 26 Nov 2026: "Every 60 seconds (Recommended)"). Defaulted, not forced: an env file may change it.
os.environ.setdefault("OPIK_CONNECTION_MONITOR_PING_INTERVAL", "60")
