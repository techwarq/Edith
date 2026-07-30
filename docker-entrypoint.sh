#!/bin/sh
# monid's CLI stores its auth in ~/.config/monid, which isn't on the mounted
# volume (EDITH_HOME=/data) — it resets on every fresh container, unlike the
# SQLite DB. Re-authenticate from MONID_API_KEY on every startup instead.
# Optional, like every other integration here (Qdrant/Temporal/Firebase):
# skipped entirely if the env var isn't set, rather than failing startup.
if [ -n "$MONID_API_KEY" ]; then
  monid setup --client edith-backend >/dev/null 2>&1 || true
  monid keys add -k "$MONID_API_KEY" -l main >/dev/null 2>&1 || true
fi

# Worker runs in the background, sharing this container's filesystem (and thus the
# same SQLite file on the mounted volume) as the web server — device tokens and
# scheduled-job output only make sense if both processes see the same database.
# Backgrounded with `&` so a worker crash (e.g. Temporal misconfigured) doesn't
# take the container down with it; only uvicorn is the tracked main process.
python -m edith.temporal.worker &
uvicorn edith.server:app --host 0.0.0.0 --port ${PORT:-8000}
