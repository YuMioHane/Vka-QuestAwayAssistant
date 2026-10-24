@echo off
chcp 936 >nul
cd /d "%~dp0"
title QuestAway 助手 - 启动自检
setlocal enabledelayedexpansion
set OK=1

echo ==========================================
echo   QuestAway 助手  启动自检
echo ==========================================
ver
echo.

if not exist "_internal\python312.dll" (
  echo [X] 缺少 _internal 里的文件。
  echo     原因：只把 exe 拖出来了，或者直接在压缩包里双击。
  echo     做法：把压缩包整个解压到一个普通文件夹，再从里面运行。
  set OK=0
)

if not exist "%SystemRoot%\System32\ucrtbase.dll" (
  echo [X] 系统缺少 ucrtbase.dll（通用 C 运行库）。
  echo     系统太老或被人精简过。装「Visual C++ 2015-2022 运行库 x64」再试。
  set OK=0
)

if /i "%PROCESSOR_ARCHITECTURE%"=="x86" (
  echo [X] 这是 32 位 Windows，本程序是 64 位，无法运行。
  set OK=0
)

if not exist "QuestAwayHelper.exe" (
  echo [X] 当前目录没有 QuestAwayHelper.exe，别单独移动 bat。
  set OK=0
)

if "%OK%"=="0" (
  echo.
  echo 先按上面提示处理，再双击 QuestAwayHelper.exe。
  pause
  exit /b 1
)
echo [OK] 自检通过，正在启动...
echo.

if exist "helper_error.log" ren "helper_error.log" "helper_error.prev.log" >nul 2>nul
start "" "QuestAwayHelper.exe"
ping -n 6 127.0.0.1 >nul

tasklist /FI "IMAGENAME eq QuestAwayHelper.exe" 2>nul | find /i "QuestAwayHelper.exe" >nul
if errorlevel 1 (
  echo [X] 程序启动后立刻退出了。
  if exist "helper_error.log" (
    echo ---- helper_error.log 内容 ----
    type "helper_error.log"
    echo ------------------------------
  ) else (
    echo 没有生成 helper_error.log，说明在加载 Python 之前就被终止了，常见三种原因：
    echo   1. 系统低于 Windows 10，或被人精简过（比如某些 GHOST 版）
    echo   2. 杀软/安全卫士拦截，把整个文件夹加白名单后重试
    echo   3. 没完整解压，_internal 文件夹不在 exe 旁边
  )
  echo.
  echo 还不行就运行 QuestAwayHelper_debug.exe，把黑窗口内容截图给作者。
  pause
  exit /b 1
)
echo [OK] 已启动。若没看到窗口，检查任务栏。
ping -n 3 127.0.0.1 >nul
