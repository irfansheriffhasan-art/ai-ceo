#!/usr/bin/env bash
# Start AI-CEO and open the Studio.   ./start.sh   |   ./start.sh --demo   (offline demo, no AI model needed)
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Run ./setup.sh first."; exit 1; }
if [ "${1:-}" = "--demo" ]; then
  exec .venv/bin/python main.py --provider mock serve
fi
exec .venv/bin/python main.py serve "$@"
