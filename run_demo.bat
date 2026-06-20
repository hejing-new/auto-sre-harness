@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
python src/agent/engine.py
pause
