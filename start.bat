@echo off
echo Windows Screen Recorder
echo ========================
echo.
echo Installing dependencies...
pip install -r requirements.txt
echo.
echo Starting Screen Recorder...
python screen_recorder.py
pause
