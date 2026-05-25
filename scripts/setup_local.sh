#!/usr/bin/env bash
set -euo pipefail

cd /Users/apple/Documents/AIinvestmentAgent
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp -n .env.example .env
python -m invest_agent.cli seed
python -m pytest

echo "Run: source .venv/bin/activate && python -m invest_agent.api"
