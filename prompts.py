from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Optional

from models import GlossaryEntry


class PromptBuilder:
    """
    프롬프트 생성 로직을 JiraTicketTranslator에서 분리하기 위한 빌더.
    - 용어집 지시사항 생성
    - 언어/모드(단일/배치)에 따른 system message 구성
    """

    def __init__(
        self,
        glossary_terms: dict[str, str] | None = None,
        glossary_name: str = "",
        glossary_entries: Sequence[GlossaryEntry] | None = None,
    ):
        self.glossary_terms: dict[str, str] = {}
        self.glossary_entries: list[GlossaryEntry] = []
        self.glossary_name: str = glossary_name or ""
        self.set_glossary(glossary_terms=glossary_terms, glossary_entries=glossary_entries)

    def set_glossary(
        self,
        *,
        glossary_terms: dict[str, str] | None = None,
        glossary_entries: Sequence[GlossaryEntry] | None = None,
    ) -> None:
        if glossary_entries is not None:
            entries = list(glossary_entries)
        else:
            entries = self.entries_from_terms(glossary_terms or {})
        self.glossary_entries = entries
        self.glossary_terms = self.terms_from_entries(entries)

    @staticmethod
    def _base_eng(eng: str) -> str:
        """충돌 방지용 suffix(__2, __3 ...) 제거 후 실제 영문 반환."""
        return re.sub(r"__\d+$", "", eng)

    @staticmethod
    def _split_ko_and_note(value: str) -> tuple[str, str]:
        cleaned = (value or "").strip()
        if not cleaned:
            return "", ""

        note_match = re.match(r"^(.*?)\s*\(note:\s*(.+)\)\s*$", cleaned, flags=re.IGNORECASE)
        if note_match:
            return note_match.group(1).strip(), note_match.group(2).strip()

        # Backward compatibility for legacy "ko (note)" style.
        legacy_match = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", cleaned)
        if legacy_match:
            base = legacy_match.group(1).strip()
            note = legacy_match.group(2).strip()
            if base and note:
                return base, note

        return cleaned, ""

    @classmethod
    def entries_from_terms(cls, terms: dict[str, str]) -> list[GlossaryEntry]:
        entries: list[GlossaryEntry] = []
        for raw_key, raw_value in terms.items():
            eng_key = str(raw_key or "").strip()
            eng = cls._base_eng(eng_key)
            ko, note = cls._split_ko_and_note(str(raw_value or ""))
            if not (eng and ko):
                continue
            entries.append(GlossaryEntry(id=eng_key, en=eng, ko=ko, note=note))
        return entries

    @staticmethod
    def terms_from_entries(entries: Sequence[GlossaryEntry]) -> dict[str, str]:
        terms: dict[str, str] = {}
        for entry in entries:
            if not (entry.id and entry.ko):
                continue
            terms[entry.id] = f"{entry.ko} ({entry.note})" if entry.note else entry.ko
        return terms

    @staticmethod
    def _contains_hangul(text: str) -> bool:
        return bool(re.search(r"[가-힣]", text))

    @staticmethod
    def _boundary_match(term: str, text_lower: str) -> bool:
        normalized = (term or "").strip().lower()
        if not normalized:
            return False
        pattern = rf"(?<!\w){re.escape(normalized)}(?!\w)"
        return re.search(pattern, text_lower) is not None

    @classmethod
    def _match_en_term(cls, term: str, text_lower: str) -> bool:
        return cls._boundary_match(term, text_lower)

    @classmethod
    def _match_ko_term(cls, term: str, text_lower: str) -> bool:
        normalized = (term or "").strip().lower()
        if not normalized:
            return False

        # 조사/활용 붙는 한국어 용어는 substring을 허용해 recall을 확보하고,
        # 아주 짧은 토큰은 과매칭 방지를 위해 경계 매칭 유지.
        if cls._contains_hangul(normalized) and len(normalized) > 2:
            return normalized in text_lower
        return cls._boundary_match(normalized, text_lower)

    def _entry_match_flags(self, entry: GlossaryEntry, text_lower: str) -> tuple[bool, bool]:
        en_terms = [entry.en, *entry.aliases_en]
        ko_terms = [entry.ko, *entry.aliases_ko]
        en_hit = any(self._match_en_term(term, text_lower) for term in en_terms if term)
        ko_hit = any(self._match_ko_term(term, text_lower) for term in ko_terms if term)
        return en_hit, ko_hit

    def get_candidate_entries(
        self,
        texts: Sequence[str],
        source_lang: Optional[str] = None,
    ) -> list[GlossaryEntry]:
        """
        1단계: string match로 용어집에서 후보 용어만 추출.
        source_lang:
          - "ko": ko -> en 번역 상황(한국어 원문 중심)
          - "en": en -> ko 번역 상황(영어 원문 중심)
          - None: 양방향 관대 매칭
        """
        if not self.glossary_entries:
            return []

        combined_text = "\n".join(texts).lower()
        source = (source_lang or "").strip().lower()
        candidates: list[GlossaryEntry] = []

        for entry in self.glossary_entries:
            en_hit, ko_hit = self._entry_match_flags(entry, combined_text)

            if source == "ko":
                matched = ko_hit or en_hit
            elif source == "en":
                matched = en_hit or ko_hit
            else:
                matched = en_hit or ko_hit

            if matched:
                candidates.append(entry)

        return candidates

    def get_candidate_terms(
        self,
        texts: Sequence[str],
        source_lang: Optional[str] = None,
    ) -> dict[str, str]:
        candidates = self.get_candidate_entries(texts, source_lang=source_lang)
        return self.terms_from_entries(candidates)

    def build_glossary_instruction(
        self,
        texts: Sequence[str],
        source_lang: Optional[str] = None,
        candidate_entries: Sequence[GlossaryEntry] | None = None,
    ) -> str:
        """
        양방향 용어집 지원: 영어->한국어, 한국어->영어 모두 포함.
        source_lang을 넘기면 해당 번역 방향 기준으로 라인 표기를 정렬.
        """
        candidates = list(candidate_entries) if candidate_entries is not None else self.get_candidate_entries(
            texts,
            source_lang=source_lang,
        )
        if not candidates:
            return ""

        source = (source_lang or "").strip().lower()
        glossary_lines: list[str] = []

        for entry in candidates:
            if source == "ko":
                left = f"ko: {entry.ko}"
                right = f"en: {entry.en}"
            else:
                left = f"en: {entry.en}"
                right = f"ko: {entry.ko}"

            note_part = f" | note: {entry.note}" if entry.note else ""
            glossary_lines.append(f"- {left} | {right}{note_part}")

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
          - "ko": 한국어 -> 영어
          - 기타: 영어 -> 한국어 (기존 로직과 동일하게 보수적으로 처리)
        """
        _markup_rule = (
            "Markup safety: NEVER move, drop, or duplicate placeholder tokens "
            "(e.g. __IMAGE_PLACEHOLDER__, __ATTACHMENT_0__) or Jira markup "
            "(*bold*, _italic_, {code}...{code}, [text|URL], !image!, [^attach]). "
            "Keep every token in its original relative position. "
        )

        if detected_lang == "ko":
            _ko_en_common = (
                "You are a professional translator for Jira QA tickets "
                "(bug reports, reproduction steps, expected/observed results). "
                "Prioritize natural-sounding English over literal translation - "
                "restructure sentences when needed, but preserve the original meaning. "
                "The output MUST be 100% in English - do NOT leave any Korean words. "
                "Rewrite rule: Korean passive/causal chains (되다, ~해서 ~이/가) should become "
                "active English constructions. "
                "e.g., '버튼을 클릭 시 에러가 발생되는 것을 확인' -> 'Clicking the button triggers an error' "
                "(not 'It is confirmed that an error occurs'). "
                "Title rule: Start with the symptom directly. "
                "Do NOT start with 'There is an issue where...', 'An issue where...', or 'This is an issue...'. "
                "Prefer patterns like 'Error occurs when ...', 'Crash when ...', 'UI does not ...', 'Cannot ...'. "
                "Observation rule: When translating '확인하다' in reproduction steps, "
                "prefer 'observe' or 'notice' over 'confirm' "
                "(e.g., '에러가 발생하는 것을 확인' -> 'Observe that the error occurs'). "
                + _markup_rule
            )
            if batch:
                system_msg = (
                    _ko_en_common
                    + "Field context: items may be 'summary' (one-line title), 'description' (detailed body), "
                    "or 'steps' (numbered reproduction steps). Use consistent terminology across all fields. "
                    "IMPORTANT: Keep the exact same number of lines as the source text. "
                    "Do not add commentary. "
                )
            else:
                system_msg = _ko_en_common
        else:
            _en_ko_common = (
                "You are a professional translator for Jira QA tickets "
                "(bug reports, reproduction steps, expected/observed results). "
                "Prioritize natural-sounding Korean over literal translation - "
                "restructure sentences when needed, but preserve the original meaning. "
                "Keep proper nouns and game-specific terms in English. "
                "Title rule: Use concise noun phrases matching the description tone. "
                "e.g., if description uses '발생합니다' style, title should read '오류 발생' "
                "(not '오류가 발생하는 중입니다'). "
                "Use formal '습니다' style for description body text "
                "(e.g., '발생합니다', '확인됩니다', '필요합니다'). "
                + _markup_rule
            )
            if batch:
                system_msg = (
                    _en_ko_common
                    + "Field context: items may be 'summary' (one-line title), 'description' (detailed body), "
                    "or 'steps' (numbered reproduction steps). Use consistent terminology across all fields. "
                    "IMPORTANT: Keep the exact same number of lines as the source text. "
                    "Do not add commentary. "
                )
            else:
                system_msg = _en_ko_common

        if glossary_instruction:
            system_msg = f"{system_msg} {glossary_instruction}"
            system_msg = (
                f"{system_msg}\n\n"
                "GLOSSARY NOTE RULE:\n"
                "- Glossary lines can include 'note: ...' for meaning disambiguation.\n"
                "- Use the note to pick the correct sense, but DO NOT output note text in translation.\n"
                "- Example: 'en: Marksman | ko: 저격수 | note: 플레이어 롤/클래스' => output '저격수'.\n"
            )

        return system_msg

