import re

def detect_text_language(text: str, extract_text_func=None) -> str:
    """
    텍스트의 언어를 감지 (고도화된 로직).
    
    핵심 원칙:
    - 한국어 조사/어미가 있으면 거의 확실히 한국어 (영어 고유명사가 많아도)
    - 한글이 1자라도 있고 문장 구조가 한국어면 한국어
    - 순수 영어 문장 패턴이 있을 때만 영어로 판단
    
    Returns:
        "ko": 한국어
        "en": 영어
        "unknown": 알 수 없음
    """
    if not text:
        return "unknown"
    
    # 원본 텍스트에서 언어 감지 (마크업 제거 전)
    original_text = text
    
    # 마크업 제거된 텍스트
    # extract_text_func가 제공되면 우선 사용하고, 아니면 기본 구현을 사용한다.
    sanitizer = extract_text_func if callable(extract_text_func) else extract_detectable_text
    sanitized = sanitizer(text)
    if not sanitized:
        return "unknown"
    
    # 1. 한글 문자 개수
    korean_chars = len(re.findall(r"[\uac00-\ud7a3]", sanitized))
    
    # 2. 영어 문자 개수
    latin_chars = len(re.findall(r"[A-Za-z]", sanitized))
    
    # 3. 한국어 조사 패턴 (가장 확실한 한국어 지표)
    # 한글 + 조사 패턴: 영어 고유명사 뒤에 한국어 조사가 붙는 경우도 포함
    korean_particle_patterns = [
        # 주격/목적격 조사
        r'[\uac00-\ud7a3][이가](?:\s|$|[^\uac00-\ud7a3])',  # ~이/가
        r'[\uac00-\ud7a3][을를](?:\s|$|[^\uac00-\ud7a3])',  # ~을/를
        r'[\uac00-\ud7a3][은는](?:\s|$|[^\uac00-\ud7a3])',  # ~은/는
        # 부사격 조사
        r'[\uac00-\ud7a3]에서(?:\s|$)',  # ~에서
        r'[\uac00-\ud7a3]에(?:\s|$)',    # ~에
        r'[\uac00-\ud7a3]으?로(?:\s|$)', # ~으로/로
        r'[\uac00-\ud7a3][와과](?:\s|$)', # ~와/과
        r'[\uac00-\ud7a3]의(?:\s|$)',    # ~의
        # 영어 단어 + 한국어 조사 (고유명사 처리)
        r'[A-Za-z]에서(?:\s|$)',         # Records에서
        r'[A-Za-z]으?로(?:\s|$)',        # Tab으로
        r'[A-Za-z][을를](?:\s|$)',       # Tab을
        r'[A-Za-z][이가](?:\s|$)',       # Tab이
        r'[A-Za-z][은는](?:\s|$)',       # Tab은
        r'[A-Za-z]와(?:\s|$)',           # Tab와
    ]
    
    korean_particle_count = 0
    for pattern in korean_particle_patterns:
        korean_particle_count += len(re.findall(pattern, original_text))
    
    # 4. 한국어 어미 패턴 (문장 종결)
    korean_ending_patterns = [
        r'입니다[.!?\s]?$', r'습니다[.!?\s]?$', r'됩니다[.!?\s]?$',
        r'있습니다[.!?\s]?$', r'없습니다[.!?\s]?$', r'했습니다[.!?\s]?$',
        r'합니다[.!?\s]?$', r'됩니다[.!?\s]?$', r'집니다[.!?\s]?$',
        r'입니까[.!?\s]?$', r'습니까[.!?\s]?$',
        r'세요[.!?\s]?$', r'해요[.!?\s]?$', r'돼요[.!?\s]?$',
        r'[다음임함됨없음있음][.!?\s]?$',  # 음슴체
        r'현상입니다', r'현상임', r'발생함', r'확인됨',
        r'느립니다', r'빠릅니다', r'많습니다', r'적습니다',
        r'됩니다', r'않습니다', r'못합니다',
    ]
    
    korean_ending_count = 0
    for pattern in korean_ending_patterns:
        if re.search(pattern, original_text, re.MULTILINE):
            korean_ending_count += 1
    
    # 5. 한국어 문장 구조 점수
    korean_structure_score = korean_particle_count + korean_ending_count
    
    # 6. 영어 문장 패턴 (관사, 전치사, be동사 등이 문장 내에서 사용될 때)
    english_sentence_patterns = [
        r'\b(the|a|an)\s+\w+',           # 관사 + 명사
        r'\b(is|are|was|were|be)\s+',    # be동사
        r'\b(have|has|had)\s+(been|to)', # have + been/to
        r'\b(to|for|from|with|by|at|in|on)\s+\w+',  # 전치사 + 명사
        r'\b(when|where|what|who|why|how)\s+',      # 의문사
        r'\b(if|then|else|because|although)\s+',    # 접속사
        r'\bshould\s+(be|not|have)',     # should + 동사
        r'\bcan\s+(be|not|have)',        # can + 동사
        r'\bwill\s+(be|not|have)',       # will + 동사
    ]
    
    english_sentence_count = 0
    text_lower = original_text.lower()
    for pattern in english_sentence_patterns:
        english_sentence_count += len(re.findall(pattern, text_lower))
    
    # === 판단 로직 (우선순위 순) ===
    
    # 최우선: 한국어 조사/어미가 1개라도 있으면 한국어
    if korean_structure_score >= 1:
        return "ko"
    
    # 한글이 있고, 영어 문장 패턴이 없으면 한국어
    if korean_chars >= 1 and english_sentence_count == 0:
        return "ko"
    
    # 한글이 영어보다 많으면 한국어
    if korean_chars > latin_chars:
        return "ko"
    
    # 영어 문장 패턴이 있고 한글이 없으면 영어
    if english_sentence_count >= 1 and korean_chars == 0:
        return "en"
    
    # 한글 없고 영어가 있으면 영어
    if korean_chars == 0 and latin_chars > 0:
        return "en"
    
    # 기본값: 한글이 조금이라도 있으면 한국어로 (보수적 접근)
    if korean_chars > 0:
        return "ko"
    
    return "unknown"

