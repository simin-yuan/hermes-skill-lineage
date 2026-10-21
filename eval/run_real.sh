#!/usr/bin/env bash
# Run eval/real_model.py with a chosen interpreter and the DeepSeek key taken from an .env file.
# The key is never echoed and never appears in a command line (agent.log records those verbatim).
#
# Override the two paths with environment variables; the defaults follow a standard install layout.
set -euo pipefail

ENVF="${HERMES_ENV_FILE:-$HOME/AppData/Local/hermes/.env}"
PY="${EVAL_PYTHON:-python}"
KEY=$(grep -m1 '^DEEPSEEK_API_KEY=' "$ENVF" | sed 's/^DEEPSEEK_API_KEY=//' | tr -d '\r')
KEY=${KEY%\"}
KEY=${KEY#\"}
KEY=${KEY%\'}
KEY=${KEY#\'}
export DEEPSEEK_API_KEY="$KEY"
echo "key length: ${#DEEPSEEK_API_KEY}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
exec "$PY" eval/real_model.py "$@"
