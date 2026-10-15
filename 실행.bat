@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "from PIL import Image" >nul 2>&1
    if errorlevel 1 goto :missing_pillow
    py -3 app.py
    goto :end
)
where python >nul 2>&1
if not errorlevel 1 (
    python -c "from PIL import Image" >nul 2>&1
    if errorlevel 1 goto :missing_pillow
    python app.py
    goto :end
)
echo Python 3 is only required for development sources, not the future bundled Windows EXE.
goto :pause
:missing_pillow
echo Pillow missing. Developer setup: python -m pip install -r requirements.txt
:pause
pause
:end
if errorlevel 1 pause
