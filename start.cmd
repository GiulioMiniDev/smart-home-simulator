@echo off
setlocal
set "PROJECT_DIRECTORY=%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%PROJECT_DIRECTORY%tools\start_smart_home_simulator.py" %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python "%PROJECT_DIRECTORY%tools\start_smart_home_simulator.py" %*
  exit /b %ERRORLEVEL%
)

echo ERRORE: Python 3 non trovato. Installa Python 3 e riprova. 1>&2
exit /b 1
