import re
from typing import Optional

DESCRIPTION_SECTIONS = ("Observed", "Expected", "Expected Result", "Note", "Notes", "Video", "Etc.")

# 번역 스킵할 섹션 (영어 키워드 기준, 대소문자 무시)
SKIP_TRANSLATION_SECTIONS = ("QA Environment",)

def extract_attachments_markup(text: str) -> tuple[list[str], str]:
    """
    Jira 마크업에서 이미지와 첨부파일 마크업을 추출하고 플레이스홀더로 대체

    Args:
        text: 원본 텍스트

    Returns:
        (마크업 리스트, 플레이스홀더가 적용된 텍스트)
    """
    if not text:
        return [], ""

    attachments = []

    # 이미지 마크업 패턴: !image.png!, !image.png|thumbnail!, !image.png|width=300!
    image_pattern = r'!([^!]+?)(?:\|[^!]*)?!'

    # 첨부파일 마크업 패턴: [^attachment.pdf], [^video.mp4]
    attachment_pattern = r'\[\^([^\]]+?)\]'

    def replace_image(match):
        attachments.append(match.group(0))
        return f"__IMAGE_PLACEHOLDER_{len(attachments)-1}__"

    def replace_attachment(match):
        attachments.append(match.group(0))
        return f"__ATTACHMENT_PLACEHOLDER_{len(attachments)-1}__"

    # 플레이스홀더로 대체
    text = re.sub(image_pattern, replace_image, text)
    text = re.sub(attachment_pattern, replace_attachment, text)

    return attachments, text

def restore_attachments_markup(text: str, attachments: list[str]) -> str:
    """
    번역된 텍스트에 원본 마크업을 복원

    Args:
        text: 번역된 텍스트 (플레이스홀더 포함)
        attachments: 원본 마크업 리스트

    Returns:
        마크업이 복원된 텍스트
    """
    for i, attachment_markup in enumerate(attachments):
        # 이미지 플레이스홀더 복원
        text = text.replace(f"__IMAGE_PLACEHOLDER_{i}__", attachment_markup)
        # 첨부파일 플레이스홀더 복원
        text = text.replace(f"__ATTACHMENT_PLACEHOLDER_{i}__", attachment_markup)

    return text

def format_summary_value(original: str, translated: str) -> str:
    """
    Summary는 한 줄이어야 하고 Jira 필드 제한이 255자이므로
    원문은 그대로 두고 번역문만 잘라서 제한을 지킨다.
    """
    MAX_LEN = 255
    SEPARATOR = " / "

    def _normalize(text: str) -> str:
        return (text or "").replace("\n", " ").strip()

    def _truncate(text: str, limit: int) -> str:
        if limit <= 0:
            return ""
        if len(text) <= limit:
            return text
        if limit == 1:
            return text[:1]
        return text[: limit - 1].rstrip() + "…"

    original = _normalize(original)
    translated = _normalize(translated)

    if not original:
        return _truncate(translated, MAX_LEN)
    if not translated:
        return original

    remaining = MAX_LEN - len(original) - len(SEPARATOR)
    if remaining <= 0:
        return original

    truncated_translated = _truncate(translated, remaining)
    if not truncated_translated:
        return original

    return f"{original}{SEPARATOR}{truncated_translated}"

def format_steps_value(original: str, translated: str) -> str:
    original = (original or "").strip()
    translated = (translated or "").strip()
    if original and translated:
        return f"{original}\n\n{translated}"
    return original or translated

def split_bracket_prefix(text: str) -> tuple[str, str]:
    """
    Summary 맨 앞의 [System Menu] 같은 브래킷 블록을 분리한다.
    예) "[Test] [System Menu] 에디터 ..." -> ("[Test] [System Menu] ", "에디터 ...")
    여러 개의 대괄호 블록이 연속되는 경우도 허용한다.
    """
    if not text:
        return "", ""
    m = re.match(r'^(\s*(?:\[[^\]]*\]\s*)+)(.*)$', text)
    if m:
        return m.group(1), m.group(2)
    return "", text

