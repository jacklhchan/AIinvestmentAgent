#!/usr/bin/env bash
set -euo pipefail

if command -v hermes >/dev/null 2>&1; then
  hermes --version || true
  exit 0
fi

curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

echo "Open a new shell or run: source ~/.zshrc"
echo "Then run: hermes model"
echo "Pick OpenAI Codex, complete ChatGPT OAuth, and merge deploy/hermes/config.snippet.yaml into ~/.hermes/config.yaml"
