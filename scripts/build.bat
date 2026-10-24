@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo [!] .venv not found. Run:
  echo     python -m venv .venv
  echo     .venv\Scripts\pip install websocket-client pyinstaller
  pause
  exit /b 1
)
if exist "release\QuestAwayHelper.exe" (
  taskkill /F /IM QuestAwayHelper.exe >nul 2>nul
)
".venv\Scripts\python.exe" -m PyInstaller --onedir --windowed --noconfirm ^
  --name QuestAwayHelper --distpath release --workpath build --specpath build ^
  "src\assistant.pyw"
copy /Y "tools\启动-自检.bat" "release\QuestAwayHelper\启动-自检.bat" >nul
copy /Y "docs\使用说明.md"   "release\QuestAwayHelper\使用说明.md" >nul
echo.
echo [OK] build done: release\QuestAwayHelper\
pause
