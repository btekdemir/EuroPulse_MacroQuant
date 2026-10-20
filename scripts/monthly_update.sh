#!/usr/bin/env bash
# Monthly update: pull the latest Eurostat release, rerun everything, record the new forecast in the
# ledger (only if the data changed), score past forecasts, and commit the results.
#   bash scripts/monthly_update.sh            # commit locally
#   PUSH=1 bash scripts/monthly_update.sh     # also push (the remote's commit time then dates the ledger)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"

if [ -n "$(git status --porcelain -- . ':!outputs' ':!ledger' ':!data')" ]; then
  echo "Uncommitted code changes: commit them first, or the ledger will refuse to record (D25)." >&2
  exit 1
fi

"$PY" run.py
PYTHONPATH=src "$PY" -m hicp.ledger

# Commit only when something real changed: a new ledger entry, a newly scored forecast, or a new
# forecast. (Other outputs carry run timestamps and change on every run.)
if git diff --quiet -- ledger outputs/ledger_scores.json outputs/forecast.json; then
  echo "Nothing new (same data, nothing newly scored): no commit."
  git checkout -- outputs 2>/dev/null || true
  exit 0
fi
git add ledger outputs
git commit -q -m "Monthly update: $(date -u +%Y-%m-%d) ledger and outputs"
echo "Committed: $(git log --oneline -1)"
if [ "${PUSH:-0}" = "1" ]; then git push; fi
