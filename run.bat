@echo off
cd /d "%~dp0"
REM Python lookup (not PATH): 1) project .venv  2) conda agent-py313 (relative, works on E: and D:)
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0..\..\envs\miniconda3\envs\agent-py313\python.exe" set "PY=%~dp0..\..\envs\miniconda3\envs\agent-py313\python.exe"
if not defined PY ( echo Python not found. Run ..\..\_setup\setup-dev-env.bat & exit /b 1 )
set "PYTHONUTF8=1"
REM Usage: run.bat "keyword" [options]   (all args go to main.py; run.bat --help)
"%PY%" main.py %*