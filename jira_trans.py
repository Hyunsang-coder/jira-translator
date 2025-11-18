import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from dotenv import load_dotenv

import json
import base64
import urllib.parse

import requests
from openai import OpenAI


class JiraTicketTranslator:
    """Jira 티켓을 번역하면서 이미지/첨부파일 마크업을 유지하는 클래스"""

    # 섹션 헤더는 "영어 부분" 기준으로 관리
    # 예시:
    #   - "Observed:"
    #   - "Observed/관찰됨:"
    #   - "Expected/기대 결과:"
    #   - "Expected Result/기대 결과:"
    #   - "Note/참고:"
    #   - "Video/영상:"
    # 영어-only 헤더와 영어/국문 혼합 헤더를 모두 포착하기 위해
    # 가능한 영어 형태들을 나열해 둔다.
    DESCRIPTION_SECTIONS = ("Observed", "Expected", "Expected Result", "Note", "Video", "Etc.")

    def __init__(self, jira_url: str, email: str, api_token: str, openai_api_key: str):
        """
        Args:
            jira_url: Jira 인스턴스 URL (예: 'https://cloud.jira.krafton.com')
            email: Jira 계정 이메일
            api_token: Jira API 토큰
            openai_api_key: OpenAI API 키
        """
        self.jira_url = jira_url.rstrip("/")
        self.email = email
        self.api_token = api_token

        self.session = requests.Session()
        self.session.auth = (email, api_token)

        # OpenAI SDK 초기화 (LangChain 대체)
        self.openai = OpenAI(api_key=openai_api_key)
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-5-mini")

    def extract_attachments_markup(self, text: str) -> tuple[list[str], str]:
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

    def restore_attachments_markup(self, text: str, attachments: list[str]) -> str:
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

    def translate_text(self, text: str, target_language: str = "Korean") -> str:
        """
        텍스트를 번역 (마크업 제외)

        Args:
            text: 번역할 텍스트
            target_language: 목표 언어

        Returns:
            번역된 텍스트
        """
        if not text or not text.strip():
            return text

        # pbb_glossary.json을 읽어 용어 매핑(dict)으로 로드
        terms = self._load_pbb_glossary_terms()

        # target_language에 따라 글로서리 방향(소스 → 타겟)을 다르게 구성하고,
        # 실제 텍스트에 등장하는 용어만 선별해서 토큰 사용량을 줄인다.
        glossary_lines: list[str] = []
        if terms:
            tl = (target_language or "").lower()
            if tl.startswith("korean"):
                # English → Korean (JSON 정의 방향 그대로)
                source_to_target = terms  # {"reputation": "우호도"}
            else:
                # Korean → English (역방향)
                source_to_target = {tgt: src for src, tgt in terms.items()}

            lowered_text = text.lower()
            for src, tgt in source_to_target.items():
                if src.lower() in lowered_text:
                    glossary_lines.append(f"- {src} -> {tgt}")

        pbb_glossary_text = "\n".join(glossary_lines) if glossary_lines else ""

        glossary_instruction = ""
        if pbb_glossary_text:
            glossary_instruction = (
                "Use this PBB(Project Black Budget) glossary for PBB-specific terms "
                "(left = source, right = target):\n"
                f"{pbb_glossary_text}"
            )

        system_msg = (
            f"Translate to {target_language}. "
            "Preserve Jira markup (*bold*, _italic_, {{code}}, etc.) "
            "and translate only natural language text. "
            f"{glossary_instruction}"
        )

        response = self.openai.chat.completions.create(
            model=self.openai_model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": text},
            ],
        )
        return (response.choices[0].message.content or "").strip()

    def translate_field(self, field_value: str, target_language: Optional[str] = None) -> str:
        """
        Jira 필드 값을 번역 (이미지/첨부파일 마크업 보존)

        Args:
            field_value: 원본 필드 값
            target_language: 목표 언어

        Returns:
            번역된 필드 값 (마크업 보존)
        """
        if not field_value:
            return field_value

        target = target_language or self.determine_target_language(field_value)
        # 1. 이미지/첨부파일 마크업 추출
        attachments, clean_text = self.extract_attachments_markup(field_value)

        # 2. 텍스트만 번역
        translated_text = self.translate_text(clean_text, target)

        # 3. 마크업 복원
        final_text = self.restore_attachments_markup(translated_text, attachments)

        return final_text

    def translate_description_field(self, field_value: str, target_language: Optional[str] = None) -> str:
        sections = self._extract_description_sections(field_value)
        target = target_language or self.determine_target_language(field_value)

        if not sections:
            translated = self.translate_field(field_value, target)
            return self._format_bilingual_block(field_value, translated)

        formatted_sections = []
        for header, content in sections:
            translated_section = self.translate_field(content, target)
            formatted_sections.append(
                self._format_bilingual_block(content, translated_section, header=header)
            )

        return "\n\n".join(filter(None, formatted_sections)).strip()

    def determine_target_language(self, text: str) -> str:
        return {"ko": "English", "en": "Korean"}.get(self._detect_text_language(text), "Korean")

    def _detect_text_language(self, text: str) -> str:
        if not text:
            return "unknown"
        sanitized = self._extract_detectable_text(text)
        if not sanitized:
            return "unknown"
        korean_chars = len(re.findall(r"[\uac00-\ud7a3]", sanitized))
        latin_chars = len(re.findall(r"[A-Za-z]", sanitized))
        if korean_chars > latin_chars:
            return "ko"
        if latin_chars > 0:
            return "en"
        return "unknown"

    def _extract_detectable_text(self, text: str) -> str:
        cleaned = text
        cleaned = re.sub(r"![^!]+!", " ", cleaned)
        cleaned = re.sub(r"\[\^[^\]]+\]", " ", cleaned)
        cleaned = re.sub(r"__[^_]+__", " ", cleaned)
        cleaned = re.sub(r"\{color:[^}]+\}|\{color\}", " ", cleaned)
        cleaned = re.sub(r"`[^`]+`", " ", cleaned)
        cleaned = re.sub(r"[^A-Za-z\uac00-\ud7a3]", "", cleaned)
        return cleaned

    def _is_bilingual_summary(self, summary: str) -> bool:
        """
        Summary가 이미 '한글 / 영어' 같이 양언어로 구성되어 있는지 판별.
        브래킷 prefix([Test] [System Menu])는 제외하고, 나머지 core 부분만 검사한다.
        """
        _, core = self._split_bracket_prefix(summary or "")
        if " / " not in core:
            return False
        left, right = core.split(" / ", 1)
        left_lang = self._detect_text_language(left)
        right_lang = self._detect_text_language(right)
        if left_lang == "unknown" or right_lang == "unknown":
            return False
        return left_lang != right_lang

    def _is_description_already_translated(self, value: str) -> bool:
        """
        Description 내에 이미 번역 줄({color:#4c9aff} ...)이 포함되어 있으면
        한 번 이상 번역된 것으로 간주하고 다시 번역하지 않는다.
        """
        if not value:
            return False
        return "{color:#4c9aff}" in value

    def _is_steps_bilingual(self, value: str) -> bool:
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
        first_lang = self._detect_text_language(first)
        second_lang = self._detect_text_language(second)
        if first_lang == "unknown" or second_lang == "unknown":
            return False
        return first_lang != second_lang

    def _split_bracket_prefix(self, text: str) -> tuple[str, str]:
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

    def format_summary_value(self, original: str, translated: str) -> str:
        original = (original or "").strip()
        translated = (translated or "").strip()
        if not original:
            return translated
        if not translated:
            return original
        return f"{original} / {translated}"

    def format_steps_value(self, original: str, translated: str) -> str:
        original = (original or "").strip()
        translated = (translated or "").strip()
        if original and translated:
            return f"{original}\n\n{translated}"
        return original or translated

    def build_field_update_payload(self, translation_results: dict[str, dict[str, str]]) -> dict[str, str]:
        payload: dict[str, str] = {}
        for field, content in translation_results.items():
            original = content.get('original', '')
            translated = content.get('translated', '')
            if field == "summary":
                formatted = self.format_summary_value(original, translated)
            elif field == "description":
                formatted = translated
            elif field == "customfield_10399":
                formatted = self.format_steps_value(original, translated)
            else:
                formatted = translated or original

            if formatted:
                payload[field] = formatted

        return payload

    def _load_pbb_glossary_terms(self) -> dict[str, str]:
        """pbb_glossary.json에서 terms 딕셔너리를 로드.

        pbb_glossary.json 구조:
        {
            "description": "...",
            "terms": {
                "reputation": "우호도",
                ...
            }
        }
        """
        try:
            base_dir = Path(__file__).resolve().parent
            glossary_path = base_dir / "pbb_glossary.json"
            if not glossary_path.exists():
                return {}

            with glossary_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            terms = data.get("terms") or {}
            if not isinstance(terms, dict):
                return {}
            return terms
        except Exception:
            # 용어집이 없어도 번역은 동작해야 하므로 조용히 무시
            return {}
            
    def _format_bilingual_block(self, original: str, translated: str, header: Optional[str] = None) -> str:
        original = (original or "").strip()
        translated = (translated or "").strip()
        lines: list[str] = []
        if header:
            lines.append(header)

        if not original:
            if translated:
                lines.append(f"{{color:#4c9aff}}{translated}{{color}}")
            return "\n".join(lines).strip()

        translation_lines = [line for line in translated.splitlines() if line.strip()]
        translation_index = 0

        def next_translation_line() -> str:
            nonlocal translation_index
            if translation_index < len(translation_lines):
                line = translation_lines[translation_index]
                translation_index += 1
                return line
            return translated

        for line in original.splitlines():
            stripped = line.strip()
            lines.append(line)
            if not stripped or self._is_media_line(stripped) or self._is_header_line(stripped):
                continue
            translated_line = next_translation_line().strip()
            if translated_line:
                if self._is_media_line(translated_line) or self._is_header_line(translated_line):
                    continue
                formatted = self._match_translated_line_format(line, translated_line)
                if formatted:
                    lines.append(formatted)

        return "\n".join(lines).strip()

    def _match_translated_line_format(self, original_line: str, translated_line: str) -> str:
        translation = translated_line.strip()
        if not translation:
            return ""

        bullet_match = re.match(r"(\s*(?:[-*#]+|\d+\.)\s+)(.*)", original_line)
        if bullet_match:
            cleaned_translation = self._strip_bullet_prefix(translation)
            # 원문은 bullet을 유지하되, 번역 줄은 bullet 없이 색상만 입힌 텍스트로 표시
            return f"{{color:#4c9aff}}{cleaned_translation}{{color}}"
        return f"{{color:#4c9aff}}{translation}{{color}}"

    def _strip_bullet_prefix(self, text: str) -> str:
        return re.sub(r"^\s*(?:[-*#]+|\d+\.)\s+", "", text).strip()

    def _is_media_line(self, stripped_line: str) -> bool:
        if not stripped_line:
            return False
        if stripped_line.startswith("!"):
            return True
        if stripped_line.startswith("[^"):
            return True
        if "__IMAGE_PLACEHOLDER" in stripped_line or "__ATTACHMENT_PLACEHOLDER" in stripped_line:
            return True
        return False
    
    def _is_header_line(self, line: str) -> bool:
        """
        이 줄이 섹션 헤더(Observed / Expected / Note / Video 등)인지 여부를 판단.
        영어-only 라벨과 영어/국문 혼합 라벨(예: 'Expected/기대 결과:')을 모두 헤더로 취급한다.
        """
        cleaned = re.sub(r"\{color:[^}]+\}|\{color\}", "", line or "").strip()
        return self._match_section_header(cleaned) is not None

    def _extract_description_sections(self, text: str) -> list[tuple[str, str]]:
        if not text:
            return []

        sections: list[tuple[str, str]] = []
        current_header: Optional[str] = None
        buffer: list[str] = []

        def flush():
            if current_header is not None:
                sections.append((current_header, "\n".join(buffer).strip()))

        for line in text.splitlines():
            header = self._match_section_header(line)
            if header:
                flush()
                current_header = header
                buffer = []
                continue
            if current_header is not None:
                buffer.append(line)
        flush()

        return [(header, content) for header, content in sections if content]

    def _match_section_header(self, line: str) -> Optional[str]:
        """
        Description 내에서 섹션 헤더(Observed, Expected, Note, Video 등)를 찾아서
        매칭되는 경우 원래 라벨(영어/국문 혼합 포함)을 반환한다.

        예:
            "Expected Result:"           -> "Expected Result"
            "Expected/기대 결과:"        -> "Expected/기대 결과"
            "Video/영상:"                -> "Video/영상"
        """
        # 색상/스타일 마크업 제거
        stripped = re.sub(r"\{color:[^}]+\}|\{color\}", "", line or "").strip()
        # 마지막 콜론 제거 및 양끝 * / _ 제거
        stripped_no_colon = stripped.rstrip(":").strip("*_ ")
        lowered = stripped_no_colon.lower()

        # 영어/한글 혼합 라벨인 경우 (예: "expected/기대 결과")
        if "/" in lowered:
            left = lowered.split("/", 1)[0].strip()
        else:
            left = lowered

        for header in self.DESCRIPTION_SECTIONS:
            normalized = header.lower()
            # "expected" 또는 "expected result" 형태 모두 허용
            if left == normalized or left.startswith(f"{normalized} "):
                # canonical 문자열 대신, 실제 라벨(영어/국문 모두 포함 가능)을 그대로 사용
                return stripped_no_colon

        return None

    def normalize_field_value(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            return self._flatten_adf_node(value).strip()
        if isinstance(value, Sequence):
            flattened = "\n".join(
                filter(None, (self.normalize_field_value(item) for item in value))
            )
            return flattened.strip()
        return str(value).strip()

    def _flatten_adf_node(self, node) -> str:
        if isinstance(node, dict):
            node_type = node.get("type")
            if node_type == "text":
                return node.get("text", "")
            if node_type == "hardBreak":
                return "\n"
            content = node.get("content", [])
            text = "".join(self._flatten_adf_node(child) for child in content)
            if node_type in {"paragraph", "heading"} and text:
                return f"{text}\n"
            return text
        if isinstance(node, list):
            return "".join(self._flatten_adf_node(child) for child in node)
        return ""

    def fetch_issue_fields(
        self,
        issue_key: str,
        fields_to_fetch: Optional[Sequence[str]] = None
    ) -> dict[str, str]:
        if not fields_to_fetch:
            fields_to_fetch = ["summary", "description", "customfield_10399"]

        endpoint = f"{self.jira_url}/rest/api/2/issue/{issue_key}"
        params = {
            "fields": ",".join(fields_to_fetch),
            "expand": "renderedFields"
        }

        response = self.session.get(endpoint, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        fetched_fields: dict[str, str] = {}
        raw_fields = data.get("fields", {}) or {}
        rendered_fields = data.get("renderedFields", {}) or {}

        for field in fields_to_fetch:
            raw_value = raw_fields.get(field)
            normalized = self.normalize_field_value(raw_value)

            if not normalized:
                rendered_value = rendered_fields.get(field)
                normalized = self.normalize_field_value(rendered_value)

            if normalized:
                fetched_fields[field] = normalized

        return fetched_fields

    def update_issue_fields(self, issue_key: str, field_payload: dict[str, str]) -> None:
        if not field_payload:
            print("ℹ️ 업데이트할 필드가 없습니다.")
            return

        endpoint = f"{self.jira_url}/rest/api/2/issue/{issue_key}"
        response = self.session.put(endpoint, json={"fields": field_payload}, timeout=15)
        response.raise_for_status()
        print("✅ Jira 이슈가 업데이트되었습니다.")

    def translate_issue(
        self,
        issue_key: str,
        target_language: Optional[str] = None,
        fields_to_translate: Optional[list[str]] = None,
        perform_update: bool = False
    ) -> dict:
        """
        Jira 이슈를 번역

        Args:
            issue_key: Jira 이슈 키 (예: 'BUG-123')
            target_language: 목표 언어
            fields_to_translate: 번역할 필드 리스트 (기본: ['summary', 'description', 'customfield_10399'])

        Returns:
            번역 결과 딕셔너리
        """
        if fields_to_translate is None:
            fields_to_translate = ['summary', 'description', 'customfield_10399']

        # 1. 이슈 조회
        print(f"📥 Fetching issue {issue_key}...")
        issue_fields = self.fetch_issue_fields(issue_key, fields_to_translate)

        if not issue_fields:
            print(f"⚠️ No fields found for {issue_key}")
            return {"results": {}, "update_payload": {}, "updated": False, "error": "no_fields"}
        resolved_target = target_language
        if resolved_target is None:
            summary_text = issue_fields.get('summary', '')
            if summary_text:
                resolved_target = self.determine_target_language(summary_text)
            else:
                resolved_target = "Korean"

        # 2. 각 필드 번역
        translation_results = {}

        for field in fields_to_translate:
            field_value = issue_fields.get(field)

            if field_value:
                print(f"🔄 Translating {field}...")
                if field == "description":
                    # 이미 번역 줄이 포함된 Description은 다시 번역하지 않는다.
                    if self._is_description_already_translated(field_value):
                        print(f"⏭️ Skipping {field} (already translated)")
                        translated_value = ""
                    else:
                        translated_value = self.translate_description_field(field_value, resolved_target)
                elif field == "summary":
                    # 이미 '한글 / 영어' 같이 양언어로 구성된 Summary는 번역하지 않는다.
                    if self._is_bilingual_summary(field_value):
                        print(f"⏭️ Skipping {field} (already bilingual)")
                        translated_value = ""
                    else:
                        # 제목 앞의 [Test] [System Menu] 같은 블록은 번역 대상에서 제외
                        _, core = self._split_bracket_prefix(field_value)
                        if core:
                            translated_core = self.translate_field(core, resolved_target)
                        else:
                            translated_core = ""
                        # 번역 문자열에는 대괄호 prefix를 포함하지 않는다
                        translated_value = translated_core
                elif field == "customfield_10399":
                    # 재현 단계가 이미 '원문 블록 + 번역 블록' 구조면 다시 번역하지 않는다.
                    if self._is_steps_bilingual(field_value):
                        print(f"⏭️ Skipping {field} (already bilingual steps)")
                        translated_value = ""
                    else:
                        translated_value = self.translate_field(field_value, resolved_target)
                else:
                    translated_value = self.translate_field(field_value, resolved_target)
                translation_results[field] = {
                    'original': field_value,
                    'translated': translated_value
                }

        payload = self.build_field_update_payload(translation_results)
        updated = False
        error = None
        if perform_update and payload:
            try:
                self.update_issue_fields(issue_key, payload)
                updated = True
            except Exception as exc:
                error = str(exc)

        return {
            "results": translation_results,
            "update_payload": payload,
            "updated": updated,
            "error": error,
        }


def parse_issue_url(issue_url: str) -> tuple[str, str]:
    parsed = urlparse(issue_url.strip())

    if not parsed.scheme or not parsed.netloc:
        raise ValueError("유효한 Jira 이슈 URL을 입력해주세요.")

    base_url = f"{parsed.scheme}://{parsed.netloc}"
    path_segments = [segment for segment in parsed.path.split("/") if segment]

    issue_key = None
    if "browse" in path_segments:
        browse_index = path_segments.index("browse")
        if browse_index + 1 < len(path_segments):
            issue_key = path_segments[browse_index + 1]
    if not issue_key:
        match = re.search(r"[A-Z][A-Z0-9]+-\d+", parsed.path, re.IGNORECASE)
        if match:
            issue_key = match.group(0).upper()

    if not issue_key:
        raise ValueError("URL에서 Jira 이슈 키를 찾을 수 없습니다.")

    return base_url, issue_key


# 사용 예시
if __name__ == "__main__":

    load_dotenv()
    # 설정
    JIRA_URL = os.getenv("JIRA_URL", "https://cloud.jira.krafton.com").rstrip("/")
    JIRA_EMAIL = os.getenv("JIRA_EMAIL")
    JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    if not all([JIRA_EMAIL, JIRA_API_TOKEN, OPENAI_API_KEY]):
        raise EnvironmentError("JIRA_EMAIL, JIRA_API_TOKEN, OPENAI_API_KEY 환경 변수를 모두 설정해주세요.")

    issue_url_input = input("번역할 Jira 티켓 URL을 입력하세요: ").strip()
    if not issue_url_input:
        raise ValueError("Jira 티켓 URL은 필수 입력값입니다.")

    input_base_url, issue_key = parse_issue_url(issue_url_input)
    if JIRA_URL and JIRA_URL.lower() != input_base_url.lower():
        print(f"ℹ️ 입력된 URL의 Jira 서버({input_base_url})가 설정된 기본 URL({JIRA_URL})과 다릅니다. 기본 URL을 사용합니다.")

    # 번역기 초기화
    translator = JiraTicketTranslator(
        jira_url=JIRA_URL or input_base_url,
        email=JIRA_EMAIL,
        api_token=JIRA_API_TOKEN,
        openai_api_key=OPENAI_API_KEY
    )

    results_obj = translator.translate_issue(
        issue_key=issue_key,
        target_language=None,
        fields_to_translate=['summary', 'description', 'customfield_10399']
    )

    translation_results = results_obj.get("results", {}) if isinstance(results_obj, dict) else {}

    # 결과 출력
    if not translation_results:
        print("⚠️ 번역 결과가 없습니다.")
    else:
        print("\n📊 Translation Results:")
        print("="*50)
        for field, content in translation_results.items():
            print(f"\n{field.upper()}:")
            print("Original:")
            print(content.get('original', ''))
            print("\nTranslated:")
            print(content.get('translated', ''))

        update_payload = translator.build_field_update_payload(translation_results)
        if not update_payload:
            print("\nℹ️ 업데이트할 필드가 없습니다.")
        else:
            confirm = input("\nJira 이슈를 업데이트할까요? (y/n): ").strip().lower()
            if confirm == "y":
                try:
                    translator.update_issue_fields(issue_key, update_payload)
                except requests.HTTPError as exc:
                    print(f"❌ Jira 업데이트 실패: {exc}")
            else:
                print("ℹ️ 업데이트를 취소했습니다.")


## 핸들러 함수
def handler(event, context):
    event = event or {}
    # Parse API Gateway proxy body (JSON or x-www-form-urlencoded)
    body_raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        if isinstance(body_raw, str):
            body_raw = body_raw.encode("utf-8", "ignore")
        body_raw = base64.b64decode(body_raw).decode("utf-8", "ignore")
    headers = event.get("headers") or {}
    content_type = headers.get("content-type") or headers.get("Content-Type") or ""
    content_type = content_type.lower() if isinstance(content_type, str) else ""
    parsed = {}
    try:
        if "application/json" in content_type:
            parsed = json.loads(body_raw or "{}")
        elif "application/x-www-form-urlencoded" in content_type:
            parsed = {
                k: (v[0] if isinstance(v, list) else v)
                for k, v in urllib.parse.parse_qs(body_raw).items()
            }
    except Exception:
        parsed = {}
    if isinstance(parsed, dict):
        event.update(parsed)

    issue_key = event.get("issue_key")
    issue_url = event.get("issue_url")
    target_language = event.get("target_language")  # None이면 자동 판별
    fields = event.get("fields_to_translate", ['summary', 'description', 'customfield_10399'])
    do_update = event.get("update", False)
    jira_url_override = event.get("jira_url")  # 선택: 이벤트로 JIRA URL 재정의

    JIRA_URL = (jira_url_override or os.getenv("JIRA_URL", "https://cloud.jira.krafton.com")).rstrip("/")
    JIRA_EMAIL = os.getenv("JIRA_EMAIL")
    JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    if not all([JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, OPENAI_API_KEY]):
        raise EnvironmentError("JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, OPENAI_API_KEY 환경 변수가 필요합니다.")

    # issue_key 우선, 없으면 URL에서 추출
    if not issue_key:
        if issue_url:
            _, issue_key = parse_issue_url(issue_url)
        else:
            raise ValueError("issue_key 또는 issue_url 중 하나는 필수입니다.")

    translator = JiraTicketTranslator(
        jira_url=JIRA_URL,
        email=JIRA_EMAIL,
        api_token=JIRA_API_TOKEN,
        openai_api_key=OPENAI_API_KEY
    )

    results_obj = translator.translate_issue(
        issue_key=issue_key,
        target_language=target_language,
        fields_to_translate=fields,
        perform_update=do_update
    )

    return {
        "issue_key": issue_key,
        **results_obj
    }