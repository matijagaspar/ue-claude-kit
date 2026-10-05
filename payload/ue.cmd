@echo off
rem ue-claude-kit launcher: finds a Python 3 and runs the kit CLI. See .claude\skills\unreal-editor\SKILL.md
setlocal
set "UEKIT=%~dp0.claude\skills\unreal-editor\scripts\ue.py"
set "UE_PYARGS="
if defined UE_PYTHON goto run
for /f "tokens=1,* delims= " %%A in ('findstr /b /c:"python_exe: " "%~dp0ue_local_config.local" 2^>nul') do set "UE_PYTHON=%%~B"
if defined UE_PYTHON if exist "%UE_PYTHON%" goto run
set "UE_PYTHON="
py -3 -c "import sys" >nul 2>&1 && (set "UE_PYTHON=py" & set "UE_PYARGS=-3" & goto run)
python -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>&1 && (set "UE_PYTHON=python" & goto run)
rem Fall back to the Python that ships with Unreal (Epic launcher installs).
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "try { (Get-Content \"$env:ProgramData\Epic\UnrealEngineLauncher\LauncherInstalled.dat\" -Raw | ConvertFrom-Json).InstallationList | Where-Object AppName -like 'UE_*' | ForEach-Object { Join-Path $_.InstallLocation 'Engine\Binaries\ThirdParty\Python3\Win64\python.exe' } | Where-Object { Test-Path $_ } | Select-Object -Last 1 } catch {}"`) do set "UE_PYTHON=%%P"
if defined UE_PYTHON goto run
echo ue: no Python 3 found. Install Python 3.8+ or set UE_PYTHON to a python.exe (Unreal ships one in Engine\Binaries\ThirdParty\Python3\Win64). 1>&2
exit /b 1
:run
"%UE_PYTHON%" %UE_PYARGS% "%UEKIT%" %*
exit /b %ERRORLEVEL%
