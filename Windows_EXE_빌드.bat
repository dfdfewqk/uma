@echo off
setlocal
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt
if errorlevel 1 goto :fail
py -3 -m unittest discover -s tests -v
if errorlevel 1 goto :fail
py -3 -m compileall -q capture_integrity_r24.py live_state_r24.py companion.py offline_replay_ui_r23.py offline_replay_r23.py
if errorlevel 1 goto :fail
py -3 -m pip install "pyinstaller>=6.10,<7"
if errorlevel 1 goto :fail
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name UmaTrainerKR --add-data "examples\synthetic_r4.png;examples" --add-data "examples\synthetic_roi.json;examples" --add-data "research\sources.json;research" --add-data "research\r13\japan_island_2025_events.json;research/r13" --add-data "research\r14\lineage_and_calendar.json;research/r14" --add-data "scenario_policies\island_post_patch_v1.json;scenario_policies" --add-data "research\video_reviews\verified_turns.csv;research/video_reviews" --add-data "research\jp_post_patch_2025\sources.csv;research/jp_post_patch_2025" --add-data "research\jp_post_patch_2025\video_chapters.csv;research/jp_post_patch_2025" --add-data "research\video_reviews\review_queue.csv;research/video_reviews" app.py
if errorlevel 1 goto :fail
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name UmaTrainerKR_Companion --hidden-import=screen_r4 --hidden-import=cv2 --hidden-import=numpy --add-data "scenario_policies\island_post_patch_v1.json;scenario_policies" companion.py
if errorlevel 1 goto :fail
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name UmaTrainerKR_GameTest --add-data "scenario_policies\island_post_patch_v1.json;scenario_policies" live_test_ui_r22.py
if errorlevel 1 goto :fail
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name UmaTrainerKR_Preflight --add-data "scenario_policies\island_post_patch_v1.json;scenario_policies" --add-data "examples\r23_demo_manifest.json;examples" --add-data "examples\r22_mock_roi.json;examples" --add-data "examples\r22_mock_1.png;examples" --add-data "examples\r22_mock_2.png;examples" --add-data "examples\r22_mock_3.png;examples" --add-data "examples\r22_mock_4.png;examples" --add-data "examples\r22_mock_5.png;examples" offline_replay_ui_r23.py
if errorlevel 1 goto :fail
if not exist "dist\UmaTrainerKR.exe" goto :fail
if not exist "dist\UmaTrainerKR_Companion.exe" goto :fail
if not exist "dist\UmaTrainerKR_GameTest.exe" goto :fail
if not exist "dist\UmaTrainerKR_Preflight.exe" goto :fail
echo Built dist\UmaTrainerKR.exe, UmaTrainerKR_Companion.exe, UmaTrainerKR_GameTest.exe, UmaTrainerKR_Preflight.exe
pause
exit /b 0
:fail
echo Build failed; review the log above.
pause
exit /b 1