def strip_bullet_prefix(text: str) -> str:
    return re.sub(r"^\s*(?:[-*#]+|\d+[\.\)])\s*", "", text).strip()

def is_media_line(stripped_line: str) -> bool:
    if not stripped_line:
        return False

    def _strip_bullet_prefix_local(text: str) -> str:
        return re.sub(r"^\s*(?:[-*#]+|\d+[\.\)])\s*", "", text or "").strip()

    candidates = [stripped_line, _strip_bullet_prefix_local(stripped_line)]

    for candidate in candidates:
        if not candidate:
            continue
        if candidate.startswith("!"):
            return True
        if candidate.startswith("[^"):
            return True
        # 이미지 메타데이터 패턴 감지 (예: width=...,height=...,alt="..."!)
        if re.search(r'(width|height|alt)=.*!$', candidate):
            return True
    if "__IMAGE_PLACEHOLDER" in stripped_line or "__ATTACHMENT_PLACEHOLDER" in stripped_line:
        return True
    return False

def is_code_block_line(line: str) -> bool:
    """
    코드블럭 태그 라인인지 판단.
    - {code} 또는 {code:language}가 포함된 라인
    - {noformat}이 포함된 라인
    """
    if not line:
        return False
    stripped = line.strip()
    
    # noformat 태그 감지
    if "{noformat}" in stripped:
        return True
        
    # code 태그 감지
    if re.search(r'\{code(?::[^}]*)?\}', stripped):
        return True
        
    return False

def is_inside_code_block(line: str, in_code_block: bool) -> tuple[bool, bool]:
    """
    코드블럭 내부인지 판단하고 상태 업데이트.
    {code}, {code:language}, {noformat} 블록을 모두 처리.
    태그가 한 줄에 홀수 개 있으면 상태를 토글합니다.
    
    Args:
        line: 현재 라인
        in_code_block: 현재 코드블럭 내부 상태
        
    Returns:
        (is_code_line, new_in_code_block_state)
        - is_code_line: 이 라인이 코드블럭 태그 라인인지 여부
        - new_in_code_block_state: 업데이트된 코드블럭 내부 상태
    """
    if not line:
        return False, in_code_block
    
    stripped = line.strip()
    
    # 1. {noformat} 처리
    if "{noformat}" in stripped:
        # 태그 개수 세기
        count = stripped.count("{noformat}")
        # 홀수 개면 상태 토글 (열거나 닫음)
        if count % 2 == 1:
            return True, not in_code_block
        # 짝수 개면 (열고 닫힘) 해당 라인은 코드 라인이지만 블록 상태는 유지
        return True, in_code_block
        
    # 2. {code} 처리
    # {code} 또는 {code:xxx} 태그 찾기
    code_tags = re.findall(r'\{code(?::[^}]*)?\}', stripped)
    if code_tags:
        # 태그 개수가 홀수면 상태 토글
        if len(code_tags) % 2 == 1:
            return True, not in_code_block
        return True, in_code_block
    
    # 코드블럭 내부 상태 유지
    return in_code_block, in_code_block

def match_bracket_label_header(line: str) -> Optional[str]:
    """
    *[라벨]* 또는 *[한글 / English]* 형태의 라벨을 헤더로 인식.
    매칭되면 원본 라인을 반환.
    
    예:
        "*[QA 환경 / QA Environment]*" -> "*[QA 환경 / QA Environment]*"
        "*[상세 설명 / Details]*"      -> "*[상세 설명 / Details]*"
    """
    if not line:
        return None
    
    stripped = line.strip()
    
    # *[...]* 패턴 매칭 (볼드 + 대괄호)
    if re.match(r'^\*\[[^\]]+\]\*\s*$', stripped):
        return stripped
    
    return None

