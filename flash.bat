@echo off
setlocal
cd /d "%~dp0"

:menu
echo.
echo ============================================================
echo   Plai firmware - build ^& flash
echo ============================================================
echo.
echo   How would you like to run flash.ps1?
echo.
echo     [1] Full flash            (default; prompts before NVS wipe)
echo     [2] App-only flash        (-AppOnly; keeps your mesh keys)
echo     [3] App-only + monitor    (-AppOnly -Monitor)
echo     [4] Build only, no flash  (-NoFlash)
echo     [5] Regenerate protobufs  (-Regen)
echo     [6] Full flash + monitor  (-Yes -Monitor)
echo     [H] Show flash.ps1 help   (-Help)
echo     [C] Custom arguments...
echo     [Q] Quit
echo.

set "ARGS="
set "CHOICE="
set /p "CHOICE=Selection [1]: "
if not defined CHOICE set "CHOICE=1"

if /i "%CHOICE%"=="1" goto run
if /i "%CHOICE%"=="2" ( set "ARGS=-AppOnly"          & goto run )
if /i "%CHOICE%"=="3" ( set "ARGS=-AppOnly -Monitor" & goto run )
if /i "%CHOICE%"=="4" ( set "ARGS=-NoFlash"          & goto run )
if /i "%CHOICE%"=="5" ( set "ARGS=-Regen"            & goto run )
if /i "%CHOICE%"=="6" ( set "ARGS=-Yes -Monitor"     & goto run )
if /i "%CHOICE%"=="H" ( set "ARGS=-Help"             & goto run )
if /i "%CHOICE%"=="C" goto custom
if /i "%CHOICE%"=="Q" goto end

echo.
echo   "%CHOICE%" is not a valid selection.
goto menu

:custom
echo.
echo   Type any flash.ps1 arguments. Examples:
echo     -Port COM4            -AppOnly -Monitor            -Regen -NoFlash
echo   (Pick [H] from the menu to see the full option list.)
echo.
set "ARGS="
set /p "ARGS=Arguments: "

:run
echo.
echo   Running: flash.ps1 %ARGS%
echo.
Powershell.exe -ExecutionPolicy Bypass -File "%~dp0flash.ps1" %ARGS%

echo.
pause

:end
endlocal
