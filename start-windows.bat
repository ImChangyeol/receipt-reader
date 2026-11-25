@echo off
cd /d "%~dp0"
echo Installing packages (first run only takes a minute)...
python -m pip install -q -r requirements.txt
echo Starting Receipt Reader at http://localhost:8000
python run.py
pause
