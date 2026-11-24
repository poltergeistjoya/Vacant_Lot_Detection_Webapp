#!/usr/bin/env bash
# One-time setup for a fresh worktree: installs JS and Python dependencies and runs the tests.
# Deployment settings are tracked in deploy.env; config.local.yaml lives in the bare repo folder.
set -euo pipefail

cd "$(dirname "$0")/.."
npm ci
uv sync
npm run test:all
echo "Worktree ready."