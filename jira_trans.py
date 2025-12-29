import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from dotenv import load_dotenv

import json
import base64
import urllib.parse

import requests
from openai import OpenAI
from pydantic import BaseModel


@dataclass
class TranslationChunk:
    id: str
    field: str
    original_text: str
    clean_text: str
    attachments: list[str]
    header: Optional[str] = None


class TranslationItem(BaseModel):
    id: str
    translated: str


class TranslationResponse(BaseModel):
    translations: list[TranslationItem]


@dataclass
class FieldTranslationJob:
    field: str
    original_value: str
    chunks: list[TranslationChunk]
    mode: str = "default"


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
    DESCRIPTION_SECTIONS = ("Observed", "Expected", "Expected Result", "Note", "Notes", "Video", "Etc.")

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
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-5.1")
        
        # 용어집 데이터 (translate_issue 호출 시 로드됨)
        self.glossary_terms: dict[str, str] = {}
        self.glossary_name: str = ""

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

    def translate_text(self, text: str) -> str:
        """
        텍스트를 번역 (마크업 제외)
        한글 텍스트는 영어로, 영어 텍스트는 한글로 자동 번역.

        Args:
            text: 번역할 텍스트

        Returns:
            번역된 텍스트
        """
        if not text or not text.strip():
            return text

        # 언어 감지 먼저 수행
        detected_lang = self._detect_text_language(text)
        
        glossary_instruction = self._build_glossary_instruction([text])
        
        if detected_lang == "ko":
            # 한국어 → 영어: 완전한 영어로 번역
            system_msg = (
                "You are a professional Korean to English translator. "
                "Translate the following Korean text to English. "
                "The output MUST be 100% in English - do NOT leave any Korean words. "
                "Preserve Jira markup (*bold*, _italic_, {{code}}, etc.)."
            )
        else:
            # 영어 → 한국어: 고유명사는 영어 유지
            system_msg = (
                "You are a professional English to Korean translator. "
                "Translate the following English text to Korean. "
                "Keep proper nouns and game-specific terms in English. "
                "Use terse memo-style (음슴체): drop endings such as '합니다', "
                "favor noun phrases like '하이드아웃 진입', '이슈 확인'. "
                "Preserve Jira markup (*bold*, _italic_, {{code}}, etc.)."
            )
        
        if glossary_instruction:
            system_msg = f"{system_msg} {glossary_instruction}"

        response = self.openai.chat.completions.create(
            model=self.openai_model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": text},
            ],
        )
        return (response.choices[0].message.content or "").strip()

    def _build_glossary_instruction(self, texts: Sequence[str]) -> str:
        """
        양방향 용어집 지원: 영어→한국어, 한국어→영어 모두 포함.
        단어 경계 매칭(\b)을 사용하여 정확히 일치하는 용어만 찾습니다.
        예: 'key' 검색 시 'monkey'는 무시함.
        """
        terms = self.glossary_terms
        if not terms:
            return ""

        combined_text = "\n".join(texts).lower()
        glossary_lines: list[str] = []

        for eng, kor in terms.items():
            # 영어 용어가 텍스트에 있으면 영어→한국어 매핑 추가
            eng_pattern = r"\b" + re.escape(eng.lower()) + r"\b"
            if re.search(eng_pattern, combined_text):
                glossary_lines.append(f"- {eng} <-> {kor}")
                continue
            
            # 한국어 용어가 텍스트에 있으면 한국어→영어 매핑 추가
            if kor.lower() in combined_text:
                glossary_lines.append(f"- {kor} <-> {eng}")

        if not glossary_lines:
            return ""

        glossary_name_display = self.glossary_name or "Project"
        return (
            f"Use this {glossary_name_display} glossary for specific terms "
            "(bidirectional mapping):\n"
            + "\n".join(glossary_lines)
        )

    def translate_field(self, field_value: str) -> str:
        """
        Jira 필드 값을 번역 (이미지/첨부파일 마크업 보존)
        한글→영어, 영어→한글 자동 번역.

        Args:
            field_value: 원본 필드 값

        Returns:
            번역된 필드 값 (마크업 보존)
        """
        if not field_value:
            return field_value

        # 1. 이미지/첨부파일 마크업 추출
        attachments, clean_text = self.extract_attachments_markup(field_value)

        # 2. 텍스트만 번역
        translated_text = self.translate_text(clean_text)

        # 3. 마크업 복원
        final_text = self.restore_attachments_markup(translated_text, attachments)

        return final_text

    def _translate_chunk_text(
        self,
        chunk: TranslationChunk,
    ) -> str:
        return self.translate_text(chunk.clean_text) or ""

    def _translate_chunk_list(
        self,
        chunk_list: Sequence[TranslationChunk],
    ) -> dict[str, str]:
        translations: dict[str, str] = {}
        for chunk in chunk_list:
            translations[chunk.id] = self._translate_chunk_text(chunk)
        return translations

    def _translate_chunks_individually(
        self,
        jobs: dict[str, FieldTranslationJob],
    ) -> dict[str, str]:
        per_chunk: dict[str, str] = {}
        for job in jobs.values():
            per_chunk.update(self._translate_chunk_list(job.chunks))
        return per_chunk

    def translate_description_field(self, field_value: str) -> str:
        """한글→영어, 영어→한글 자동 번역."""
        sections = self._extract_description_sections(field_value)

        if not sections:
            translated = self.translate_field(field_value)
            return self._format_bilingual_block(field_value, translated)

        formatted_sections = []
        for header, content in sections:
            translated_section = self.translate_field(content)
            formatted_sections.append(
                self._format_bilingual_block(content, translated_section, header=header)
            )

        return "\n\n".join(filter(None, formatted_sections)).strip()

    def _detect_text_language(self, text: str) -> str:
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
        sanitized = self._extract_detectable_text(text)
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

    def _extract_detectable_text(self, text: str) -> str:
        cleaned = text
        cleaned = re.sub(r"![^!]+!", " ", cleaned)
        cleaned = re.sub(r"\[\^[^\]]+\]", " ", cleaned)
        cleaned = re.sub(r"__.*?__", " ", cleaned)
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
        # 단순히 태그만 있는 것이 아니라, 태그 안에 내용이 있거나 태그 뒤에 내용이 있는 패턴을 찾음
        # 예: {color:#4c9aff}Translation{color}
        # 단, 테이블 구분자(|)만 있는 경우는 제외 (예: {color:#4c9aff}|{color})
        return bool(re.search(r"\{color:#4c9aff\}(?!\s*\|?\s*\{color\}).+", value))

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

            if not translated:
                continue

            if field == "summary":
                formatted = self.format_summary_value(original, translated)
            elif field == "description":
                formatted = translated
            elif field.startswith("customfield_"): # Steps to Reproduce fields
                formatted = self.format_steps_value(original, translated)
            else:
                formatted = translated

            if formatted:
                payload[field] = formatted

        return payload

    def _load_glossary_terms(self, filename: str) -> dict[str, str]:
        """지정된 용어집 파일에서 terms 딕셔너리를 로드."""
        try:
            base_dir = Path(__file__).resolve().parent
            glossary_path = base_dir / filename
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

    def _call_openai_batch(
        self,
        chunks: Sequence[TranslationChunk],
        retries: int = 2,
    ) -> dict[str, str]:
        if not chunks:
            return {}

        attempt = 0
        last_error: Optional[Exception] = None
        batch_result: dict[str, str] = {}

        while attempt <= retries:
            attempt += 1
            try:
                batch_result = self._call_openai_batch_once(chunks)
                break
            except Exception as exc:
                last_error = exc
                if attempt > retries:
                    break
                print(f"⚠️ Batch translation failed (attempt {attempt}/{retries + 1}): {exc}")

        if not batch_result and last_error:
            raise last_error

        missing_ids = [chunk.id for chunk in chunks if chunk.id not in batch_result]
        if missing_ids:
            print(f"⚠️ Batch translation missing {len(missing_ids)} chunk(s); retrying individually.")
            missing_chunks = [chunk for chunk in chunks if chunk.id in missing_ids]
            fallback = self._translate_chunk_list(missing_chunks)
            batch_result.update(fallback)

        return batch_result

    def _call_openai_batch_once(
        self,
        chunks: Sequence[TranslationChunk],
    ) -> dict[str, str]:
        """
        OpenAI Structured Outputs(beta.parse)를 사용하여
        JSON 파싱 에러를 원천 차단하고 안정성을 확보합니다.
        한글→영어, 영어→한글 자동 번역.
        """
        if not chunks:
            return {}

        glossary_instruction = self._build_glossary_instruction(
            [chunk.clean_text for chunk in chunks],
        )
        
        # 청크들의 주요 언어 감지 (첫 번째 청크 기준)
        combined_text = "\n".join(chunk.clean_text for chunk in chunks)
        detected_lang = self._detect_text_language(combined_text)
        
        if detected_lang == "ko":
            # 한국어 → 영어: 완전한 영어로 번역
            system_msg = (
                "You are a professional Korean to English translator. "
                "Translate each provided Korean text to English. "
                "The output MUST be 100% in English - do NOT leave any Korean words. "
                "Preserve Jira markup (*bold*, _italic_, {{code}}, etc.), bullet indentation, "
                "and placeholder tokens like __IMAGE_PLACEHOLDER__. "
                "IMPORTANT: Keep the exact same number of lines as the source text. "
                "Do not add commentary."
            )
        else:
            # 영어 → 한국어: 고유명사는 영어 유지
            system_msg = (
                "You are a professional English to Korean translator. "
                "Translate each provided English text to Korean. "
                "Keep proper nouns and game-specific terms in English. "
                "Use terse memo-style (음슴체) and concise noun phrases for titles/summaries. "
                "Preserve Jira markup (*bold*, _italic_, {{code}}, etc.), bullet indentation, "
                "and placeholder tokens like __IMAGE_PLACEHOLDER__. "
                "IMPORTANT: Keep the exact same number of lines as the source text. "
                "Do not add commentary."
            )
        
        if glossary_instruction:
            system_msg = f"{system_msg} {glossary_instruction}"

        # Structured Outputs용 페이로드 구성
        payload = {
            "items": [
                {"id": chunk.id, "text": chunk.clean_text}
                for chunk in chunks
            ]
        }
        user_msg = (
            f"Translate the text fields in the following JSON data. Keep 'id' unchanged.\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

        # client.beta.chat.completions.parse 사용
        # response_format에 Pydantic 클래스를 넘겨줍니다.
        completion = self.openai.beta.chat.completions.parse(
            model=self.openai_model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_format=TranslationResponse,
        )

        # 파싱된 결과(parsed)를 바로 사용
        parsed_response = completion.choices[0].message.parsed
        
        if not parsed_response or not parsed_response.translations:
            # 매우 드문 경우지만 결과가 없을 때를 대비
            raise ValueError("Translation returned no structured data.")

        result: dict[str, str] = {}
        for item in parsed_response.translations:
            if item.id and item.translated:
                result[item.id] = item.translated.strip()

        return result

    def _create_translation_chunk(
        self,
        *,
        chunk_id: str,
        field: str,
        original_text: str,
        header: Optional[str] = None,
    ) -> Optional[TranslationChunk]:
        if original_text is None:
            return None

        attachments, clean_text = self.extract_attachments_markup(original_text)
        return TranslationChunk(
            id=chunk_id,
            field=field,
            original_text=original_text,
            clean_text=clean_text,
            attachments=attachments,
            header=header,
        )

    def _plan_field_translation_job(
        self,
        field: str,
        value: str,
    ) -> Optional[FieldTranslationJob]:
        if not value:
            return None

        if field == "summary":
            _, core = self._split_bracket_prefix(value)
            if not core.strip():
                return None
            chunk = self._create_translation_chunk(
                chunk_id="summary",
                field=field,
                original_text=core,
            )
            if not chunk:
                return None
            return FieldTranslationJob(
                field=field,
                original_value=value,
                chunks=[chunk],
            )

        if field == "description":
            sections = self._extract_description_sections(value)
            chunks: list[TranslationChunk] = []
            if sections:
                for idx, (header, content) in enumerate(sections):
                    if not content.strip():
                        continue
                    chunk = self._create_translation_chunk(
                        chunk_id=f"{field}__section_{idx}",
                        field=field,
                        original_text=content,
                        header=header,
                    )
                    if chunk:
                        chunks.append(chunk)
            else:
                chunk = self._create_translation_chunk(
                    chunk_id=f"{field}__full",
                    field=field,
                    original_text=value,
                )
                if chunk:
                    chunks.append(chunk)
            if not chunks:
                return None
            return FieldTranslationJob(
                field=field,
                original_value=value,
                chunks=chunks,
                mode="description",
            )

        chunk = self._create_translation_chunk(
            chunk_id=field,
            field=field,
            original_text=value,
        )
        if not chunk:
            return None
        return FieldTranslationJob(
            field=field,
            original_value=value,
            chunks=[chunk],
        )
            
    def _format_bilingual_block(self, original: str, translated: str, header: Optional[str] = None) -> str:
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
            is_code_line, in_code_block_orig = self._is_inside_code_block(orig_line, in_code_block_orig)
            if is_code_line or in_code_block_orig:
                continue  # 코드블럭 라인은 제외
            
            stripped_orig = orig_line.strip()
            if not stripped_orig:
                continue
            
            # 미디어, 헤더 라인은 번역 매칭에서 제외 (표는 포함)
            if self._is_media_line(stripped_orig) or self._is_header_line(stripped_orig):
                continue
            
            translatable_original_lines.append(orig_line)
        
        # 번역문에서도 코드블럭 라인 제외하고 번역 가능한 라인만 추출
        for trans_line in translated.splitlines():
            is_code_line, in_code_block_trans = self._is_inside_code_block(trans_line, in_code_block_trans)
            if is_code_line or in_code_block_trans:
                continue  # 코드블럭 라인은 제외
            
            trans_stripped = trans_line.strip()
            if not trans_stripped:
                continue
            
            # 미디어, 헤더 라인은 번역 매칭에서 제외
            if self._is_media_line(trans_stripped) or self._is_header_line(trans_stripped):
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
                    formatted = self._match_translated_line_format(org_line, translated_line)
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
            is_code_line, in_code_block = self._is_inside_code_block(line, in_code_block)
            
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
                        if self._is_media_line(orig_content):
                            new_cells.append(orig_cell)
                            continue
                        
                        # 대응하는 번역 셀 가져오기
                        if trans_cells and i < len(trans_cells):
                            trans_content = trans_cells[i].strip()
                            if trans_content and not self._is_media_line(trans_content):
                                # 포맷: "원문/번역"
                                new_cells.append(f"{orig_content}/{trans_content}")
                            else:
                                new_cells.append(orig_cell)
                        else:
                            new_cells.append(orig_cell)
                    
                    lines.append("|".join(new_cells))
                continue

            # 미디어 라인 처리
            if self._is_media_line(stripped):
                flush_text_buffer() # 미디어 나오기 전 텍스트 처리
                lines.append(line) # 미디어 라인 출력
                continue
            
            # 헤더 라인 처리
            if self._is_header_line(stripped):
                flush_text_buffer()
                lines.append(line)
                continue

            # 일반 텍스트는 버퍼에 추가
            text_buffer.append(line)

        flush_text_buffer() # 남은 텍스트 처리
            
        return "\n".join(lines).strip()

    def _match_translated_line_format(self, original_line: str, translated_line: str) -> str:
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
            cleaned_translation = self._strip_bullet_prefix(translation)
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

    def _strip_bullet_prefix(self, text: str) -> str:
        return re.sub(r"^\s*(?:[-*#]+|\d+[\.\)])\s*", "", text).strip()

    def _is_media_line(self, stripped_line: str) -> bool:
        if not stripped_line:
            return False

        def _strip_bullet_prefix(text: str) -> str:
            return re.sub(r"^\s*(?:[-*#]+|\d+[\.\)])\s*", "", text or "").strip()

        candidates = [stripped_line, _strip_bullet_prefix(stripped_line)]

        for candidate in candidates:
            if not candidate:
                continue
            if candidate.startswith("!"):
                return True
            if candidate.startswith("[^"):
                return True
            if candidate.startswith("["):
                return True
            # 이미지 메타데이터 패턴 감지 (예: width=...,height=...,alt="..."!)
            if re.search(r'(width|height|alt)=.*!$', candidate):
                return True
        if "__IMAGE_PLACEHOLDER" in stripped_line or "__ATTACHMENT_PLACEHOLDER" in stripped_line:
            return True
        return False
    
    def _is_code_block_line(self, line: str) -> bool:
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

    def _is_inside_code_block(self, line: str, in_code_block: bool) -> tuple[bool, bool]:
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
    
    def _is_header_line(self, line: str) -> bool:
        """
        이 줄이 섹션 헤더(Observed / Expected / Note / Video 등)인지 여부를 판단.
        영어-only 라벨과 영어/국문 혼합 라벨(예: 'Expected/기대 결과:')을 모두 헤더로 취급한다.
        """
        cleaned = re.sub(r"\{color:[^}]+\}|\{color\}", "", line or "").strip()
        return self._match_section_header(cleaned) is not None

    def _extract_description_sections(self, text: str) -> list[tuple[Optional[str], str]]:
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
            header = self._match_section_header(line)
            if header:
                flush()
                current_header = header
                continue
            buffer.append(line)
        flush()

        return sections

    def _match_section_header(self, line: str) -> Optional[str]:
        """
        Description 내에서 섹션 헤더(Observed, Expected, Note, Video 등)를 찾아서
        매칭되는 경우 원래 라벨(영어/국문 혼합 포함)을 반환한다.

        예:
            "Expected Result:"           -> "Expected Result:"
            "Expected/기대 결과:"        -> "Expected/기대 결과:"
            "Video/영상:"                -> "Video/영상:"
        """
        # 색상/스타일 마크업 제거
        stripped = re.sub(r"\{color:[^}]+\}|\{color\}", "", line or "").strip()
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

        for header in self.DESCRIPTION_SECTIONS:
            normalized = header.lower()
            # "expected" 또는 "expected result" 형태 모두 허용
            if left == normalized or left.startswith(f"{normalized} "):
                # 원본 형식을 그대로 반환 (콜론 포함)
                return stripped

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
            # 기본값은 호출하는 쪽에서 결정해서 넘겨주도록 변경됨
            # 하지만 안전장치로 남겨둠
            fields_to_fetch = ["summary", "description"]

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
        
        # 👇 [추가] 에러 발생 시 상세 응답 내용 출력
        if not response.ok:
            print(f"❌ Jira API Error ({response.status_code})")
            print(f"Response: {response.text}")
            
        response.raise_for_status()
        print("✅ Jira 이슈가 업데이트되었습니다.")

    def translate_issue(
        self,
        issue_key: str,
        fields_to_translate: Optional[list[str]] = None,
        perform_update: bool = False
    ) -> dict:
        """
        Jira 이슈를 번역 (한글→영어, 영어→한글 자동 번역)

        Args:
            issue_key: Jira 이슈 키 (예: 'BUG-123')
            fields_to_translate: 번역할 필드 리스트 (기본: None -> 자동 결정)

        Returns:
            번역 결과 딕셔너리
        """
        # 1. 티켓 타입 판별 및 설정
        if issue_key.upper().startswith("PUBG-"):
            steps_field = "customfield_10237"
            glossary_file = "pubg_glossary.json"
            self.glossary_name = "PUBG"
        elif issue_key.upper().startswith("PAYDAY-"):
            steps_field = "customfield_10237"
            glossary_file = "heist_glossary.json"
            self.glossary_name = "HeistRoyale"
        else:
            # 기본값은 PBB (P2-*)
            steps_field = "customfield_10399"
            glossary_file = "pbb_glossary.json"
            self.glossary_name = "PBB(Project Black Budget)"

        # 용어집 로드
        self.glossary_terms = self._load_glossary_terms(glossary_file)

        if fields_to_translate is None:
            fields_to_translate = ['summary', 'description', steps_field]

        # 2. 이슈 조회
        print(f"📥 Fetching issue {issue_key}...")
        issue_fields = self.fetch_issue_fields(issue_key, fields_to_translate)

        if not issue_fields:
            print(f"⚠️ No fields found for {issue_key}")
            return {"results": {}, "update_payload": {}, "updated": False, "error": "no_fields"}

        # 3. 각 필드를 단일 배치로 번역 준비
        translation_results: dict[str, dict[str, str]] = {}
        jobs: dict[str, FieldTranslationJob] = {}
        all_chunks: list[TranslationChunk] = []

        for field in fields_to_translate:
            field_value = issue_fields.get(field)
            if not field_value:
                continue

            translation_results[field] = {
                "original": field_value,
                "translated": "",
            }

            print(f"🔄 Translating {field}...")
            skip_reason = None
            if field == "description" and self._is_description_already_translated(field_value):
                skip_reason = "already translated"
            elif field == "summary" and self._is_bilingual_summary(field_value):
                skip_reason = "already bilingual"
            elif field == steps_field and self._is_steps_bilingual(field_value):
                skip_reason = "already bilingual steps"

            if skip_reason:
                print(f"⏭️ Skipping {field} ({skip_reason})")
                continue

            job = self._plan_field_translation_job(field, field_value)
            if not job:
                continue

            jobs[field] = job
            all_chunks.extend(job.chunks)

        chunk_translations: dict[str, str] = {}
        if all_chunks:
            try:
                chunk_translations = self._call_openai_batch(all_chunks)
            except Exception as exc:
                print(f"⚠️ Batch translation failed, falling back to per-field mode: {exc}")
                chunk_translations = self._translate_chunks_individually(jobs)

        for field, job in jobs.items():
            assembled: list[str] = []
            for chunk in job.chunks:
                translated_raw = chunk_translations.get(chunk.id, "")
                restored = self.restore_attachments_markup(translated_raw, chunk.attachments)
                if job.mode == "description":
                    block = self._format_bilingual_block(
                        chunk.original_text,
                        restored,
                        header=chunk.header,
                    )
                    if block:
                        assembled.append(block)
                else:
                    if restored:
                        assembled.append(restored)
            if job.mode == "description":
                translated_value = "\n\n".join(filter(None, assembled)).strip()
            else:
                translated_value = "\n\n".join(filter(None, assembled))
            translation_results[field]["translated"] = translated_value

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

    default_url = "https://cloud.jira.krafton.com/browse/P2-70735"
    issue_url_input = input(f"번역할 Jira 티켓 URL을 입력하세요 (Enter for default: {default_url}): ").strip()
    if not issue_url_input:
        issue_url_input = default_url
        print(f"ℹ️ 기본 URL을 사용합니다: {issue_url_input}")

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
        fields_to_translate=None  # 자동 결정
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
    try:
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
        fields = event.get("fields_to_translate")  # None이면 자동 결정
        do_update = event.get("update", False)
        # [보안 수정] jira_url 오버라이드 제거
        # jira_url_override = event.get("jira_url")  <-- 삭제 권장
        
        # [수정] 환경 변수에서만 URL 로드
        JIRA_URL = os.getenv("JIRA_URL", "https://cloud.jira.krafton.com").rstrip("/")
        JIRA_EMAIL = os.getenv("JIRA_EMAIL")
        JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
        OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        
        # ... (검증 및 translator 초기화 로직 유지) ...
        
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
            fields_to_translate=fields,
            perform_update=do_update
        )

        response_data = {
            "issue_key": issue_key,
            **results_obj
        }

        # [수정] API Gateway Proxy Response Format 준수
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(response_data, ensure_ascii=False)
        }

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        # 에러 발생 시에도 정형화된 JSON 응답 반환
        return {
            "statusCode": 500, # 상황에 따라 400 등 분기 가능
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "error": str(e),
                "type": type(e).__name__
            }, ensure_ascii=False)
        }
