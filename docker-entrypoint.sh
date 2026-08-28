#!/bin/sh
set -eu

python -m app.db.seed
python -m app.agent.finance_graph --setup

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
