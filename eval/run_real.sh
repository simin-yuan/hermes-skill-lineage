#!/usr/bin/env bash
# Run eval/real_model.py with the pinned Hermes venv and the DeepSeek key taken from .env.
# The key is never echoed and never appears in a command line (agent.log records those verbatim).
set -euo pipefail

ENVF="C:/Users/Simon/AppData/Local/hermes/.env"
KEY=$(grep -m1 '^DEEPSEEK_API_KEY=' "$ENVF" | sed 's/^DEEPSEEK_API_KEY=//' | tr -d '\r')
KEY=${KEY%\"}
KEY=${KEY#\"}
KEY=${KEY%\'}
KEY=${KEY#\'}
export DEEPSEEK_API_KEY="$KEY"
echo "key length: ${#DEEPSEEK_API_KEY}"

REPO="C:/Users/Simon/AppData/Local/hermes/cache/scratch/hs11"
PY="C:/Users/Simon/AppData/Local/hermes/cache/scratch/hermes-pin-c5a3c0f/.venv/Scripts/python.exe"
cd "$REPO"
exec "$PY" eval/real_model.py "$@"
