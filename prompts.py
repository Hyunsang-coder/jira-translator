from __future__ import annotations

import re
from collections.abc import Sequence


class PromptBuilder:
    """
    프롬프트 생성 로직을 JiraTicketTranslator에서 분리하기 위한 빌더.
    - 용어집 지시사항 생성
    - 언어/모드(단일/배치)에 따른 system message 구성
    """

    def __init__(self, glossary_terms: dict[str, str] | None = None, glossary_name: str = ""):
        self.glossary_terms: dict[str, str] = glossary_terms or {}
        self.glossary_name: str = glossary_name or ""

    def build_glossary_instruction(self, texts: Sequence[str]) -> str:
        """
        양방향 용어집 지원: 영어→한국어, 한국어→영어 모두 포함.
        단어 경계 매칭(\\b)을 사용하여 정확히 일치하는 용어만 찾습니다.
        예: 'key' 검색 시 'monkey'는 무시함.
        """
        terms = self.glossary_terms
        if not terms:
            return ""

        combined_text = "\n".join(texts).lower()
        glossary_lines: list[str] = []

        for eng, kor in terms.items():
            eng_pattern = r"\b" + re.escape((eng or "").lower()) + r"\b"
            if eng and re.search(eng_pattern, combined_text):
                glossary_lines.append(f"- {eng} <-> {kor}")
                continue

            if kor and (kor.lower() in combined_text):
                glossary_lines.append(f"- {kor} <-> {eng}")

        if not glossary_lines:
            return ""

        glossary_name_display = self.glossary_name or "Project"
        return (
            f"Use this {glossary_name_display} glossary for specific terms "
            "(bidirectional mapping):\n"
            + "\n".join(glossary_lines)
        )

    def build_system_message(
        self,
        *,
        detected_lang: str,
        glossary_instruction: str = "",
        batch: bool = False,
    ) -> str:
        """
        detected_lang:
          - "ko": 한국어 → 영어
          - 기타: 영어 → 한국어 (기존 로직과 동일하게 보수적으로 처리)
        """
        if detected_lang == "ko":
            if batch:
                system_msg = (
                    "You are a professional Korean to English translator. "
                    "Translate each provided Korean text to English. "
                    "The output MUST be 100% in English - do NOT leave any Korean words. "
                    "Preserve Jira markup (*bold*, _italic_, {{code}}, etc.), bullet indentation, "
                    "and placeholder tokens like __IMAGE_PLACEHOLDER__. "
                    "IMPORTANT: Keep the exact same number of lines as the source text. "
                    "Do not add commentary. " 
                    "Title rule: When translating titles/summaries, start with the symptom directly. "
                    "Do NOT start with 'There is an issue where...', 'An issue where...', or 'This is an issue...'. "
                    "Prefer patterns like 'Error occurs when ...', 'Crash when ...', 'UI does not ...', 'Cannot ...'. "
                    "Observation rule: When translating '확인하다' in reproduction steps, "
                    "prefer 'observe' or 'notice' over 'confirm' "
                    "(e.g., '에러가 발생하는 것을 확인' → 'Observe that the error occurs'). "
                )
            else:
                system_msg = (
                    "You are a professional Korean to English translator. "
                    "Translate the following Korean text to English. "
                    "The output MUST be 100% in English - do NOT leave any Korean words. "
                    "Preserve Jira markup (*bold*, _italic_, {{code}}, etc.)."
                    "Title rule: When translating titles/summaries, start with the symptom directly. "
                    "Do NOT start with 'There is an issue where...', 'An issue where...', or 'This is an issue...'. "
                    "Prefer patterns like 'Error occurs when ...', 'Crash when ...', 'UI does not ...', 'Cannot ...'. "
                    "Observation rule: When translating '확인하다' in reproduction steps, "
                    "prefer 'observe' or 'notice' over 'confirm' "
                    "(e.g., '에러가 발생하는 것을 확인' → 'Observe that the error occurs'). "
                )
        else:
            if batch:
                system_msg = (
                    "You are a professional English to Korean translator. "
                    "Translate each provided English text to Korean. "
                    "Keep proper nouns and game-specific terms in English. "
                    "Concise noun phrases for titles/summaries. "
                    "Preserve Jira markup (*bold*, _italic_, {{code}}, etc.), bullet indentation, "
                    "and placeholder tokens like __IMAGE_PLACEHOLDER__. "
                    "IMPORTANT: Keep the exact same number of lines as the source text. "
                    "Do not add commentary. "
                )
            else:
                system_msg = (
                    "You are a professional English to Korean translator. "
                    "Translate the following English text to Korean. "
                    "Keep proper nouns and game-specific terms in English. "
                    "favor noun phrases like '하이드아웃 진입', '이슈 확인'. "
                    "Preserve Jira markup (*bold*, _italic_, {{code}}, etc.)."
                )

        if glossary_instruction:
            system_msg = f"{system_msg} {glossary_instruction}"
            system_msg = (
                f"{system_msg}\n\n"
                "GLOSSARY NOTE RULE:\n"
                "- In glossary mappings, any text inside parentheses '(... )' is a note/description for disambiguation.\n"
                "- Use the note to choose the correct meaning, but DO NOT include the parentheses text in the translation output.\n"
                "- Example: 'Marksman <-> 저격수 (플레이어 롤/클래스)' => output '저격수' (omit the note).\n"
            )

        return system_msg


