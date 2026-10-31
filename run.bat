@echo off
REM One-click launcher for Windows. Serves API + frontend on http://localhost:8001/
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate
pip install -q -r requirements.txt
echo.
echo  Open http://localhost:8001/  (Ctrl+C to stop)
echo.
python -m backend.main
