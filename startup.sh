#!/bin/bash
PORT=${PORT:-8000}
echo "Launching Chainlit on port $PORT..."
chainlit run app.py --host 0.0.0.0 --port $PORT
