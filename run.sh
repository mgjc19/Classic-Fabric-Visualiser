#!/bin/bash
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r backend/requirements.txt
else
    source .venv/bin/activate
fi

echo "Starting Classic Fabric Visualiser on http://localhost:8765"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8765 --reload
