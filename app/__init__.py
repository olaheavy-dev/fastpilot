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

# No third-party usage telemetry from the backend (founder, 25 Nov 2026: "Turn it off
# (Recommended)"; #64). Haystack decides when it is first imported, so this must run before
# any haystack import; this package is imported first. setdefault: an operator can still opt
# in on purpose. (Qdrant's telemetry is off in the Compose file.)
os.environ.setdefault("HAYSTACK_TELEMETRY_ENABLED", "False")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
