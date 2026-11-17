@echo off
setlocal EnableExtensions

rem Builds the Windows program mfi-wifi-setup as one .exe (PyInstaller, --onefile).
rem Run by a person on Windows, from this folder: double-click or run from cmd.
rem Output: dist\mfi-wifi-setup-VERSION-windows-x64.exe and the .sha256 file next to it.
rem No administrator rights, no change to the system; the temporary venv is removed at the end.

set "BUILD_DIR=%TEMP%\mfi-wifi-setup-build"
set "VENV_DIR=%BUILD_DIR%\venv"
set "VERSION_FILE=%BUILD_DIR%\version.txt"
set "HASH_FILE=%BUILD_DIR%\hash.txt"

where python >nul 2>&1
if errorlevel 1 (
    echo Python 3.12 or newer is required: https://www.python.org/downloads/
    exit /b 1
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"
if errorlevel 1 (
    echo Python 3.12 or newer is required: https://www.python.org/downloads/
    exit /b 1
)

rem Remove leftovers from an interrupted previous build.
rmdir /s /q "%BUILD_DIR%" 2>nul

python -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo Could not create the build environment in "%VENV_DIR%".
    goto :fail
)

"%VENV_DIR%\Scripts\python.exe" -m pip install -r "%~dp0requirements-build.txt"
if errorlevel 1 (
    echo Could not install the build requirements from requirements-build.txt.
    goto :fail
)

rem r'%~dp0.' ends with a dot: a raw string cannot end with a backslash
python -c "import sys; sys.path.insert(0, r'%~dp0.'); import mfi_wifi_setup; print(mfi_wifi_setup.__version__)" > "%VERSION_FILE%"
if errorlevel 1 (
    echo Could not read the version of mfi_wifi_setup.
    goto :fail
)
set /p APP_VERSION=<"%VERSION_FILE%"
if not defined APP_VERSION (
    echo The version of mfi_wifi_setup is empty.
    goto :fail
)

set "EXE_NAME=mfi-wifi-setup-%APP_VERSION%-windows-x64"
set "EXE=%~dp0dist\%EXE_NAME%.exe"

rem Remove any .exe (and its hash) left by a previous, possibly failed, build.
del /q "%EXE%" "%EXE%.sha256" 2>nul

rem PyInstaller runs the entry script as the top-level __main__ with no parent
rem package, so the package module with relative imports cannot be the entry.
rem Write a tiny launcher with absolute imports; --paths lets PyInstaller find
rem the mfi_wifi_setup package next to this script.
set "ENTRY=%BUILD_DIR%\entry.py"
> "%ENTRY%" echo from mfi_wifi_setup.window import run
>> "%ENTRY%" echo run()

"%VENV_DIR%\Scripts\pyinstaller.exe" --onefile --windowed --name "%EXE_NAME%" --distpath "%~dp0dist" --workpath "%BUILD_DIR%\work" --specpath "%BUILD_DIR%" --paths "%~dp0." "%ENTRY%"
if errorlevel 1 (
    echo PyInstaller failed: see the messages above.
    goto :fail
)

certutil -hashfile "%EXE%" SHA256 > "%HASH_FILE%"
if errorlevel 1 (
    echo Could not compute the sha256 of "%EXE%".
    goto :fail
)
rem certutil's second output line is the hash itself, in any Windows UI language.
set "APP_HASH="
for /f "skip=1 tokens=*" %%h in ('type "%HASH_FILE%"') do if not defined APP_HASH set "APP_HASH=%%h"
if not defined APP_HASH (
    echo Could not read the sha256 of "%EXE%".
    goto :fail
)
> "%EXE%.sha256" echo %APP_HASH% *%EXE_NAME%.exe

rmdir /s /q "%BUILD_DIR%"
if exist "%BUILD_DIR%" (
    echo Could not remove the temporary folder "%BUILD_DIR%".
    exit /b 1
)

echo Built "%EXE%"
type "%EXE%.sha256"
exit /b 0

:fail
rmdir /s /q "%BUILD_DIR%" 2>nul
exit /b 1
