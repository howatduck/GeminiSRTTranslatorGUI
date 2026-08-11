# Windows 10+ PowerShell 빌드 스크립트
$ErrorActionPreference = "Stop"

Write-Host "===================================================" -ForegroundColor Cyan
Write-Host " Gemini SRT Translator GUI - Windows Build Script" -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[오류] Python이 설치되어 있지 않거나 PATH에 포함되어 있지 않습니다." -ForegroundColor Red
    Write-Host "https://www.python.org 에서 Python 3.10 이상 설치 후 다시 시도하세요." -ForegroundColor Yellow
    Exit 1
}

Write-Host "[1/4] 가상환경(venv) 생성 및 활성화..." -ForegroundColor Green
if (-not (Test-Path "venv")) {
    python -m venv venv
}

& "venv\Scripts\Activate.ps1"

Write-Host "[2/4] 필요 패키지 설치 중..." -ForegroundColor Green
python -m pip install --upgrade pip
pip install -r requirements.txt

Write-Host "[3/4] PyInstaller 실행파일 빌드 중..." -ForegroundColor Green
pyinstaller --clean --noconfirm GeminiSRTTranslator.spec

if (Test-Path "dist\GeminiSRTTranslator.exe") {
    Write-Host ""
    Write-Host "===================================================" -ForegroundColor Green
    Write-Host " [성공] Windows 실행 파일 빌드가 완료되었습니다!" -ForegroundColor Green
    Write-Host " 실행 파일 위치: dist\GeminiSRTTranslator.exe" -ForegroundColor Yellow
    Write-Host "===================================================" -ForegroundColor Green
} else {
    Write-Host "[오류] 빌드에 실패했습니다." -ForegroundColor Red
}
