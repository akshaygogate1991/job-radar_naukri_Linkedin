@echo off
REM ─────────────────────────────────────────────
REM  Job Apply Dashboard launcher
REM  Double-click this file to open the dashboard.
REM ─────────────────────────────────────────────
cd /d "%~dp0"

REM Install streamlit the first time if it's missing
python -c "import streamlit" 2>NUL
if errorlevel 1 (
    echo Installing Streamlit ^(first run only^)...
    python -m pip install streamlit
)

echo Starting dashboard... your browser will open shortly.
python -m streamlit run dashboard.py

pause
