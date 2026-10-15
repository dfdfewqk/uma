@echo off
cd /d "%~dp0"
py -3 companion.py
if errorlevel 1 pause
