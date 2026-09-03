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
- **적응형 배치/오디오 자동 감축 (v3.8.3)**: API 오류(429/500/503) 또는 파싱 오류 발생 시 배치 크기(`batch_size_error_step`)와 오디오 청크(`audio_chunk_error_step`)를 자동으로 줄여 복구 후 원래 크기로 복원
- **Google Cloud / Vertex AI(Enterprise) 연동**: Cloud Project, API Key, Region, Request Type 설정 지원
- **자동 재시도/백오프**: 연속 실패 시 지수 백오프로 대기하고, 임계치 초과 시 안전하게 작업 중단
- **원자적 파일 저장**: 자막 저장 시 임시 파일 기록 후 `os.replace()` 교체 방식으로 파일 손상 방지
- **설정 자동 저장/복원**: `QSettings` 기반으로 API 키, 옵션, 파일 경로 등을 재실행 시 자동 로드
- **UI 언어 전환**: 한국어 / English 실시간 전환 지원

### 요구 사항

- Windows 10 이상 (64-bit) 또는 Linux/macOS
- Python 3.10 이상 (소스 코드 실행 시)

### 📦 Windows 10+ 실행파일(.exe) 빌드 방법

#### 1. 원클릭 자동 빌드 (추천)
Windows 환경에서 프로젝트 폴더를 열고 `build_win.bat` 파일 또는 `build_win.ps1`을 실행하면 필요 패키지 설치부터 `.exe` 빌드까지 자동으로 진행됩니다.

```cmd
build_win.bat
```

빌드가 완료되면 `dist\GeminiSRTTranslator.exe` 단일 실행 파일이 생성됩니다.

#### 2. 수동 빌드 (Command Prompt / PowerShell)
```cmd
pip install -r requirements.txt
pyinstaller --clean --noconfirm GeminiSRTTranslator.spec
```
생성된 실행 파일 위치: `dist\GeminiSRTTranslator.exe`

#### 3. GitHub Release 다운로드
Release에서 `GeminiSRTTranslator-Windows.zip` 다운로드 후 압축 해제하여 바로 실행.

### 소스 코드 직접 실행 방법

```bash
pip install -r requirements.txt
python main.py
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
| 배치 축소단위 | 오류 발생 시 배치 크기 자동 감축 단계 (기본: 100) |
| 오디오 축소단위 | 오류 발생 시 오디오 청크 자동 감축 단계 (기본: 60) |

### 폴더/설정 저장 위치

설정은 `QSettings(SETTINGS_ORG="GeminiSrtTranslatorGUI", SETTINGS_APP="GeminiSrtTranslatorGUI")`를 통해 OS 표준 위치(Windows 레지스트리)에 저장됩니다.

### 주의 사항

- API 키는 평문(Normal echo mode)으로 입력창에 표시됩니다. 화면 캡처나 공유 시 주의하세요.
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
- **Adaptive Batch & Audio Chunk Sizing (v3.8.3)**: Automatically reduces `batch_size` and `audio_chunk_size` on API errors (429/500/503) or parse failures, then restores original values on success
- **Google Cloud / Vertex AI (Enterprise)**: Supports Cloud Project, API Key, Region, and Request Type configuration
- **Auto Retry / Backoff**: Exponential backoff on consecutive failures; safely aborts when threshold is exceeded
- **Atomic File Save**: Subtitles are written atomically via temp file + `os.replace()` to prevent corruption
- **Auto Save / Restore Settings**: API keys, options, and file paths are persisted and restored via `QSettings`
- **UI Language Toggle**: Switch between Korean (한국어) and English at runtime

### Requirements

- Windows 10 or later (64-bit), or Linux/macOS
- Python 3.10 or later (for running from source)

### 📦 Build Windows 10+ Executable (.exe)

#### Option 1 — One-click Auto Build (Recommended)
Open the project folder on Windows and run `build_win.bat` or `build_win.ps1`. It automatically installs dependencies and builds the `.exe`.

```cmd
build_win.bat
```

When finished, the standalone executable is placed at `dist\GeminiSRTTranslator.exe`.

#### Option 2 — Manual Build (Command Prompt / PowerShell)
```cmd
pip install -r requirements.txt
pyinstaller --clean --noconfirm GeminiSRTTranslator.spec
```
Output: `dist\GeminiSRTTranslator.exe`

#### Option 3 — GitHub Release Download
Download `GeminiSRTTranslator-Windows.zip` from the latest Release, extract, and run directly.

### Running from Source

```bash
pip install -r requirements.txt
python main.py
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
| Batch Error Step | Auto-reduction step for batch size on errors (default: 100) |
| Audio Error Step | Auto-reduction step for audio chunk on errors (default: 60) |

### Settings Storage Location

Settings are stored via `QSettings(SETTINGS_ORG="GeminiSrtTranslatorGUI", SETTINGS_APP="GeminiSrtTranslatorGUI")` in the OS standard location (Windows Registry on Windows).

### Notes

- API keys are displayed in plain text in the input field. Be careful when screen-sharing or taking screenshots.
- Enterprise (Vertex AI) mode requires a separate Google Cloud Project and authentication credentials.
- This GUI targets the **v3.8.3** interface of the [gemini-srt-translator](https://pypi.org/project/gemini-srt-translator/) library. Some options may not work with different library versions.
