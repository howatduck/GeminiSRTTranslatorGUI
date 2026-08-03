# Gemini SRT Translator GUI

PyQt6 기반 GUI 애플리케이션으로, [gemini-srt-translator](https://github.com/MaKTaiL/gemini-srt-translator) 라이브러리를 활용하여 자막(SRT/ASS) 번역과 비디오/오디오 전사(Transcribe)를 손쉽게 수행할 수 있습니다. Pyte 기반 VT100 터미널 에뮬레이터를 내장하여 콘솔 출력(색상, 진행률 등)을 GUI 안에서 그대로 확인할 수 있습니다.

## 주요 기능

- **자막 번역 (Translate)**: SRT/ASS 자막 파일을 원하는 언어로 번역
- **비디오/오디오 전사 (Transcribe)**: 비디오·오디오 파일에서 자막을 새로 생성
- **다중 언어 동시 처리**: 체크박스 콤보박스로 여러 대상 언어를 한 번에 선택해 일괄 작업
- **다중 API 키 로테이션**: 최대 10개의 Gemini API 키를 등록해 무료 할당량을 순환 사용
- **다중 파일 큐 처리**: 자막/비디오 파일을 여러 개 선택하면 순차적으로 처리
- **실시간 VT100 터미널 뷰**: 라이브러리의 콘솔 출력(색상 포함)을 앱 내에서 실시간 렌더링
- **세부 튜닝 옵션**: temperature, top_p, top_k, 사고(thinking) 예산/수준, 배치 크기, 서비스 티어 등
- **Google Cloud / Vertex AI(Enterprise) 연동**: Cloud Project, API Key, Region, Request Type 설정 지원
- **자동 재시도/백오프**: 연속 실패 시 지수 백오프로 대기하고, 임계치 초과 시 안전하게 작업 중단
- **설정 자동 저장/복원**: `QSettings` 기반으로 API 키, 옵션, 파일 경로 등을 재실행 시 자동 로드

## 요구 사항

- Python 3.9 이상 (Windows 빌드 시 PyInstaller 등으로 패키징 가능)
- 아래 패키지들

```
pip install PyQt6 pyte gemini-srt-translator google-genai
```

> `google-genai`는 "모델 가져오기" 기능(사용 가능한 Gemini 모델 목록 조회)에 필요합니다. 없어도 프로그램은 실행되지만 해당 버튼은 비활성화됩니다.

## 실행 방법

```
python gemini_srt_translator_gui.py
```

## Windows용 빌드 (PyInstaller 예시)

```
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed ^
  --name "GeminiSrtTranslatorGUI" ^
  gemini_srt_translator_gui.py
```

빌드 후 `dist/GeminiSrtTranslatorGUI.exe` 파일이 생성됩니다.

> 콘솔 창 없이 실행하려면 `--windowed` 옵션을 유지하세요. 실행 중 발생하는 오류를 콘솔에서 확인하고 싶다면 빌드 시 `--windowed`를 빼고 테스트하는 것을 권장합니다.

## 사용 방법 요약

1. **API 키 설정**: "API 키 관리..." 버튼을 눌러 최소 1개 이상의 Gemini API 키를 입력하고 저장합니다.
2. **작업 모드 선택**: 자막 번역 또는 비디오/오디오 전사 중 선택합니다.
3. **입력 파일 지정**:
   - 번역: SRT/ASS 파일 선택
   - 전사: 비디오 또는 오디오 파일 선택
4. **출력 폴더 지정**
5. **대상 언어 선택**: 다중 선택 콤보박스에서 원하는 언어를 체크
6. (선택) **기본 설정 / 고급 설정**에서 모델, 배치 크기, temperature 등 세부 옵션 조정
7. **🚀 작업 시작** 클릭 → 하단 터미널 창에서 실시간 진행 상황 확인
8. 필요 시 **🛑 작업 중단**으로 안전하게 중지 가능 (진행 중인 배치 완료 후 종료)

## 폴더/설정 저장 위치

설정은 `QSettings(SETTINGS_ORG="HANDANG", SETTINGS_APP="GeminiSrtTranslatorGUI_v3_6_2")`를 통해 OS 표준 위치(Windows 레지스트리)에 저장됩니다.

## 주의 사항

- API 키는 평문(Normal echo mode)으로 입력창에 표시됩니다. 화면 캡처나 공유 시 주의하세요.
- Enterprise(Vertex AI) 모드 사용 시 별도의 Google Cloud Project / 인증 정보가 필요합니다.
- 이 GUI는 [gemini-srt-translator](https://pypi.org/project/gemini-srt-translator/) 라이브러리의 v3.6.2 인터페이스에 맞춰 작성되었습니다. 라이브러리 버전이 다르면 일부 옵션이 동작하지 않을 수 있습니다.