def should_skip_section_translation(header: str) -> bool:
    """
    이 섹션 헤더가 번역 스킵 대상인지 판단.
    *[한글 / English]* 형태에서 영어 부분을 추출하여 SKIP_TRANSLATION_SECTIONS와 비교.
    """
    if not header:
        return False
    
    # *[한글 / English]* 형태에서 라벨 추출
    match = re.match(r'^\*\[([^\]]+)\]\*', header.strip())
    if match:
        label = match.group(1)
        # "/" 뒤의 영어 부분 추출
        if "/" in label:
            english_part = label.split("/", 1)[1].strip()
        else:
            english_part = label.strip()
        
        for skip_keyword in SKIP_TRANSLATION_SECTIONS:
            if skip_keyword.lower() in english_part.lower():
                return True
    
    return False

def match_section_header(line: str) -> Optional[str]:
    """
    Description 내에서 섹션 헤더(Observed, Expected, Note, Video 등)를 찾아서
    매칭되는 경우 원래 라벨(영어/국문 혼합 포함)을 반환한다.

    예:
        "Expected Result:"           -> "Expected Result:"
        "Expected/기대 결과:"        -> "Expected/기대 결과:"
        "Video/영상:"                -> "Video/영상:"
        "*[QA 환경 / QA Environment]*" -> "*[QA 환경 / QA Environment]*"
    """
    # 색상/스타일 마크업 제거
    stripped = re.sub(r"\{color:[^}]+\}|\{color\}", "", line or "").strip()
    
    # 1. *[라벨]* 패턴 체크 (우선)
    bracket_header = match_bracket_label_header(stripped)
    if bracket_header:
        return bracket_header
    
    # 2. 기존 DESCRIPTION_SECTIONS 매칭
    # 마지막 콜론 제거 및 양끝 * / _ 제거 (매칭 용도로만 사용)
    stripped_no_colon = stripped.rstrip(":").strip("*_ ")
    lowered = stripped_no_colon.lower()

    # 혼합 라벨에서 앞부분만 추출 (예: "expected/기대 결과", "observed(관찰 결과)" 등)
    if "/" in lowered:
        left = lowered.split("/", 1)[0].strip()
    else:
        left = lowered
    # 괄호나 추가 설명이 붙어도 앞부분만 비교하도록 조정
    left = re.split(r"[\(\[]", left, 1)[0].strip()

    for header in DESCRIPTION_SECTIONS:
        normalized = header.lower()
        # "expected" 또는 "expected result" 형태 모두 허용
        if left == normalized or left.startswith(f"{normalized} "):
            # 원본 형식을 그대로 반환 (콜론 포함)
            return stripped

    return None

def is_header_line(line: str) -> bool:
    """
    이 줄이 섹션 헤더(Observed / Expected / Note / Video 등)인지 여부를 판단.
    영어-only 라벨과 영어/국문 혼합 라벨(예: 'Expected/기대 결과:')을 모두 헤더로 취급한다.
    """
    cleaned = re.sub(r"\{color:[^}]+\}|\{color\}", "", line or "").strip()
    return match_section_header(cleaned) is not None

def extract_description_sections(text: str) -> list[tuple[Optional[str], str]]:
    if not text:
        return []

    sections: list[tuple[Optional[str], str]] = []
    current_header: Optional[str] = None
    buffer: list[str] = []

    def flush():
        nonlocal buffer
        if not buffer:
            return
        content = "\n".join(buffer).strip("\n")
        buffer = []
        if content:
            sections.append((current_header, content))

    for line in text.splitlines():
        header = match_section_header(line)
        if header:
            flush()
            current_header = header
            continue
        buffer.append(line)
    flush()

    return sections

