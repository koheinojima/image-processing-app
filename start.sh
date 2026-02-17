#!/bin/bash

# Kill any existing processes on ports 8000 and 3000 to avoid conflicts
echo "Stopping existing servers..."
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:3000 | xargs kill -9 2>/dev/null

# Start Backend
echo "Starting Backend..."
cd api
# Ensure venv exists
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Python venv not found. Please run setup first."
    exit 1
fi

nohup uvicorn main:app --reload --port 8000 > ../backend.log 2>&1 &
BACKEND_PID=$!
echo "Backend started (PID: $BACKEND_PID)."
cd ..

# Start Frontend
echo "Starting Frontend..."
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
cd app
nohup npm run dev > ../frontend.log 2>&1 &
FRONTEND_PID=$!
echo "Frontend started (PID: $FRONTEND_PID)."
cd ..

echo "Waiting for servers to initialize..."
sleep 5
echo "Ready! Open http://localhost:3000"
