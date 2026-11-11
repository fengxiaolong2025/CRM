@echo off
cd /d %~dp0backend
call "%USERPROFILE%\.workbuddy\binaries\python\envs\crm\Scripts\activate.bat"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
