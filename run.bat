@echo off
cd /d "%~dp0"
echo ===================================================
echo Starting SalesGenie AI Services...
echo ===================================================

start "SalesGenie - Backend API (Port 8001)" cmd /k ".\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8001"

echo Waiting for backend to initialize...
ping 127.0.0.1 -n 3 >nul

start "SalesGenie - Streamlit UI (Port 8501)" cmd /k ".\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false"

echo ===================================================
echo Backend API Docs: http://127.0.0.1:8001/docs
echo Frontend Web UI:  http://127.0.0.1:8501
echo ===================================================
