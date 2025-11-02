#!/usr/bin/env bash
set -e
python -m playwright install --with-deps firefox || true
python -m playwright install --with-deps chromium || true
streamlit run app.py --server.address=0.0.0.0 --server.port=${PORT:-8501}
