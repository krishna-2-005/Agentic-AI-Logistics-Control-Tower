#!/usr/bin/env bash
# Regenerate requirements.lock.
#
#     bash scripts/lock_requirements.sh
#
# Why this is a script and not just `pip-compile`
# -----------------------------------------------
# pip-compile resolves against the machine it runs on, so a lock built on
# Windows contains Windows-only transitive packages -- `pywin32` (via mcp) and
# `pywinpty` (via jupyter-server) -- with no environment marker. Installing that
# file on Linux fails at `pywin32==312`, which is exactly how CI failed the first
# time this lock was committed.
#
# The lock is meant to be the reproducible install, so it has to install
# everywhere the project claims to run. This adds the markers pip-compile could
# not know to add, and it is idempotent: re-running it re-adds them after the
# next compile wipes them.
#
# The proper fix is a resolver that locks for multiple platforms at once (uv
# does this). That is a dependency change and a decision for the team, so until
# then this keeps the lock honest.

set -euo pipefail
cd "$(dirname "$0")/.."

echo "resolving requirements.txt ..."
python -m piptools compile \
  --quiet \
  --strip-extras \
  --output-file=requirements.lock \
  requirements.txt

# Packages that only exist on Windows. Without a marker, pip on Linux tries to
# find them and stops the whole install.
WINDOWS_ONLY=(pywin32 pywinpty)

echo "adding platform markers ..."
for pkg in "${WINDOWS_ONLY[@]}"; do
  # Only touch a pinned line that does not already carry a marker.
  if grep -qE "^${pkg}==[^;]+$" requirements.lock; then
    sed -i -E "s|^(${pkg}==[^;]+)$|\1 ; sys_platform == \"win32\"|" requirements.lock
    echo "  ${pkg}: marked win32-only"
  fi
done

echo
echo "wrote requirements.lock"
echo "verify on this platform:  pip install -r requirements.lock"
echo "CI verifies it on Linux in the 'pytest from requirements.lock' job."