def extract_detectable_text(text: str) -> str:
    cleaned = text
    cleaned = re.sub(r"![^!]+!", " ", cleaned)
    cleaned = re.sub(r"\[\^[^\]]+\]", " ", cleaned)
    cleaned = re.sub(r"__.*?__", " ", cleaned)
    cleaned = re.sub(r"\{color:[^}]+\}|\{color\}", " ", cleaned)
    cleaned = re.sub(r"`[^`]+`", " ", cleaned)
    cleaned = re.sub(r"[^A-Za-z\uac00-\ud7a3]", "", cleaned)
    return cleaned

def is_bilingual_summary(summary: str, split_bracket_func) -> bool:
    """
    Summary가 이미 '한글 / 영어' 같이 양언어로 구성되어 있는지 판별.
    브래킷 prefix([Test] [System Menu])는 제외하고, 나머지 core 부분만 검사한다.
    
    Args:
        summary: 요약 텍스트
        split_bracket_func: _split_bracket_prefix 함수 (순환 참조 방지 위해 인자로)
    """
    _, core = split_bracket_func(summary or "")
    if " / " not in core:
        return False
    left, right = core.split(" / ", 1)
    left_lang = detect_text_language(left)
    right_lang = detect_text_language(right)
    if left_lang == "unknown" or right_lang == "unknown":
        return False
    return left_lang != right_lang

def is_description_already_translated(value: str) -> bool:
    """
    Description 내에 이미 번역 줄({color:#4c9aff} ...)이 포함되어 있으면
    한 번 이상 번역된 것으로 간주하고 다시 번역하지 않는다.
    """
    if not value:
        return False
    # 단순히 태그만 있는 것이 아니라, 태그 안에 내용이 있거나 태그 뒤에 내용이 있는 패턴을 찾음
    # 예: {color:#4c9aff}Translation{color}
    # 단, 테이블 구분자(|)만 있는 경우는 제외 (예: {color:#4c9aff}|{color})
    return bool(re.search(r"\{color:#4c9aff\}(?!\s*\|?\s*\{color\}).+", value))

def is_steps_bilingual(value: str) -> bool:
    """
    customfield_10399(재현 단계)가 이미 '원문 블록 + 번역 블록' 형태인지 판별.
    format_steps_value에서 original + '\\n\\n' + translated 형태로 만드는 것을 이용한다.
    """
    if not value:
        return False
    parts = [p.strip() for p in value.split("\n\n") if p.strip()]
    if len(parts) < 2:
        return False
    first, second = parts[0], parts[1]
    first_lang = detect_text_language(first)
    second_lang = detect_text_language(second)
    if first_lang == "unknown" or second_lang == "unknown":
        return False
    return first_lang != second_lang
