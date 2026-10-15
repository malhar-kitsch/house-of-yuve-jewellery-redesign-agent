#!/bin/sh
cd "$(dirname "$0")" && .venv/bin/uvicorn app.server:app --port 8000
