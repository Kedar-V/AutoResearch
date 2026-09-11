# AutoResearch Langfuse self-host
#
# Selectable observability modes (backend/.env):
#   AUTORESEARCH_OBSERVABILITY_BACKEND=noop              # default, no vendor
#   AUTORESEARCH_OBSERVABILITY_BACKEND=langfuse-cloud    # Langfuse Cloud (Free/Pro)
#   AUTORESEARCH_OBSERVABILITY_BACKEND=langfuse-selfhost # this stack
#   AUTORESEARCH_OBSERVABILITY_BACKEND=langfuse          # generic: use LANGFUSE_HOST + keys
#
# Quick start
#   cp ops/langfuse/.env.example ops/langfuse/.env
#   make langfuse-selfhost-up
#   # UI: http://localhost:3000  (admin@autoresearch.local / changeme-langfuse-admin)
#   # Then in backend/.env:
#   AUTORESEARCH_OBSERVABILITY_BACKEND=langfuse-selfhost
#   AUTORESEARCH_LANGFUSE_PUBLIC_KEY=pk-lf-autoresearch-local
#   AUTORESEARCH_LANGFUSE_SECRET_KEY=sk-lf-autoresearch-local-dev-secret
#   AUTORESEARCH_LANGFUSE_HOST=http://localhost:3000
#
# Stop: make langfuse-selfhost-down
#
# Upstream: https://langfuse.com/self-hosting
# Compose is a lightly patched copy of langfuse/langfuse docker-compose.yml
# (Postgres published on host 5434 to avoid clashing with AutoResearch Postgres).