def match_translated_line_format(original_line: str, translated_line: str) -> str:
    translation = translated_line.strip()
    if not translation:
        return ""

    # 원문에 색상 태그가 있는지 확인
    has_color_tag = "{color:" in original_line or "{color}" in original_line
    
    # 원문의 들여쓰기 및 불릿/번호 패턴 감지
    # 예: "  - Item" -> prefix="  - "
    # 예: "    1. Item" -> prefix="    1. "
    match = re.match(r"^(\s*(?:[-*#]+|\d+\.)\s+)(.*)", original_line)
    if match:
        prefix = match.group(1)
        cleaned_translation = strip_bullet_prefix(translation)
        # 원문의 prefix 구조를 유지하고, 내용만 색상 처리 (원문에 색상 태그가 없을 때만)
        if not has_color_tag:
            return f"{prefix}{{color:#4c9aff}}{cleaned_translation}{{color}}"
        else:
            return f"{prefix}{cleaned_translation}"
    
    # 불릿이 없는 경우 (일반 텍스트)
    # 원문의 leading whitespace를 감지하여 번역문에도 적용
    indent_match = re.match(r"^(\s*)", original_line)
    if indent_match:
        indent = indent_match.group(1)
        if not has_color_tag:
            return f"{indent}{{color:#4c9aff}}{translation}{{color}}"
        else:
            return f"{indent}{translation}"
    
    # 기본 케이스
    if not has_color_tag:
        return f"{{color:#4c9aff}}{translation}{{color}}"
    else:
        return translation

