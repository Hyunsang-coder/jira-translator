import re
from collections.abc import Sequence
from typing import Optional

from models import (
    FieldTranslationJob,
    TranslationChunk,
    TranslationItem,
    TranslationResponse,
)

# New modules
from modules import formatting, language
from modules.jira_client import JiraClient, parse_issue_url
from modules.translation_engine import TranslationEngine, run_batch_translation_orchestration

# Backward-compat re-exports (tests/external code may import these from jira_trans)
__all__ = [
    "JiraTicketTranslator",
    "TranslationChunk",
    "TranslationItem",
    "TranslationResponse",
    "FieldTranslationJob",
    "parse_issue_url",
]


class JiraTicketTranslator:
    """Jira 티켓을 번역하면서 이미지/첨부파일 마크업을 유지하는 클래스 (Facade)"""

    DESCRIPTION_SECTIONS = formatting.DESCRIPTION_SECTIONS

    def __init__(self, jira_url: str, email: str, api_token: str, openai_api_key: str):
        """
        Args:
            jira_url: Jira 인스턴스 URL 
            email: Jira 계정 이메일
            api_token: Jira API 토큰
            openai_api_key: OpenAI API 키
        """
        # Facade: Initialize components
        self.jira_client = JiraClient(jira_url, email, api_token)
        self.translation_engine = TranslationEngine(openai_api_key)
        
        # Initialize compatibility properties
        self.jira_url = self.jira_client.jira_url
        self.email = email
        self.api_token = api_token

    # --- Compatibility Properties ---
    @property
    def openai(self):
        return self.translation_engine.openai
    
    @openai.setter
    def openai(self, value):
        self.translation_engine.openai = value

    @property
    def session(self):
        return self.jira_client.session
    
    @session.setter
    def session(self, value):
        self.jira_client.session = value
    
    @property
    def openai_model(self):
        return self.translation_engine.openai_model
    
    @openai_model.setter
    def openai_model(self, value):
        self.translation_engine.openai_model = value
        
    @property
    def glossary_terms(self):
        return self.translation_engine.glossary_terms

    @glossary_terms.setter
    def glossary_terms(self, value):
        self.translation_engine.glossary_terms = value

    @property
    def glossary_name(self):
        return self.translation_engine.glossary_name

    @glossary_name.setter
    def glossary_name(self, value):
        self.translation_engine.glossary_name = value

    @property
    def prompt_builder(self):
        return self.translation_engine.prompt_builder

    @prompt_builder.setter
    def prompt_builder(self, value):
        self.translation_engine.prompt_builder = value

    # --- Delegated Methods (kept for test compatibility) ---

    def restore_attachments_markup(self, text: str, attachments: list[str]) -> str:
        return formatting.restore_attachments_markup(text, attachments)

    def translate_text(self, text: str, target_language: Optional[str] = None) -> str:
        return self.translation_engine.translate_text(text, target_language)

    def _translate_chunk_text(
        self,
        chunk: TranslationChunk,
        target_language: Optional[str] = None,
    ) -> str:
        return self.translate_text(chunk.clean_text, target_language=target_language) or ""

    def _translate_chunk_list(
        self,
        chunk_list: Sequence[TranslationChunk],
        target_language: Optional[str] = None,
    ) -> dict[str, str]:
        # Orchestrate locally to support mocking self._translate_chunk_text
        translations: dict[str, str] = {}
        for chunk in chunk_list:
            translations[chunk.id] = self._translate_chunk_text(chunk, target_language)
        return translations

    def _translate_chunks_individually(
        self,
        jobs: dict[str, FieldTranslationJob],
        target_language: Optional[str] = None,
    ) -> dict[str, str]:
        # Orchestrate locally to support mocking self._translate_chunk_list
        per_chunk: dict[str, str] = {}
        for job in jobs.values():
            per_chunk.update(self._translate_chunk_list(job.chunks, target_language))
        return per_chunk

    def _is_bilingual_summary(self, summary: str) -> bool:
        return language.is_bilingual_summary(summary, split_bracket_func=formatting.split_bracket_prefix)

    def _is_description_already_translated(self, value: str) -> bool:
        return language.is_description_already_translated(value)

    def _is_steps_bilingual(self, value: str) -> bool:
        return language.is_steps_bilingual(value)

    def format_summary_value(self, original: str, translated: str) -> str:
        return formatting.format_summary_value(original, translated)

    def build_field_update_payload(self, translation_results: dict[str, dict[str, str]]) -> dict[str, str]:
        return self.translation_engine.build_field_update_payload(translation_results)

    def _load_glossary_terms(self, filename: str) -> dict[str, str]:
        return self.translation_engine._load_glossary_terms(filename)

    def _call_openai_batch(
        self,
        chunks: Sequence[TranslationChunk],
        target_language: Optional[str] = None,
        retries: int = 2,
    ) -> dict[str, str]:
        return run_batch_translation_orchestration(
            chunks,
            target_language=target_language,
            retries=retries,
            batch_once=self._call_openai_batch_once,
            fallback_chunk_list=self._translate_chunk_list,
        )

    def _call_openai_batch_once(
        self,
        chunks: Sequence[TranslationChunk],
        target_language: Optional[str] = None,
    ) -> dict[str, str]:
        return self.translation_engine._call_openai_batch_once(chunks, target_language)

    def _plan_field_translation_job(
        self,
        field: str,
        value: str,
    ) -> Optional[FieldTranslationJob]:
        return self.translation_engine.plan_field_translation_job(field, value)

    def fetch_issue_fields(
        self,
        issue_key: str,
        fields_to_fetch: Optional[Sequence[str]] = None
    ) -> dict[str, str]:
        return self.jira_client.fetch_issue_fields(issue_key, fields_to_fetch)

    def update_issue_fields(self, issue_key: str, field_payload: dict[str, str]) -> None:
        self.jira_client.update_issue_fields(issue_key, field_payload)

    # Formatting wrappers (kept for test compatibility)
    def _match_translated_line_format(self, original_line: str, translated_line: str) -> str:
        return formatting.match_translated_line_format(original_line, translated_line)

    def _format_bilingual_block(self, original: str, translated: str, header: Optional[str] = None) -> str:
        return formatting.format_bilingual_block(original, translated, header)

    def _extract_description_sections(self, text: str) -> list[tuple[Optional[str], str]]:
        return formatting.extract_description_sections(text)

    @staticmethod
    def _determine_glossary(project_key: str, summary: str = "") -> tuple[str, str]:
        """프로젝트 키(+ 선택적 summary)로 glossary 파일명과 이름을 결정.

        PUBG-/PM- 티켓에서 summary에 '[BS]'가 있으면 BinarySpot glossary 사용.
        PUBGXBSG- 티켓은 무조건 Outbreak glossary 사용.
        PAYDAY- 티켓은 무조건 Heist Royale glossary 사용.
        """
        # PUBG/PM 계열: summary에 [BS] 또는 [BS_...] 태그 있으면 BinarySpot
        # [BS] 또는 [BS_xxx] 매칭, [BSG] 등 다른 태그는 제외
        if project_key in ("PUBG", "PM") and re.search(r"\[BS[\]_]", summary):
            return ("pubg_binaryspot_glossary.json", "PUBG BinarySpot")

        mapping = {
            "PUBG": ("pubg_glossary.json", "PUBG"),
            "PM": ("pubg_glossary.json", "PUBG"),
            "PUBGXBSG": ("pubg_outbreak_glossary.json", "PUBG Outbreak"),
            "PAYDAY": ("pubg_heist_glossary.json", "PUBG Heist Royale"),
        }
        return mapping.get(project_key, ("pbb_glossary.json", "PBB(Project Black Budget)"))

    @staticmethod
    def _fallback_steps_field(project_key: str) -> str:
        """detect_steps_field 실패 시 기존 하드코딩 기반 fallback."""
        if project_key in ("PUBG", "PM", "PUBGXBSG", "PAYDAY"):
            return "customfield_10237"
        return "customfield_10399"

    def translate_issue(
        self,
        issue_key: str,
        target_language: Optional[str] = None,
        fields_to_translate: Optional[list[str]] = None,
        perform_update: bool = False
    ) -> dict:
        """
        Jira 이슈를 번역 (한글→영어, 영어→한글 자동 번역)
        """
        # 1. 티켓 타입 판별 및 설정
        project_key = issue_key.split("-")[0].upper()
        # summary를 미리 fetch해서 [BS] 태그 기반 glossary 분기에 활용
        _summary_preview = ""
        if project_key in ("PUBG", "PM"):
            try:
                _preview = self.fetch_issue_fields(issue_key, ["summary"])
                _summary_preview = (_preview or {}).get("summary", "")
            except Exception:
                pass
        glossary_file, glossary_name = self._determine_glossary(project_key, _summary_preview)

        # Steps 필드 자동 탐지 (createmeta API) → 실패 시 하드코딩 fallback
        steps_field = self.jira_client.detect_steps_field(project_key)
        if steps_field is None:
            steps_field = self._fallback_steps_field(project_key)

        # 용어집 로드 (legacy + structured entry 동시 지원)
        self.translation_engine.load_glossary(glossary_file, glossary_name)

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
                chunk_translations = self._call_openai_batch(all_chunks, target_language)
            except Exception as exc:
                print(f"⚠️ Batch translation failed, falling back to per-field mode: {exc}")
                chunk_translations = self._translate_chunks_individually(jobs, target_language)

        for field, job in jobs.items():
            assembled: list[str] = []
            for chunk in job.chunks:
                translated_raw = chunk_translations.get(chunk.id, "")
                restored = self.restore_attachments_markup(translated_raw, chunk.attachments)
                if job.mode == "description":
                    # 스킵 섹션은 헤더 + 원문만 출력 (번역 없음)
                    if chunk.skip_translation:
                        block_parts = []
                        if chunk.header:
                            block_parts.append(chunk.header)
                        if chunk.original_text:
                            block_parts.append(chunk.original_text)
                        block = "\n".join(block_parts).strip()
                    else:
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
