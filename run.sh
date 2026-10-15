#!/usr/bin/env bash
# Launch PDF Builder from the project directory.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"
if [[ ! -x .venv/bin/python ]]; then
  echo "The environment is missing. Run ./install.sh first." >&2
  exit 1
fi
exec .venv/bin/python -m pdfbuilder.app "$@"
