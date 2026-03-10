@echo off
setlocal

REM Папка, где лежит этот .bat (farm_guardian)
set "ROOT=%~dp0"
REM убираем завершающий обратный слэш, если есть
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "PY=%ROOT%\venv\Scripts\python.exe"
set "SCRIPT=%ROOT%\weather_collector.py"

echo ROOT   = "%ROOT%"
echo PY     = "%PY%"
echo SCRIPT = "%SCRIPT%"
echo.

if not exist "%PY%" (
  echo ERROR: python.exe not found
  pause
  exit /b 1
)

if not exist "%SCRIPT%" (
  echo ERROR: weather_collector.py not found
  pause
  exit /b 1
)

echo OK: paths exist. Starting loop...
echo.

:loop
"%PY%" "%SCRIPT%"
timeout /t 3600 /nobreak >nul
goto loop
