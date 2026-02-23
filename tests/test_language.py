from modules.language import detect_text_language


def test_detect_text_language_uses_custom_sanitizer():
    # 기본 텍스트만 보면 영어로 분류되지만, 커스텀 sanitizer가 한글을 반환하면 한국어로 분류되어야 한다.
    result = detect_text_language("This is English only", extract_text_func=lambda _: "한글")
    assert result == "ko"


def test_detect_text_language_default_path_unchanged():
    result = detect_text_language("This is an English sentence.")
    assert result == "en"
