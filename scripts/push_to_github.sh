#!/usr/bin/env bash
set -euo pipefail

REMOTE_URL="${1:-https://github.com/mkarp87/WeatherTelegramAlerts.git}"
BRANCH="${2:-main}"

if [ -f config.yaml ]; then
  echo "Refusing to continue because config.yaml exists in this directory." >&2
  echo "Move private config files outside the repo before committing." >&2
  exit 1
fi

if [ ! -d .git ]; then
  git init
  git branch -M "$BRANCH"
fi

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

git add .
git status --short

echo "Review the staged files above. To commit and push, run:"
echo "  git commit -m 'Harden WeatherTelegramAlerts deployment'"
echo "  git push origin $BRANCH"
