Set-Location $PSScriptRoot

Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "Starting SalesGenie AI Services..." -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan

# Check if port 8001 is already active
$port8001 = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue
if (-not $port8001) {
    Write-Host "Starting FastAPI Backend on http://127.0.0.1:8001..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$PSScriptRoot'; .\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8001"
    Start-Sleep -Seconds 2
} else {
    Write-Host "FastAPI Backend is already running on port 8001." -ForegroundColor Green
}

# Check if port 8501 is already active
$port8501 = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue
if (-not $port8501) {
    Write-Host "Starting Streamlit UI on http://127.0.0.1:8501..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$PSScriptRoot'; .\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false"
    Start-Sleep -Seconds 3
} else {
    Write-Host "Streamlit UI is already running on port 8501." -ForegroundColor Green
}

Write-Host "===================================================" -ForegroundColor Green
Write-Host "SalesGenie is up and running!" -ForegroundColor Green
Write-Host "Backend API Docs: http://127.0.0.1:8001/docs" -ForegroundColor Yellow
Write-Host "Frontend Web UI:  http://127.0.0.1:8501" -ForegroundColor Yellow
Write-Host "===================================================" -ForegroundColor Green
