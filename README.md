# Gemini SRT Translator GUI

> 🇰🇷 한국어 / 🇺🇸 English — *scroll down for English*

---

## 🇰🇷 한국어

PyQt6 기반 GUI 애플리케이션으로, [gemini-srt-translator](https://github.com/MaKTaiL/gemini-srt-translator) 라이브러리(v3.8.3)를 활용하여 자막(SRT/ASS) 번역과 비디오/오디오 전사(Transcribe)를 손쉽게 수행할 수 있습니다. Pyte 기반 VT100 터미널 에뮬레이터를 내장하여 콘솔 출력(색상, 진행률 등)을 GUI 안에서 그대로 확인할 수 있습니다.

### 주요 기능

- **자막 번역 (Translate)**: SRT/ASS 자막 파일을 원하는 언어로 번역
- **비디오/오디오 전사 (Transcribe)**: 비디오·오디오 파일에서 자막을 새로 생성
- **다중 언어 동시 처리**: 체크박스 콤보박스로 여러 대상 언어를 한 번에 선택해 일괄 작업
- **다중 API 키 로테이션**: 최대 10개의 Gemini API 키를 등록해 무료 할당량을 순환 사용
- **다중 파일 큐 처리**: 자막/비디오 파일을 여러 개 선택하면 순차적으로 처리
- **실시간 VT100 터미널 뷰**: 라이브러리의 콘솔 출력(색상 포함)을 앱 내에서 실시간 렌더링
- **세부 튜닝 옵션**: temperature, top_p, top_k, 사고(thinking) 예산/수준, 배치 크기, 서비스 티어 등
- **문맥 연속성 관리 (context_size)**: 번역 중 이전 자막 라인을 참조하는 슬라이딩 컨텍스트 크기 설정
- **중단된 작업 이어하기 (resume, v3.8.3)**: 이전에 중단된 번역/전사 작업을 저장된 진행 상태부터 자동으로 이어서 수행. 체크 해제 시 처음부터 새로 시작
- **번역 스타일 프리셋**: 자연스러운 구어체, 드라마·영화 자막체, 다큐 내레이션체, 애니 더빙체, 어학용 직역, 예능·유튜브체, 어린이용 등 7종 프리셋. 선택한 스타일 지침이 번역 프롬프트에 자동 합성됨
- **번역 결과 미리보기/편집**: 번역 완료 후 원문과 대조하며 번역문을 행 단위로 수정·저장. CPS(초당 글자수) 경고 표시, 검색, 저장 시 `.bak` 자동 백업
- **적응형 배치/오디오 자동 감축 (v3.8.3)**: API 오류(429/500/503) 또는 파싱 오류 발생 시 배치 크기(`batch_size_error_step`)와 오디오 청크(`audio_chunk_error_step`)를 자동으로 줄여 복구 후 원래 크기로 복원
- **Google Cloud / Vertex AI(Enterprise) 연동**: Cloud Project, API Key, Region, Request Type 설정 지원
- **자동 재시도/백오프**: 연속 실패 시 지수 백오프로 대기하고, 임계치 초과 시 안전하게 작업 중단
- **원자적 파일 저장**: 자막 저장 시 임시 파일 기록 후 `os.replace()` 교체 방식으로 파일 손상 방지
- **설정 자동 저장/복원**: `QSettings` 기반으로 API 키, 옵션, 파일 경로 등을 재실행 시 자동 로드
- **UI 언어 전환**: 한국어 / English 실시간 전환 지원

### 요구 사항

- Windows 10 이상 (64-bit) 또는 Linux/macOS
- Google 계정 (Gemini API 키 발급용, 무료)
- Python 3.10 이상 (소스 코드 실행 시)
- FFmpeg (비디오/오디오 전사·음성 추출 기능 사용 시 필수)

### 🚀 설치 가이드

#### 1단계: Google AI Studio 가입 및 API 키 발급 (필수)

이 앱은 Google Gemini API로 번역/전사를 수행하므로 API 키가 반드시 필요합니다. 무료로 발급받을 수 있습니다.

1. [Google AI Studio](https://aistudio.google.com)에 접속해 Google 계정으로 로그인합니다.
2. **"Get API key"** (API 키 받기)를 클릭합니다.
3. **"Create API key"** → 새 Google Cloud 프로젝트를 만들거나 기존 프로젝트를 선택합니다.
4. 발급된 API 키를 복사합니다.
5. 앱 실행 후 **"API 키 관리..."** 버튼을 눌러 복사한 키를 붙여넣고 저장합니다.

> 💡 **무료 할당량 극대화 팁**: Gemini API는 무료 티어를 제공합니다. Google 계정당 여러 프로젝트에서 키를 발급받아 앱에 최대 10개까지 등록하면, 작업(job)마다 키를 자동으로 돌려가며 사용하므로 무료 한도를 최대한 활용할 수 있습니다.
> ⚠️ **보안 주의**: API 키는 비밀번호처럼 다루세요. 다른 사람에게 공유하거나 공개 저장소에 올리지 마세요.

#### 2단계: FFmpeg 설치 (비디오/오디오 기능 사용 시 필수)

비디오 파일에서 자막을 추출하거나 오디오 전사를 하려면 FFmpeg가 필요합니다. 자막 파일(SRT/ASS) 번역만 한다면 생략해도 됩니다.

- **Windows**: `winget install Gyan.FFmpeg` 또는 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)에서 빌드를 받아 PATH에 추가
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

설치 확인:
```bash
ffmpeg -version
```

#### 3단계: 앱 설치 — 원하는 방식 선택

**A. 실행 파일 다운로드 (Windows, 가장 쉬움)**
GitHub Release에서 `GeminiSRTTranslator-Windows.zip`을 받아 압축을 풀고 바로 실행합니다. Python 설치가 필요 없습니다.

**B. 소스 코드 직접 실행**
```bash
# Python 3.10 이상 확인
python --version

# 가상환경 사용 권장
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
python main.py
```

**C. 실행 파일(.exe) 직접 빌드 (Windows)**
1. 원클릭 자동 빌드 (추천): 프로젝트 폴더에서 `build_win.bat` (또는 `build_win.ps1`) 실행 — 패키지 설치부터 빌드까지 자동 진행
2. 수동 빌드:
```cmd
pip install -r requirements.txt
pyinstaller --clean --noconfirm GeminiSRTTranslator.spec
```
빌드 결과: `dist\GeminiSRTTranslator.exe`

### 🔧 문제 해결

| 증상 | 해결 방법 |
|---|---|
| `ffmpeg`을(를) 찾을 수 없다는 오류 | 2단계 FFmpeg 설치 후 터미널을 다시 열거나 PC 재부팅 (PATH 반영) |
| API 키 오류 / 400 에러 | AI Studio에서 키를 재발급받아 "API 키 관리"에서 교체 |
| 무료 할당량 초과 (429) | API 키를 추가로 등록하거나 잠시 후 재시도. 키가 여러 개면 자동 순환됨 |
| 모델 목록이 비어 있음 | "모델 가져오기" 버튼 클릭, API 키가 올바르게 등록됐는지 확인 |
| PyQt6 설치 실패 | `pip install --upgrade pip` 후 재시도 |

### 프로젝트 구조

```
GeminiSRTTranslatorGUI/
├── main.py                 # 얇은 진입점
├── requirements.txt        # 실행용 의존성
├── requirements-dev.txt    # 개발용 의존성
├── build_win.bat / .ps1    # Windows 빌드 스크립트
├── GeminiSRTTranslator.spec# PyInstaller 스펙
├── README.md               # 이 문서
├── core/                   # 순수 로직
│   ├── safety.py         # 프로세스 안전 패치
│   ├── config.py         # 앱 상수
│   ├── languages.py      # 언어 정규화·ISO 코드
│   ├── media.py          # FFmpeg 미디어 헬퍼
│   ├── gst_compat.py     # 라이브러리 호환 레이어
│   ├── errors.py         # 워커 오류 분류
│   ├── style_presets.py  # 스타일 프리셋 정의
│   └── subtitle_io.py    # SRT 입출력·CPS 계산
├── app/                    # PyQt6 GUI
│   ├── main_window.py    # 메인 윈도우
│   ├── preview_editor.py # 결과 미리보기/편집
│   ├── widgets.py        # 공용 위젯
│   ├── workers.py        # 번역 워커 스레드
│   └── i18n.py           # 한/영 UI 문자열
└── tests/                  # pytest 테스트 스위트
```

### 사용 방법 요약

1. **API 키 설정**: "API 키 관리..." 버튼을 눌러 최소 1개 이상의 Gemini API 키를 입력하고 저장합니다.
2. **작업 모드 선택**: 자막 번역 또는 비디오/오디오 전사 중 선택합니다.
3. **입력 파일 지정**:
   - 번역: SRT/ASS 파일 선택
   - 전사: 비디오 또는 오디오 파일 선택
4. **출력 폴더 지정**
5. **대상 언어 선택**: 다중 선택 콤보박스에서 원하는 언어를 체크
6. (선택) **기본 설정 / 고급 설정**에서 모델, 배치 크기, temperature, 문맥 크기, 적응형 감축 단위 등 세부 옵션 조정
7. **🚀 작업 시작** 클릭 → 하단 터미널 창에서 실시간 진행 상황 확인
8. 필요 시 **🛑 작업 중단**으로 안전하게 중지 가능 (진행 중인 배치 완료 후 종료)

### 고급 설정 (⚙ 고급 설정 및 튜닝)

| 옵션 | 설명 |
|------|------|
| 서비스 티어 | Default / standard / flex / priority 선택 |
| 시작 라인 | 번역을 시작할 자막 라인 번호 |
| Temperature / Top-P / Top-K | 생성 파라미터 조정 |
| 사고 예산 / 수준 | Thinking 기능 예산 및 수준 설정 |
| 오디오청크 | 오디오 컨텍스트 번역 청크 크기(초) |
| Context Size | 슬라이딩 컨텍스트 참조 라인 수 (0 = 비활성) |
| 작업 이어하기 | 중단된 작업의 저장된 진행 상태부터 자동 재개 (기본값: 켜짐) |
| 배치 축소단위 | 오류 발생 시 배치 크기 자동 감축 단계 (기본: 100) |
| 오디오 축소단위 | 오류 발생 시 오디오 청크 자동 감축 단계 (기본: 60) |

### 폴더/설정 저장 위치

설정은 `QSettings(SETTINGS_ORG="GeminiSrtTranslatorGUI", SETTINGS_APP="GeminiSrtTranslatorGUI")`를 통해 OS 표준 위치(Windows 레지스트리)에 저장됩니다.

### 주의 사항

- API 키는 기본적으로 가려서(마스크) 표시됩니다. "API 키 표시" 체크박스로 보였다/가렸다 전환할 수 있습니다.
- Enterprise(Vertex AI) 모드 사용 시 별도의 Google Cloud Project / 인증 정보가 필요합니다.
- 이 GUI는 [gemini-srt-translator](https://pypi.org/project/gemini-srt-translator/) 라이브러리 **v3.8.3** 인터페이스 기반으로 작성되었습니다.
- 라이브러리 버전이 다르면 일부 옵션이 동작하지 않을 수 있습니다.

---

## 🇺🇸 English

A PyQt6-based GUI application that leverages the [gemini-srt-translator](https://github.com/MaKTaiL/gemini-srt-translator) library (v3.8.3) to easily translate subtitles (SRT/ASS) and transcribe video/audio files. It includes a built-in Pyte VT100 terminal emulator so you can view real-time console output (including colors and progress bars) directly within the GUI.

### Key Features

- **Subtitle Translation**: Translate SRT/ASS subtitle files into any desired language
- **Video/Audio Transcription**: Generate new subtitles directly from video or audio files
- **Multi-language Batch Processing**: Select multiple target languages at once via a checkable combo box
- **Multi API Key Rotation**: Register up to 10 Gemini API keys and rotate them to maximize free quota
- **Multi-file Queue**: Select multiple subtitle/video files and process them sequentially
- **Real-time VT100 Terminal**: Renders library console output (with ANSI colors) live inside the app
- **Fine-tuning Options**: temperature, top_p, top_k, thinking budget/level, batch size, service tier, etc.
- **Context Management (context_size)**: Configure sliding context window size for improved translation continuity
- **Resume Interrupted Jobs (v3.8.3)**: Automatically continue translation/transcription from saved progress. Uncheck to start fresh from the beginning
- **Translation Style Presets**: 7 presets — natural colloquial, drama & film subtitles, documentary narration, anime dubbing, literal (for language study), variety/YouTube style, and for kids. The selected style instruction is automatically merged into the translation prompt
- **Result Preview & Editor**: After translation, review and edit translated lines side-by-side with the original. Includes CPS (chars/sec) warnings, search, and automatic `.bak` backup on save
- **Adaptive Batch & Audio Chunk Sizing (v3.8.3)**: Automatically reduces `batch_size` and `audio_chunk_size` on API errors (429/500/503) or parse failures, then restores original values on success
- **Google Cloud / Vertex AI (Enterprise)**: Supports Cloud Project, API Key, Region, and Request Type configuration
- **Auto Retry / Backoff**: Exponential backoff on consecutive failures; safely aborts when threshold is exceeded
- **Atomic File Save**: Subtitles are written atomically via temp file + `os.replace()` to prevent corruption
- **Auto Save / Restore Settings**: API keys, options, and file paths are persisted and restored via `QSettings`
- **UI Language Toggle**: Switch between Korean (한국어) and English at runtime

### Requirements

- Windows 10 or later (64-bit), or Linux/macOS
- Google account (for a free Gemini API key)
- Python 3.10 or later (for running from source)
- FFmpeg (required for video/audio transcription and audio extraction)

### 🚀 Installation Guide

#### Step 1: Sign up for Google AI Studio and get an API key (required)

This app performs translation/transcription via the Google Gemini API, so an API key is required. It's free.

1. Go to [Google AI Studio](https://aistudio.google.com) and sign in with your Google account.
2. Click **"Get API key"**.
3. Click **"Create API key"** → create a new Google Cloud project or select an existing one.
4. Copy the issued API key.
5. In the app, click **"Manage API Keys..."**, paste the key, and save.

> 💡 **Maximize the free quota**: The Gemini API offers a free tier. Issue keys from multiple projects under your Google account and register up to 10 in the app — keys are rotated automatically per job, maximizing your free usage.
> ⚠️ **Security**: Treat your API key like a password. Never share it or commit it to a public repository.

#### Step 2: Install FFmpeg (required for video/audio features)

FFmpeg is required to extract subtitles from video files or transcribe audio. Skip this if you only translate subtitle files (SRT/ASS).

- **Windows**: `winget install Gyan.FFmpeg`, or download a build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) and add it to PATH
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

Verify:
```bash
ffmpeg -version
```

#### Step 3: Install the app — pick your method

**A. Download the executable (Windows, easiest)**
Download `GeminiSRTTranslator-Windows.zip` from the latest GitHub Release, extract, and run. No Python installation needed.

**B. Run from source**
```bash
# Check Python 3.10+
python --version

# Virtual environment recommended
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
python main.py
```

**C. Build the executable (.exe) yourself (Windows)**
1. One-click auto build (recommended): run `build_win.bat` (or `build_win.ps1`) in the project folder — installs packages and builds automatically
2. Manual build:
```cmd
pip install -r requirements.txt
pyinstaller --clean --noconfirm GeminiSRTTranslator.spec
```
Output: `dist\GeminiSRTTranslator.exe`

### 🔧 Troubleshooting

| Symptom | Fix |
|---|---|
| `ffmpeg` not found error | Install FFmpeg (Step 2), then reopen the terminal or reboot (to refresh PATH) |
| API key error / 400 | Reissue the key in AI Studio and replace it under "Manage API Keys" |
| Free quota exceeded (429) | Register additional API keys or wait and retry; multiple keys rotate automatically |
| Empty model list | Click "Fetch Models" and verify the API key is registered correctly |
| PyQt6 install failure | `pip install --upgrade pip`, then retry |

### Project Structure

```
GeminiSRTTranslatorGUI/
├── main.py                 # Thin entry point
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Dev dependencies
├── build_win.bat / .ps1    # Windows build scripts
├── GeminiSRTTranslator.spec# PyInstaller build spec
├── README.md               # This document
├── core/                   # Pure logic
│   ├── safety.py         # Process-safety patches
│   ├── config.py         # App constants
│   ├── languages.py      # Language normalization
│   ├── media.py          # FFmpeg media helpers
│   ├── gst_compat.py     # Library compat layer
│   ├── errors.py         # Worker error classification
│   ├── style_presets.py  # Style preset definitions
│   └── subtitle_io.py    # SRT I/O and CPS calc
├── app/                    # PyQt6 GUI
│   ├── main_window.py    # Main window
│   ├── preview_editor.py # Result preview/edit dialog
│   ├── widgets.py        # Shared widgets
│   ├── workers.py        # Translation worker threads
│   └── i18n.py           # KO/EN UI strings
└── tests/                  # pytest test suite
```

### Quick Usage Guide

1. **Set API Keys**: Click "Manage API Keys..." and enter at least one Gemini API key.
2. **Select Task Mode**: Choose between subtitle translation or video/audio transcription.
3. **Select Input Files**:
   - Translation: choose SRT/ASS files
   - Transcription: choose a video or audio file
4. **Select Output Folder**
5. **Choose Target Languages**: Check the desired languages in the multi-select combo box.
6. *(Optional)* Adjust model, batch size, temperature, context size, and adaptive reduction steps under **Basic / Advanced Settings**.
7. Click **🚀 Start Task** — watch real-time progress in the terminal panel below.
8. Click **🛑 Stop Task** to safely interrupt (the current batch completes before stopping).

### Advanced Settings (⚙ Advanced Settings & Tuning)

| Option | Description |
|--------|-------------|
| Service Tier | Select Default / standard / flex / priority |
| Start Line | Subtitle line number to begin translation from |
| Temperature / Top-P / Top-K | Generation parameter tuning |
| Thinking Budget / Level | Configure thinking feature budget and level |
| Audio Chunk | Audio context translation chunk size (seconds) |
| Context Size | Sliding context reference line count (0 = disabled) |
| Resume | Auto-resume interrupted jobs from saved progress (default: on) |
| Batch Error Step | Auto-reduction step for batch size on errors (default: 100) |
| Audio Error Step | Auto-reduction step for audio chunk on errors (default: 60) |

### Settings Storage Location

Settings are stored via `QSettings(SETTINGS_ORG="GeminiSrtTranslatorGUI", SETTINGS_APP="GeminiSrtTranslatorGUI")` in the OS standard location (Windows Registry on Windows).

### Notes

- API keys are masked by default. Use the "Show API keys" checkbox to toggle visibility.
- Enterprise (Vertex AI) mode requires a separate Google Cloud Project and authentication credentials.
- This GUI targets the **v3.8.3** interface of the [gemini-srt-translator](https://pypi.org/project/gemini-srt-translator/) library. Some options may not work with different library versions.
