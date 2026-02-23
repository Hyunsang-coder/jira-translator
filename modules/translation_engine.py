import os
import json
from pathlib import Path
from typing import Optional, Sequence

from openai import OpenAI
from prompts import PromptBuilder
from models import (
    FieldTranslationJob,
    PYDANTIC_AVAILABLE,
    TranslationChunk,
    TranslationResponse,
    GlossarySelection,
    GLOSSARY_FILTER_THRESHOLD,
)
from modules import formatting, language

class TranslationEngine:
    def __init__(self, openai_api_key: str, model: str = "gpt-5.2"):
        self.openai = OpenAI(api_key=openai_api_key)
        self.openai_model = model or os.getenv("OPENAI_MODEL", "gpt-5.2")
        self.glossary_terms: dict[str, str] = {}
        self.glossary_name: str = ""
        self.prompt_builder = PromptBuilder(self.glossary_terms, self.glossary_name)

    def load_glossary(self, filename: str, glossary_name: str):
        self.glossary_terms = self._load_glossary_terms(filename)
        self.glossary_name = glossary_name
        self.prompt_builder.glossary_terms = self.glossary_terms
        self.prompt_builder.glossary_name = self.glossary_name

    def _load_glossary_terms(self, filename: str) -> dict[str, str]:
        """지정된 용어집 파일에서 terms 딕셔너리를 로드.

        두 가지 포맷 지원:
        - flat 포맷: {"terms": {"en": "ko", ...}}
        - 카테고리 포맷: {"glossary": {"Category": [{"ko": "...", "en": "...", "note": "..."}, ...]}}
        """
        try:
            base_dir = Path(__file__).resolve().parent.parent
            glossary_path = base_dir / "glossaries" / filename
            if not glossary_path.exists():
                return {}

            with glossary_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            # flat 포맷 우선
            terms = data.get("terms")
            if isinstance(terms, dict):
                return terms

            # 카테고리 포맷: {"glossary": {"Category": [{"ko": ..., "en": ..., "note": ...}]}}
            glossary = data.get("glossary")
            if isinstance(glossary, dict):
                flat: dict[str, str] = {}
                for entries in glossary.values():
                    if not isinstance(entries, list):
                        continue
                    for entry in entries:
                        en = (entry.get("en") or "").strip()
                        ko = (entry.get("ko") or "").strip()
                        note = (entry.get("note") or "").strip()
                        if not (en and ko):
                            continue
                        value = f"{ko} ({note})" if note else ko
                        # en 키 충돌 시 __2, __3 ... suffix로 모두 보존
                        if en not in flat:
                            flat[en] = value
                        else:
                            i = 2
                            while f"{en}__{i}" in flat:
                                i += 1
                            flat[f"{en}__{i}"] = value
                return flat

            return {}
        except Exception:
            return {}

    def _filter_glossary_by_llm(
        self,
        candidates: dict[str, str],
        texts: list[str],
    ) -> dict[str, str]:
        """2단계: LLM으로 실제 번역에 필요한 용어만 정제.

        candidates 수가 GLOSSARY_FILTER_THRESHOLD 이하면 스킵 (불필요한 API 호출 방지).
        반환: 필터링된 {eng: kor} dict
        """
        if not candidates or len(candidates) <= GLOSSARY_FILTER_THRESHOLD:
            return candidates

        combined_text = "\n".join(texts)
        term_list = "\n".join(f"{i}. {en} <-> {ko}" for i, (en, ko) in enumerate(candidates.items()))

        prompt = (
            "You are a glossary selector. Given the following text and a list of glossary terms, "
            "select ONLY the terms that are actually relevant to translating this specific text. "
            "Return a JSON object with a 'selected_keys' field containing the list of English terms to keep.\n\n"
            f"TEXT:\n{combined_text}\n\n"
            f"GLOSSARY TERMS (English <-> Korean):\n{term_list}"
        )

        try:
            if (
                PYDANTIC_AVAILABLE
                and hasattr(self.openai, "beta")
                and hasattr(self.openai.beta.chat.completions, "parse")
            ):
                completion = self.openai.beta.chat.completions.parse(
                    model=self.openai_model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format=GlossarySelection,
                )
                parsed = completion.choices[0].message.parsed
                selected_keys = getattr(parsed, "selected_keys", []) if parsed else []
            else:
                completion = self.openai.chat.completions.create(
                    model=self.openai_model,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = (completion.choices[0].message.content or "").strip()
                parsed_json = json.loads(content)
                selected_keys = parsed_json.get("selected_keys", [])

            return {k: v for k, v in candidates.items() if k in selected_keys}
        except Exception as e:
            print(f"⚠️ Glossary LLM filter failed, using all candidates: {e}")
            return candidates

    def _build_filtered_glossary_instruction(self, texts: list[str]) -> str:
        """후보 추출 + LLM 필터링 + 프롬프트 instruction 생성."""
        candidates = self.prompt_builder.get_candidate_terms(texts)
        filtered = self._filter_glossary_by_llm(candidates, texts)
        original_terms = self.prompt_builder.glossary_terms
        try:
            self.prompt_builder.glossary_terms = filtered
            return self.prompt_builder.build_glossary_instruction(texts)
        finally:
            self.prompt_builder.glossary_terms = original_terms

    def translate_text(self, text: str, target_language: Optional[str] = None) -> str:
        """
        텍스트를 번역 (마크업 제외)
        한글 텍스트는 영어로, 영어 텍스트는 한글로 자동 번역.
        """
        if not text or not text.strip():
            return text

        # 언어 감지(기본) + target_language(옵션)로 방향 강제 지원
        # Note: calling language.detect_text_language explicitly
        detected_lang = language.detect_text_language(text, extract_text_func=language.extract_detectable_text)
        forced = None
        if target_language:
            tl = str(target_language).strip().lower()
            if tl in {"english", "en"}:
                # output English => Korean -> English 프롬프트 선택
                forced = "ko"
            elif tl in {"korean", "ko"}:
                # output Korean => English -> Korean 프롬프트 선택
                forced = "en"
        direction_lang = forced or detected_lang

        glossary_instruction = self._build_filtered_glossary_instruction([text])
        system_msg = self.prompt_builder.build_system_message(
            detected_lang=direction_lang,
            glossary_instruction=glossary_instruction,
            batch=False,
        )

        response = self.openai.chat.completions.create(
            model=self.openai_model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": text},
            ],
        )
        return (response.choices[0].message.content or "").strip()

    def translate_field(self, field_value: str) -> str:
        """
        Jira 필드 값을 번역 (이미지/첨부파일 마크업 보존)
        """
        if not field_value:
            return field_value

        # 1. 이미지/첨부파일 마크업 추출
        attachments, clean_text = formatting.extract_attachments_markup(field_value)

        # 2. 텍스트만 번역
        translated_text = self.translate_text(clean_text)

        # 3. 마크업 복원
        final_text = formatting.restore_attachments_markup(translated_text, attachments)

        return final_text

    def translate_description_field(self, field_value: str) -> str:
        """한글→영어, 영어→한글 자동 번역."""
        sections = formatting.extract_description_sections(field_value)

        if not sections:
            translated = self.translate_field(field_value)
            return formatting.format_bilingual_block(field_value, translated)

        formatted_sections = []
        for header, content in sections:
            translated_section = self.translate_field(content)
            formatted_sections.append(
                formatting.format_bilingual_block(content, translated_section, header=header)
            )

        return "\n\n".join(filter(None, formatted_sections)).strip()

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
        translations: dict[str, str] = {}
        for chunk in chunk_list:
            translations[chunk.id] = self._translate_chunk_text(chunk, target_language)
        return translations

    def _translate_chunks_individually(
        self,
        jobs: dict[str, FieldTranslationJob],
        target_language: Optional[str] = None,
    ) -> dict[str, str]:
        per_chunk: dict[str, str] = {}
        for job in jobs.values():
            per_chunk.update(self._translate_chunk_list(job.chunks, target_language))
        return per_chunk

    def call_openai_batch(
        self,
        chunks: Sequence[TranslationChunk],
        target_language: Optional[str] = None,
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
                batch_result = self._call_openai_batch_once(chunks, target_language)
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
            fallback = self._translate_chunk_list(missing_chunks, target_language)
            batch_result.update(fallback)

        return batch_result

    def _call_openai_batch_once(
        self,
        chunks: Sequence[TranslationChunk],
        target_language: Optional[str] = None,
    ) -> dict[str, str]:
        """
        OpenAI Structured Outputs(beta.parse)를 사용하여
        JSON 파싱 에러를 원천 차단하고 안정성을 확보합니다.
        한글→영어, 영어→한글 자동 번역.
        """
        if not chunks:
            return {}

        # 번역 대상 청크만 필터링 (skip_translation=True인 청크 제외)
        translatable_chunks = [c for c in chunks if not c.skip_translation]
        if not translatable_chunks:
            return {}

        chunk_texts = [chunk.clean_text for chunk in translatable_chunks]
        glossary_instruction = self._build_filtered_glossary_instruction(chunk_texts)

        combined_text = "\n".join(chunk.clean_text for chunk in translatable_chunks)
        detected_lang = language.detect_text_language(combined_text, extract_text_func=language.extract_detectable_text)
        forced = None
        if target_language:
            tl = str(target_language).strip().lower()
            if tl in {"english", "en"}:
                forced = "ko"
            elif tl in {"korean", "ko"}:
                forced = "en"
        direction_lang = forced or detected_lang
        system_msg = self.prompt_builder.build_system_message(
            detected_lang=direction_lang,
            glossary_instruction=glossary_instruction,
            batch=True,
        )

        # Structured Outputs용 페이로드 구성 (field 정보 포함으로 일관성 향상)
        def _field_hint(chunk_id: str) -> str:
            if chunk_id == "summary":
                return "summary"
            if chunk_id.startswith("description"):
                return "description"
            if chunk_id.startswith("customfield_"):
                return "steps"
            return "other"

        payload = {
            "items": [
                {"id": chunk.id, "field": _field_hint(chunk.id), "text": chunk.clean_text}
                for chunk in translatable_chunks
            ]
        }
        user_msg = (
            f"Translate the 'text' fields in the following JSON data. "
            f"Keep 'id' and 'field' unchanged. Use 'field' as context hint for tone/style.\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

        # 1) Structured Outputs 경로 (Lambda/Linux 등 pydantic 사용 가능 환경)
        if (
            PYDANTIC_AVAILABLE
            and hasattr(self.openai, "beta")
            and hasattr(self.openai.beta, "chat")
            and hasattr(self.openai.beta.chat, "completions")
            and hasattr(self.openai.beta.chat.completions, "parse")
        ):
            completion = self.openai.beta.chat.completions.parse(
                model=self.openai_model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                response_format=TranslationResponse,
            )

            parsed_response = completion.choices[0].message.parsed
            if not parsed_response or not getattr(parsed_response, "translations", None):
                raise ValueError("Translation returned no structured data.")

            result: dict[str, str] = {}
            for item in parsed_response.translations:
                if item.id and item.translated:
                    result[item.id] = item.translated.strip()
            return result

        # 2) JSON 텍스트 응답 경로 (로컬/테스트 등)
        completion = self.openai.chat.completions.create(
            model=self.openai_model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        )

        content = completion.choices[0].message.content if completion and completion.choices else ""
        parsed = json.loads(content or "{}")
        items = (parsed or {}).get("translations") or []
        result: dict[str, str] = {}
        for item in items:
            item_id = (item or {}).get("id")
            translated = (item or {}).get("translated")
            if item_id and translated:
                result[str(item_id)] = str(translated).strip()
        return result

    def create_translation_chunk(
        self,
        *,
        chunk_id: str,
        field: str,
        original_text: str,
        header: Optional[str] = None,
    ) -> Optional[TranslationChunk]:
        if original_text is None:
            return None

        attachments, clean_text = formatting.extract_attachments_markup(original_text)
        return TranslationChunk(
            id=chunk_id,
            field=field,
            original_text=original_text,
            clean_text=clean_text,
            attachments=attachments,
            header=header,
        )

    def plan_field_translation_job(
        self,
        field: str,
        value: str,
    ) -> Optional[FieldTranslationJob]:
        if not value:
            return None

        if field == "summary":
            _, core = formatting.split_bracket_prefix(value)
            if not core.strip():
                return None
            chunk = self.create_translation_chunk(
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
            sections = formatting.extract_description_sections(value)
            chunks: list[TranslationChunk] = []
            if sections:
                for idx, (header, content) in enumerate(sections):
                    if not content.strip():
                        continue
                    
                    # 스킵 섹션 체크 (QA Environment 등)
                    skip_translation = formatting.should_skip_section_translation(header)
                    
                    chunk = self.create_translation_chunk(
                        chunk_id=f"{field}__section_{idx}",
                        field=field,
                        original_text=content,
                        header=header,
                    )
                    if chunk:
                        if skip_translation:
                            # 스킵 섹션은 번역하지 않고 원문 유지
                            chunk.skip_translation = True
                        chunks.append(chunk)
            else:
                chunk = self.create_translation_chunk(
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

        chunk = self.create_translation_chunk(
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

    def build_field_update_payload(self, translation_results: dict[str, dict[str, str]]) -> dict[str, str]:
        payload: dict[str, str] = {}
        for field, content in translation_results.items():
            original = content.get('original', '')
            translated = content.get('translated', '')

            if not translated:
                continue

            if field == "summary":
                formatted = formatting.format_summary_value(original, translated)
            elif field == "description":
                formatted = translated
            elif field.startswith("customfield_"): # Steps to Reproduce fields
                formatted = formatting.format_steps_value(original, translated)
            else:
                formatted = translated

            if formatted:
                payload[field] = formatted

        return payload
