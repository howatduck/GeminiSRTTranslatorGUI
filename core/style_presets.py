# -*- coding: utf-8 -*-
"""번역 스타일 프리셋.

사람들이 자막을 이용할 때 선호하는 대표적인 스타일을 미리 정의해 둔다.
각 프리셋의 ``instruction`` 은 번역 프롬프트(description)에 합쳐져서
LLM에게 원하는 문체를 지시한다. (리서치: 업계 트렌드는 드라마/미디어 자막의
자연스러운 구어체 선호, 자막 번역 원칙은 구어체·간결성·2줄 제한)
"""

STYLE_PRESETS = [
    {
        "id": "default",
        "name_ko": "기본 (프리셋 없음)",
        "name_en": "Default (no preset)",
        "instruction": "",
    },
    {
        "id": "natural_speech",
        "name_ko": "자연스러운 구어체",
        "name_en": "Natural colloquial",
        "instruction": (
            "## Style Preset: Natural Colloquial\n"
            "- Translate dialogue the way real people speak in everyday conversation.\n"
            "- Use contractions, interjections, and natural sentence fragments where the "
            "source does. Avoid stiff, written-style wording.\n"
            "- Match each speaker's tone and speech level (polite/casual) to the situation.\n"
            "- Keep lines short and punchy so they read comfortably as on-screen subtitles."
        ),
    },
    {
        "id": "drama_cinema",
        "name_ko": "드라마·영화 자막체",
        "name_en": "Drama & film subtitles",
        "instruction": (
            "## Style Preset: Drama & Film Subtitles\n"
            "- Use the classic broadcast subtitle style: concise, dramatic, and easy to "
            "scan in 1-2 seconds.\n"
            "- Prefer short sentences; split long lines at natural pauses.\n"
            "- Preserve emotional intensity (anger, sarcasm, tenderness) without over-explaining.\n"
            "- Keep character names, titles, and repeated catchphrases consistent."
        ),
    },
    {
        "id": "documentary",
        "name_ko": "다큐멘터리 내레이션체",
        "name_en": "Documentary narration",
        "instruction": (
            "## Style Preset: Documentary Narration\n"
            "- Use a formal, calm narration tone suitable for documentaries.\n"
            "- Prefer complete, well-structured sentences over fragments.\n"
            "- Explain technical terms or proper nouns briefly when the meaning would "
            "otherwise be unclear.\n"
            "- Keep a consistent, neutral register throughout."
        ),
    },
    {
        "id": "anime_dub",
        "name_ko": "애니메이션 더빙체",
        "name_en": "Anime dubbing style",
        "instruction": (
            "## Style Preset: Anime Dubbing Style\n"
            "- Translate with a lively, expressive tone that fits animated characters.\n"
            "- Keep each character's speech quirks and personality consistent.\n"
            "- Onomatopoeia and exclamations should feel energetic, not literal.\n"
            "- Lines must stay short enough to match the speaking rhythm."
        ),
    },
    {
        "id": "literal_study",
        "name_ko": "어학용 직역",
        "name_en": "Literal (for language study)",
        "instruction": (
            "## Style Preset: Literal Translation for Language Study\n"
            "- Translate as literally as possible while staying grammatical.\n"
            "- Preserve the source sentence structure and word order where feasible, "
            "so learners can map words between languages.\n"
            "- Do NOT paraphrase idioms away: keep them close to the original wording.\n"
            "- Consistency of vocabulary choice matters more than elegance."
        ),
    },
    {
        "id": "variety_youtube",
        "name_ko": "예능·유튜브체",
        "name_en": "Variety / YouTube style",
        "instruction": (
            "## Style Preset: Variety / YouTube Style\n"
            "- Use a casual, fun, high-energy tone like entertainment show captions.\n"
            "- Reactions and jokes should land fast: prefer witty, snappy phrasing.\n"
            "- Light use of modern slang is OK when it matches the speaker's vibe, "
            "but never at the cost of clarity.\n"
            "- Keep lines very short; viewers read these at a glance."
        ),
    },
    {
        "id": "kids",
        "name_ko": "어린이용",
        "name_en": "For kids",
        "instruction": (
            "## Style Preset: For Kids\n"
            "- Use simple vocabulary and short sentences a child can understand.\n"
            "- Explain difficult concepts in plain words instead of using technical terms.\n"
            "- Keep a warm, friendly tone throughout."
        ),
    },
]


def get_preset(preset_id):
    """프리셋 id로 프리셋 dict 반환. 없으면 default."""
    for p in STYLE_PRESETS:
        if p["id"] == preset_id:
            return p
    return STYLE_PRESETS[0]


def preset_instruction(preset_id):
    """프리셋의 프롬프트 지시문 반환 (default는 빈 문자열)."""
    return get_preset(preset_id)["instruction"]


def compose_description(user_description, preset_id):
    """사용자 입력 문맥 + 스타일 프리셋 지시문을 하나의 description으로 합성.

    라이브러리의 get_translate_instruction(description=...) 으로 전달된다.
    """
    parts = []
    user_description = (user_description or "").strip()
    if user_description:
        parts.append(user_description)
    instruction = preset_instruction(preset_id)
    if instruction:
        parts.append(instruction)
    return "\n\n---\n\n".join(parts) if parts else None
