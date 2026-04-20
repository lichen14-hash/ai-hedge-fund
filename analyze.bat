@echo off

REM === Set UTF-8 for Python output only ===
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

title AI Stock Analyzer

echo ========================================
echo     AI Hedge Fund - Stock Analyzer
echo ========================================
echo.

REM Get ticker from command line argument
if "%~1"=="" (
    echo Usage: analyze.bat ^<TICKER^>
    echo Examples: analyze.bat 600519.SH
    echo           analyze.bat 0700.HK
    echo           analyze.bat 002602.SZ
    echo.
    pause
    exit /b 1
)
set "TICKER=%~1"

REM Generate timestamp YYYYMMDD_HHMM (compatible with Windows 25H2)
for /f %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmm"') do set "TIMESTAMP=%%a"

REM Create reports directory
if not exist reports mkdir reports

REM Set output filename
set "OUTPUT_FILE=reports\report_%TICKER%_%TIMESTAMP%.md"

echo.
echo ========================================
echo  Analyzing: %TICKER%
echo  Model: GLM-4 Plus ^| Analysts: All 19
echo  Output: %OUTPUT_FILE%
echo ========================================
echo.

REM Check if poetry is available and run analysis
where poetry >nul 2>&1
if %errorlevel% == 0 (
    set "POETRY_CMD=poetry"
) else (
    set "POETRY_CMD=python -m poetry"
)

REM Run analysis with real-time output to CMD and save structured report
REM The --report flag tells Python to generate the markdown report directly
call %POETRY_CMD% run python src/main.py --tickers %TICKER% --model glm-4-plus --analysts-all --show-reasoning --report "%OUTPUT_FILE%" 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath 'temp_output.txt'"

REM Clean up temp file
if exist temp_output.txt (
    del temp_output.txt
)

echo.
echo ========================================
echo  Analysis complete.
echo  Report saved to: %OUTPUT_FILE%
echo ========================================
echo.
pause