def format_bilingual_block(original: str, translated: str, header: Optional[str] = None) -> str:
    original = (original or "").strip("\n")
    translated = (translated or "").strip()
    
    lines: list[str] = []
    if header:
        lines.append(header)
        
    if not original:
        if translated:
            lines.append(f"{{color:#4c9aff}}{translated}{{color}}")
        return "\n".join(lines).strip()

    # 번역문 라인 준비
    # 원문의 코드블럭 상태를 추적하여 번역문에서도 동일하게 처리
    translation_source_lines = []
    in_code_block_trans = False
    
    # 원문을 먼저 스캔하여 번역 가능한 라인만 추출
    original_lines_for_scan = original.splitlines()
    translatable_original_lines = []
    in_code_block_orig = False
    
    for orig_line in original_lines_for_scan:
        is_code_line, in_code_block_orig = is_inside_code_block(orig_line, in_code_block_orig)
        if is_code_line or in_code_block_orig:
            continue  # 코드블럭 라인은 제외
        
        stripped_orig = orig_line.strip()
        if not stripped_orig:
            continue
        
        # 미디어, 헤더 라인은 번역 매칭에서 제외 (표는 포함)
        if is_media_line(stripped_orig) or is_header_line(stripped_orig):
            continue
        
        translatable_original_lines.append(orig_line)
    
    # 번역문에서도 코드블럭 라인 제외하고 번역 가능한 라인만 추출
    for trans_line in translated.splitlines():
        is_code_line, in_code_block_trans = is_inside_code_block(trans_line, in_code_block_trans)
        if is_code_line or in_code_block_trans:
            continue  # 코드블럭 라인은 제외
        
        trans_stripped = trans_line.strip()
        if not trans_stripped:
            continue
        
        # 미디어, 헤더 라인은 번역 매칭에서 제외
        if is_media_line(trans_stripped) or is_header_line(trans_stripped):
            continue
        
        translation_source_lines.append(trans_line)
        
    translation_index = 0

    def next_translation_line() -> str:
        nonlocal translation_index
        if translation_index < len(translation_source_lines):
            line = translation_source_lines[translation_index]
            translation_index += 1
            return line
        return ""

    # 텍스트 버퍼 (미디어 나오기 전까지의 텍스트를 모아둠)
    text_buffer: list[str] = []
    
    def flush_text_buffer():
        nonlocal text_buffer
        if not text_buffer:
            return
        
        # 1. 원문 텍스트 출력
        lines.extend(text_buffer)
        
        # 2. 번역문 텍스트 출력 (원문 바로 아래)
        # 원문 라인 수만큼 번역문을 가져와서 포맷팅
        translated_block = []
        for org_line in text_buffer:
            stripped = org_line.strip()
            if not stripped:
                continue
            
            translated_line = next_translation_line().strip()
            if translated_line:
                formatted = match_translated_line_format(org_line, translated_line)
                if formatted:
                    translated_block.append(formatted)
        
        if translated_block:
            # 원문과 번역 블록 사이에 빈 줄 추가
            lines.append("")
            lines.extend(translated_block)
        
        text_buffer = []

    original_lines = original.splitlines()
    in_code_block = False
    
    for line in original_lines:
        stripped = line.strip()
        
        # 코드블럭 상태 업데이트
        is_code_line, in_code_block = is_inside_code_block(line, in_code_block)
        
        # 코드블럭 내부 또는 코드블럭 태그 라인은 스킵
        if is_code_line or in_code_block:
            flush_text_buffer()  # 코드블럭 나오기 전 텍스트 처리
            lines.append(line)  # 코드블럭 라인 출력
            continue
        
        # 테이블 라인 처리 (|로 시작하고 |로 끝나는 경우)
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_text_buffer() # 테이블 나오기 전 텍스트 처리
            # Jira가 표를 제대로 렌더링하려면 앞에 빈 줄이 필요
            lines.append("")
            
            # 번역된 표 라인 가져오기 (LLM이 표 전체를 하나의 라인으로 번역)
            translated_table_line = next_translation_line()
            
            # 헤더 셀 (||)과 데이터 셀 (|) 구분
            is_header_row = line.strip().startswith("||")
            
            if is_header_row:
                # 헤더 행 처리
                orig_cells = line.split("||")
                trans_cells = translated_table_line.split("||") if translated_table_line else []
                
                new_cells = []
                for i, orig_cell in enumerate(orig_cells):
                    # split 결과의 첫번째와 마지막은 빈 문자열
                    if i == 0 or i == len(orig_cells) - 1:
                        new_cells.append(orig_cell)
                        continue
                    
                    # 원문 셀에서 별표 제거하여 실제 내용 추출
                    orig_content = orig_cell.strip().strip("*").strip()
                    if not orig_content:
                        new_cells.append(orig_cell)
                        continue
                    
                    # 대응하는 번역 셀 가져오기
                    if trans_cells and i < len(trans_cells):
                        trans_content = trans_cells[i].strip().strip("*").strip()
                        if trans_content:
                            # 포맷: "*원문/번역*"
                            new_cells.append(f"*{orig_content}/{trans_content}*")
                        else:
                            new_cells.append(orig_cell)
                    else:
                        new_cells.append(orig_cell)
                
                lines.append("||".join(new_cells))
            else:
                # 데이터 행 처리
                orig_cells = line.split("|")
                trans_cells = translated_table_line.split("|") if translated_table_line else []
                
                new_cells = []
                for i, orig_cell in enumerate(orig_cells):
                    # split 결과의 첫번째와 마지막은 빈 문자열
                    if i == 0 or i == len(orig_cells) - 1:
                        new_cells.append(orig_cell)
                        continue
                    
                    orig_content = orig_cell.strip()
                    if not orig_content:
                        new_cells.append(orig_cell)
                        continue
                    
                    # 셀 내용이 미디어인 경우 번역 스킵
                    if is_media_line(orig_content):
                        new_cells.append(orig_cell)
                        continue
                    
                    # 대응하는 번역 셀 가져오기
                    if trans_cells and i < len(trans_cells):
                        trans_content = trans_cells[i].strip()
                        if trans_content and not is_media_line(trans_content):
                            # 포맷: "원문/번역"
                            new_cells.append(f"{orig_content}/{trans_content}")
                        else:
                            new_cells.append(orig_cell)
                    else:
                        new_cells.append(orig_cell)
                
                lines.append("|".join(new_cells))
            continue

        # 미디어 라인 처리
        if is_media_line(stripped):
            flush_text_buffer() # 미디어 나오기 전 텍스트 처리
            lines.append(line) # 미디어 라인 출력
            continue
        
        # 헤더 라인 처리
        if is_header_line(stripped):
            flush_text_buffer()
            lines.append(line)
            continue

        # 일반 텍스트는 버퍼에 추가
        text_buffer.append(line)

    flush_text_buffer() # 남은 텍스트 처리
        
    return "\n".join(lines).strip()

