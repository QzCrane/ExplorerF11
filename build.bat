@echo off
rem Build ExplorerF11. Produces dist\ExplorerF11.exe.
rem
rem   build.bat            release build, whichever compiler is on PATH
rem   build.bat debug      symbols, console window for stderr
rem   build.bat msvc       release build, cl.exe only (CI uses this)
rem   build.bat mingw      release build, g++ only
rem
rem Uses MSVC if it is on PATH, otherwise MinGW-w64 g++. Both produce a single
rem self-contained exe with no runtime dependency. CI calls this script rather
rem than repeating the compiler command line, so the flags proved on every push
rem are the flags this file documents - there is no second copy to drift.
setlocal enabledelayedexpansion
cd /d "%~dp0"

set MODE=%1
set FORCE=auto
if /i "%MODE%"=="msvc" (set FORCE=msvc & set MODE=release)
if /i "%MODE%"=="mingw" (set FORCE=mingw & set MODE=release)
if "%MODE%"=="" set MODE=release

if not exist dist mkdir dist

if /i "%FORCE%"=="msvc" goto msvc
if /i "%FORCE%"=="mingw" goto mingw

where g++ >nul 2>&1
if not errorlevel 1 goto mingw
where cl >nul 2>&1
if not errorlevel 1 goto msvc

echo [ERROR] No C++ compiler found.
echo         Install MinGW-w64 (e.g. w64devkit) and add its bin to PATH,
echo         or run this from a "Developer Command Prompt for VS".
exit /b 1

:mingw
echo [build] MinGW-w64 g++ (%MODE%)
set SRC=src\main.cpp src\config.cpp src\residue.cpp src\i18n_extra.cpp src\app.rc
if /i "%MODE%"=="debug" (
    g++ -std=c++23 -O0 -g -municode -Wall -Wextra %SRC% -o dist\ExplorerF11.exe ^
        -luser32 -lshell32 -ladvapi32
) else (
    g++ -std=c++23 -Os -s -mwindows -municode -Wall -Wextra ^
        -static -static-libgcc -static-libstdc++ %SRC% -o dist\ExplorerF11.exe ^
        -luser32 -lshell32 -ladvapi32
)
if errorlevel 1 exit /b 1
goto done

:msvc
echo [build] MSVC cl (%MODE%)
rem cl does not compile .rc files the way g++ does: rc.exe builds the resource
rem object first, then the linker takes it as one more input. Skip this step and
rem the exe ends up with no icon and no version block.
rc /nologo /I src /fo dist\app.res src\app.rc
if errorlevel 1 exit /b 1
rem /utf-8 is mandatory, not cosmetic: the sources are UTF-8 without a BOM and
rem carry CJK wide literals. Without it cl decodes them with the system ANSI
rem code page, so a Japanese string compiles correctly only on a Japanese
rem machine and turns to mojibake everywhere else.
if /i "%MODE%"=="debug" (
    cl /nologo /std:c++latest /utf-8 /EHsc /W4 /Zi /Od /D_DEBUG ^
       src\main.cpp src\config.cpp src\residue.cpp src\i18n_extra.cpp dist\app.res ^
       /Fo:dist\ /Fe:dist\ExplorerF11.exe /link /SUBSYSTEM:CONSOLE
) else (
    cl /nologo /std:c++latest /utf-8 /EHsc /W4 /O2 /GL /DNDEBUG ^
       src\main.cpp src\config.cpp src\residue.cpp src\i18n_extra.cpp dist\app.res ^
       /Fo:dist\ /Fe:dist\ExplorerF11.exe /link /SUBSYSTEM:WINDOWS /LTCG
)
if errorlevel 1 exit /b 1

:done
echo.
echo [build] dist\ExplorerF11.exe
for %%F in (dist\ExplorerF11.exe) do echo         %%~zF bytes
dist\ExplorerF11.exe --version
endlocal
