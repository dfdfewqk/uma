@echo off
setlocal
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt
if errorlevel 1 goto :fail
py -3 -m unittest discover -s tests -q
if errorlevel 1 goto :fail
py -3 -m compileall -q capture_integrity_r24.py live_state_r24.py companion.py offline_replay_ui_r23.py offline_replay_r23.py
if errorlevel 1 goto :fail
py -3 -m pip install "pyinstaller>=6.10,<7"
if errorlevel 1 goto :fail
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name UmaTrainerKR_Companion --hidden-import=screen_r4 --hidden-import=cv2 --hidden-import=numpy companion.py
if errorlevel 1 goto :fail
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name UmaTrainerKR_GameTest --add-data "scenario_policies\island_post_patch_v1.json;scenario_policies" live_test_ui_r22.py
if errorlevel 1 goto :fail
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name UmaTrainerKR_Preflight --add-data "examples\r23_demo_manifest.json;examples" --add-data "examples\r22_mock_roi.json;examples" --add-data "examples\r22_mock_1.png;examples" --add-data "examples\r22_mock_2.png;examples" --add-data "examples\r22_mock_3.png;examples" --add-data "examples\r22_mock_4.png;examples" --add-data "examples\r22_mock_5.png;examples" offline_replay_ui_r23.py
if errorlevel 1 goto :fail
echo Built Companion, GameTest and Preflight EXEs (game compatibility unverified)
pause
exit /b 0
:fail
echo Build failed; review output.
pause
exit /b 1
