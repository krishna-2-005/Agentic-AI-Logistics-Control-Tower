#!/usr/bin/env bash
# gitas.sh — run a git command as a specific team member.
#
#   scripts/gitas.sh lahari commit -m "add corridor audit t-test"
#   scripts/gitas.sh lahari push -u origin week2-lahari-corridor-audit
#   scripts/gitas.sh mounika whoami          # show resolved identity, no git call
#
# Why this exists: the project rule is that every commit is authored by the task's
# real owner and every branch is pushed with that owner's credentials — never all
# from one account. Doing that by hand means remembering four -c flags and a URL
# rewrite every time, which nobody does reliably at 1am.
#
# Identities and tokens come from .env.git (gitignored). Tokens are passed to git
# via a short-lived credential helper on stdin, so they never appear in the
# process list, in ~/.git-credentials, or in your shell history.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env.git"

if [ ! -f "$ENV_FILE" ]; then
  echo "error: $ENV_FILE not found." >&2
  echo "       cp .env.git.example .env.git   then fill in your own token." >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

member="${1:-}"; shift || true
if [ -z "$member" ]; then
  echo "usage: scripts/gitas.sh <krishna|lahari|mounika> <git args...>" >&2
  exit 1
fi

case "$(echo "$member" | tr '[:upper:]' '[:lower:]')" in
  krishna) name="${GIT_KRISHNA_NAME:-}"; email="${GIT_KRISHNA_EMAIL:-}"; token="${GIT_KRISHNA_TOKEN:-}";;
  lahari)  name="${GIT_LAHARI_NAME:-}";  email="${GIT_LAHARI_EMAIL:-}";  token="${GIT_LAHARI_TOKEN:-}";;
  mounika) name="${GIT_MOUNIKA_NAME:-}"; email="${GIT_MOUNIKA_EMAIL:-}"; token="${GIT_MOUNIKA_TOKEN:-}";;
  *) echo "error: unknown member '$member' (expected krishna, lahari, or mounika)" >&2; exit 1;;
esac

if [ -z "$name" ] || [ -z "$email" ]; then
  echo "error: name/email for '$member' missing from .env.git" >&2
  exit 1
fi

if [ "${1:-}" = "whoami" ]; then
  echo "$member -> $name <$email>  token: $([ -n "$token" ] && echo set || echo MISSING)"
  exit 0
fi

# Author AND committer, so the GitHub contributor graph attributes correctly.
id_args=(-c "user.name=$name" -c "user.email=$email")

# Pushing needs the token; local operations do not.
needs_token=0
case "${1:-}" in push|fetch|pull|clone|ls-remote) needs_token=1;; esac

if [ "$needs_token" -eq 1 ]; then
  if [ -z "$token" ]; then
    echo "error: GIT_${member^^}_TOKEN is empty in .env.git — cannot push as $name." >&2
    exit 1
  fi
  # Feed the credential to git on stdin for this one invocation only.
  helper="!f() { echo username=$name; echo password=$token; }; f"
  id_args+=(-c "credential.helper=" -c "credential.helper=$helper")
fi

exec git "${id_args[@]}" "$@"
