@echo off
chcp 65001 >nul
echo ===================================================
echo  Gemini SRT Translator GUI - Windows 10+ Build
echo ===================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [오류] Python이 설치되어 있지 않거나 PATH에 추가되어 있지 않습니다.
    echo https://www.python.org 에서 Python 3.10 이상을 설치할 때 'Add python.exe to PATH'를 체크하세요.
    echo.
    pause
    exit /b 1
)

echo [1/4] 가상환경(venv) 생성 및 활성화...
if not exist "venv" (
    python -m venv venv
)
call venv\Scripts\activate.bat

echo.
echo [2/4] 필요 라이브러리 설치 중...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo [3/4] PyInstaller로 Windows 실행파일(.exe) 빌드 중...
pyinstaller --clean --noconfirm GeminiSRTTranslator.spec

echo.
if exist "dist\GeminiSRTTranslator.exe" (
    echo ===================================================
    echo  [성공] Windows 실행 파일 빌드가 완료되었습니다!
    echo  실행 파일 위치: dist\GeminiSRTTranslator.exe
    echo ===================================================
) else (
    echo [오류] 빌드에 실패했습니다. 위의 메시지를 확인해 주세요.
)

echo.
pause
