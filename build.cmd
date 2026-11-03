@echo off
rem Compiles dist\statpearls-vault.exe from this folder. Python 3.12+ is needed on this computer only for compiling.
setlocal
cd /d "%~dp0"
if not exist .build-venv\Scripts\python.exe (
  python -m venv .build-venv || goto :fail
)
.build-venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r build-requirements.txt || goto :fail
.build-venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath dist --workpath .build statpearls-vault.spec || goto :fail
echo.
echo Built %~dp0dist\statpearls-vault.exe
exit /b 0
:fail
echo.
echo The build failed; the messages above say why.
exit /b 1
