import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Optional, TypedDict, Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END


class JiraTranslationState(TypedDict, total=False):
    """LangGraph 상태 정의

    각 노드는 이 상태를 입력/출력으로 사용하며, 필요한 필드만 부분 업데이트합니다.
    """

    # 입력 파라미터
    issue_key: str
    jira_url: str
    fields_to_translate: list[str]
    target_language: Optional[str]
    perform_update: bool

    # 중간/최종 결과
    fetched_fields: dict[str, str]
    translation_results: dict[str, dict[str, str]]
    update_payload: dict[str, str]
    updated: bool
    error: Optional[str]


class JiraTextTranslator:
    """텍스트/마크업 처리 및 번역 관련 순수 기능 모음"""

    DESCRIPTION_SECTIONS = ("Observed", "Expected Result", "Note")

    def __init__(self, openai_api_key: str, model_name: Optional[str] = None) -> None:
        self.llm = ChatOpenAI(
            model=model_name or os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            api_key=openai_api_key,
        )

        # 프로젝트 용어집 로드 (glossary.json)
        self.glossary_text = self._load_glossary_text()

        self.translation_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a professional translator at PUBG. "
                    "Translate the following text to {target_language}. "
                    "Preserve any Jira markup syntax like *bold*, _italic_, {{code}}, etc. "
                    "Since the text is a Jira ticket, the text should be concise and to the point. "
                    "Keep English pronouns and terms in English. "
                    "Use the following PBB glossary for PBB-specific terms:\n"
                    "{glossary}\n"
                    "Only translate the actual text content, not the markup symbols.",
                ),
                ("user", "{text}"),
            ]
        )
        self.translation_chain = self.translation_prompt | self.llm | StrOutputParser()

    def _load_glossary_text(self) -> str:
        """pbb_glossary.json을 읽어 LLM에 넣기 좋은 문자열로 변환.

        pbb_glossary.json 구조:
        {
            "description": "...",
            "terms": {
                "facility": "퍼실리티",
                ...
            }
        }
        """
        try:
            base_dir = Path(__file__).resolve().parent
            glossary_path = base_dir / "pbb_glossary.json"
            if not glossary_path.exists():
                return ""

            with glossary_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            terms = data.get("terms") or {}
            if not isinstance(terms, dict) or not terms:
                return ""

            lines: list[str] = []
            for src, tgt in terms.items():
                lines.append(f"- {src} -> {tgt}")
            return "\n".join(lines)
        except Exception:
            # 용어집이 없어도 번역은 동작해야 하므로 조용히 무시
            return ""

    # --- 마크업 처리 ---

    def extract_attachments_markup(self, text: str) -> tuple[list[str], str]:
        """Jira 마크업에서 이미지/첨부파일을 추출하고 플레이스홀더로 대체"""
        if not text:
            return [], ""

        attachments: list[str] = []

        image_pattern = r"!([^!]+?)(?:\|[^!]*)?!"
        attachment_pattern = r"\[\^([^\]]+?)\]"

        def replace_image(match: re.Match[str]) -> str:
            attachments.append(match.group(0))
            return f"__IMAGE_PLACEHOLDER_{len(attachments)-1}__"

        def replace_attachment(match: re.Match[str]) -> str:
            attachments.append(match.group(0))
            return f"__ATTACHMENT_PLACEHOLDER_{len(attachments)-1}__"

        text = re.sub(image_pattern, replace_image, text)
        text = re.sub(attachment_pattern, replace_attachment, text)

        return attachments, text

    def restore_attachments_markup(self, text: str, attachments: list[str]) -> str:
        """번역된 텍스트에 원본 마크업을 복원"""
        for i, attachment_markup in enumerate(attachments):
            text = text.replace(f"__IMAGE_PLACEHOLDER_{i}__", attachment_markup)
            text = text.replace(f"__ATTACHMENT_PLACEHOLDER_{i}__", attachment_markup)
        return text

    # --- 언어 감지/번역 ---

    def translate_text(self, text: str, target_language: str = "Korean") -> str:
        if not text or not text.strip():
            return text
        result = self.translation_chain.invoke(
            {
                "text": text,
                "target_language": target_language,
                "glossary": self.glossary_text,
            }
        )
        return (result or "").strip()

    def translate_field(self, field_value: str, target_language: Optional[str] = None) -> str:
        if not field_value:
            return field_value

        target = target_language or self.determine_target_language(field_value)
        attachments, clean_text = self.extract_attachments_markup(field_value)
        translated_text = self.translate_text(clean_text, target)
        return self.restore_attachments_markup(translated_text, attachments)

    def translate_description_field(
        self, field_value: str, target_language: Optional[str] = None
    ) -> str:
        sections = self._extract_description_sections(field_value)
        target = target_language or self.determine_target_language(field_value)

        if not sections:
            translated = self.translate_field(field_value, target)
            return self._format_bilingual_block(field_value, translated)

        formatted_sections: list[str] = []
        for header, content in sections:
            translated_section = self.translate_field(content, target)
            formatted_sections.append(
                self._format_bilingual_block(content, translated_section, header=header)
            )

        return "\n\n".join(filter(None, formatted_sections)).strip()

    def determine_target_language(self, text: str) -> str:
        lang = self._detect_text_language(text)
        return {"ko": "English", "en": "Korean"}.get(lang, "Korean")

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

    # --- 포맷팅/섹션 처리 ---

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

    def _format_bilingual_block(
        self, original: str, translated: str, header: Optional[str] = None
    ) -> str:
        original = (original or "").strip()
        translated = (translated or "").strip()
        lines: list[str] = []
        if header:
            lines.append(header)

        if not original:
            if translated:
                lines.append(f"{{color:#4c9aff}}{translated}{{color}}")
            return "\n".join(lines).strip()

        translation_lines = [
            line for line in translated.splitlines() if line.strip()
        ]
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
                if self._is_media_line(translated_line) or self._is_header_line(
                    translated_line
                ):
                    continue
                formatted = self._match_translated_line_format(line, translated_line)
                if formatted:
                    lines.append(formatted)

        return "\n".join(lines).strip()

    def _match_translated_line_format(
        self, original_line: str, translated_line: str
    ) -> str:
        translation = translated_line.strip()
        if not translation:
            return ""

        bullet_match = re.match(r"(\s*(?:[-*#]+|\d+\.)\s+)(.*)", original_line)
        if bullet_match:
            prefix = bullet_match.group(1)
            cleaned_translation = self._strip_bullet_prefix(translation)
            return f"{prefix}{{color:#4c9aff}}{cleaned_translation}{{color}}"
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
        cleaned = re.sub(r"\{color:[^}]+\}|\{color\}", "", line or "").strip()
        return self._match_section_header(cleaned) is not None

    def _extract_description_sections(self, text: str) -> list[tuple[str, str]]:
        if not text:
            return []

        sections: list[tuple[str, str]] = []
        current_header: Optional[str] = None
        buffer: list[str] = []

        def flush() -> None:
            nonlocal sections, current_header, buffer
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
        stripped = line.strip().rstrip(":")
        stripped = re.sub(r"\{color:[^}]+\}|\{color\}", "", stripped)
        stripped = stripped.strip("*_ ").lower()
        for header in self.DESCRIPTION_SECTIONS:
            normalized = header.lower()
            if stripped == normalized or stripped.startswith(f"{normalized} "):
                return header
        return None

    # --- Jira 필드 정규화 ---

    def normalize_field_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            return self._flatten_adf_node(value).strip()
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            flattened = "\n".join(
                filter(None, (self.normalize_field_value(item) for item in value))
            )
            return flattened.strip()
        return str(value).strip()

    def _flatten_adf_node(self, node: Any) -> str:
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


class JiraTranslatorWorkflow:
    """LangGraph 기반 Jira 번역 워크플로우

    노드:
      - fetch_issue_fields
      - determine_target_language
      - translate_fields
      - build_update_payload
      - update_issue (옵션)
    """

    def __init__(self, jira_url: str, email: str, api_token: str, openai_api_key: str):
        self.jira_url = jira_url.rstrip("/")
        self.email = email
        self.api_token = api_token

        self.session = requests.Session()
        self.session.auth = (email, api_token)

        self.text = JiraTextTranslator(openai_api_key=openai_api_key)
        self.app = self._build_graph()

    # --- LangGraph 그래프 정의 ---

    def _build_graph(self):
        graph = StateGraph(JiraTranslationState)

        graph.add_node("fetch_issue_fields", self._node_fetch_issue_fields)
        graph.add_node(
            "determine_target_language", self._node_determine_target_language
        )
        graph.add_node("translate_fields", self._node_translate_fields)
        graph.add_node("build_update_payload", self._node_build_update_payload)
        graph.add_node("update_issue", self._node_update_issue)

        graph.set_entry_point("fetch_issue_fields")
        graph.add_edge("fetch_issue_fields", "determine_target_language")
        graph.add_edge("determine_target_language", "translate_fields")
        graph.add_edge("translate_fields", "build_update_payload")

        graph.add_conditional_edges(
            "build_update_payload",
            self._route_update_issue,
            {"update": "update_issue", "skip": END},
        )
        graph.add_edge("update_issue", END)

        return graph.compile()

    # --- 퍼블릭 실행 API ---

    def run(
        self,
        issue_key: str,
        target_language: Optional[str] = None,
        fields_to_translate: Optional[list[str]] = None,
        perform_update: bool = False,
    ) -> JiraTranslationState:
        initial_state: JiraTranslationState = {
            "issue_key": issue_key,
            "jira_url": self.jira_url,
            "fields_to_translate": fields_to_translate
            or ["summary", "description", "customfield_10399"],
            "target_language": target_language,
            "perform_update": perform_update,
            "updated": False,
            "error": None,
        }
        return self.app.invoke(initial_state)

    # --- 그래프 노드 구현 ---

    def _node_fetch_issue_fields(
        self, state: JiraTranslationState
    ) -> JiraTranslationState:
        issue_key = state["issue_key"]
        fields = state.get("fields_to_translate") or [
            "summary",
            "description",
            "customfield_10399",
        ]

        endpoint = f"{self.jira_url}/rest/api/2/issue/{issue_key}"
        params = {"fields": ",".join(fields), "expand": "renderedFields"}

        response = self.session.get(endpoint, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        fetched_fields: dict[str, str] = {}
        raw_fields = data.get("fields", {}) or {}
        rendered_fields = data.get("renderedFields", {}) or {}

        for field in fields:
            raw_value = raw_fields.get(field)
            normalized = self.text.normalize_field_value(raw_value)

            if not normalized:
                rendered_value = rendered_fields.get(field)
                normalized = self.text.normalize_field_value(rendered_value)

            if normalized:
                fetched_fields[field] = normalized

        return {"fetched_fields": fetched_fields}

    def _node_determine_target_language(
        self, state: JiraTranslationState
    ) -> JiraTranslationState:
        if state.get("target_language"):
            return {}

        fetched = state.get("fetched_fields") or {}
        summary_text = fetched.get("summary", "")
        if summary_text:
            resolved = self.text.determine_target_language(summary_text)
        else:
            resolved = "Korean"
        return {"target_language": resolved}

    def _node_translate_fields(self, state: JiraTranslationState) -> JiraTranslationState:
        fetched = state.get("fetched_fields") or {}
        fields = state.get("fields_to_translate") or list(fetched.keys())
        target_language = state.get("target_language") or "Korean"

        translation_results: dict[str, dict[str, str]] = {}

        for field in fields:
            field_value = fetched.get(field)
            if not field_value:
                continue

            if field == "description":
                translated_value = self.text.translate_description_field(
                    field_value, target_language
                )
            else:
                translated_value = self.text.translate_field(field_value, target_language)

            translation_results[field] = {
                "original": field_value,
                "translated": translated_value,
            }

        return {"translation_results": translation_results}

    def _node_build_update_payload(
        self, state: JiraTranslationState
    ) -> JiraTranslationState:
        results = state.get("translation_results") or {}
        payload: dict[str, str] = {}

        for field, content in results.items():
            original = content.get("original", "")
            translated = content.get("translated", "")
            if field == "summary":
                formatted = self.text.format_summary_value(original, translated)
            elif field == "description":
                formatted = translated
            elif field == "customfield_10399":
                formatted = self.text.format_steps_value(original, translated)
            else:
                formatted = translated or original

            if formatted:
                payload[field] = formatted

        return {"update_payload": payload}

    def _route_update_issue(self, state: JiraTranslationState) -> str:
        if state.get("perform_update") and state.get("update_payload"):
            return "update"
        return "skip"

    def _node_update_issue(self, state: JiraTranslationState) -> JiraTranslationState:
        payload = state.get("update_payload") or {}
        if not payload:
            return {"updated": False}

        issue_key = state["issue_key"]
        endpoint = f"{self.jira_url}/rest/api/2/issue/{issue_key}"

        try:
            response = self.session.put(
                endpoint,
                json={"fields": payload},
                timeout=15,
            )
            response.raise_for_status()
            return {"updated": True, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {"updated": False, "error": str(exc)}


def parse_issue_url(issue_url: str) -> tuple[str, str]:
    parsed = urlparse(issue_url.strip())

    if not parsed.scheme or not parsed.netloc:
        raise ValueError("유효한 Jira 이슈 URL을 입력해주세요.")

    base_url = f"{parsed.scheme}://{parsed.netloc}"
    path_segments = [segment for segment in parsed.path.split("/") if segment]

    issue_key: Optional[str] = None
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


def run_workflow_from_cli() -> None:
    """기존 `jira_trans.py`와 유사한 CLI 진입점 (LangGraph 기반)"""

    load_dotenv()
    jira_url = os.getenv("JIRA_URL", "https://cloud.jira.krafton.com").rstrip("/")
    jira_email = os.getenv("JIRA_EMAIL")
    jira_api_token = os.getenv("JIRA_API_TOKEN")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if not all([jira_email, jira_api_token, openai_api_key]):
        raise EnvironmentError(
            "JIRA_EMAIL, JIRA_API_TOKEN, OPENAI_API_KEY 환경 변수를 모두 설정해주세요."
        )

    issue_url_input = input("번역할 Jira 티켓 URL을 입력하세요: ").strip()
    if not issue_url_input:
        raise ValueError("Jira 티켓 URL은 필수 입력값입니다.")

    input_base_url, issue_key = parse_issue_url(issue_url_input)
    if jira_url and jira_url.lower() != input_base_url.lower():
        print(
            f"ℹ️ 입력된 URL의 Jira 서버({input_base_url})가 설정된 기본 URL({jira_url})과 다릅니다. 기본 URL을 사용합니다."
        )

    workflow = JiraTranslatorWorkflow(
        jira_url=jira_url or input_base_url,
        email=jira_email,
        api_token=jira_api_token,
        openai_api_key=openai_api_key,
    )

    state = workflow.run(
        issue_key=issue_key,
        target_language=None,
        fields_to_translate=["summary", "description", "customfield_10399"],
        perform_update=False,
    )

    results = state.get("translation_results") or {}
    if not results:
        print("⚠️ 번역 결과가 없습니다.")
        return

    print("\n📊 Translation Results:")
    print("=" * 50)
    for field, content in results.items():
        print(f"\n{field.upper()}:")
        print("Original:")
        print(content.get("original", ""))
        print("\nTranslated:")
        print(content.get("translated", ""))

    update_payload = state.get("update_payload") or {}
    if not update_payload:
        print("\nℹ️ 업데이트할 필드가 없습니다.")
        return

    confirm = input("\nJira 이슈를 업데이트할까요? (y/n): ").strip().lower()
    if confirm != "y":
        print("ℹ️ 업데이트를 취소했습니다.")
        return

    # 업데이트 실행용으로 한 번 더 그래프 실행 (perform_update=True)
    state_with_update = workflow.run(
        issue_key=issue_key,
        target_language=state.get("target_language"),
        fields_to_translate=["summary", "description", "customfield_10399"],
        perform_update=True,
    )

    if state_with_update.get("updated"):
        print("✅ Jira 이슈가 업데이트되었습니다.")
    else:
        print(f"❌ Jira 업데이트 실패: {state_with_update.get('error')}")


def handler(event, context):  # noqa: D401, ANN001, ANN201
    """AWS Lambda / Function 핸들러 (API Gateway 호환)

    event 예시(JSON):
      {
        "issue_key": "BUG-123",        # 또는 issue_url
        "issue_url": "https://...",    # 선택
        "target_language": null,        # 없으면 자동 판별
        "fields_to_translate": ["summary", "description", "customfield_10399"],
        "update": true,                 # Jira 필드 업데이트 여부
        "jira_url": "https://..."      # 선택: JIRA_URL override
      }
    """

    event = event or {}

    issue_key = event.get("issue_key")
    issue_url = event.get("issue_url")
    target_language = event.get("target_language")
    fields = event.get(
        "fields_to_translate", ["summary", "description", "customfield_10399"]
    )
    do_update = bool(event.get("update", False))
    jira_url_override = event.get("jira_url")

    jira_url = (jira_url_override or os.getenv("JIRA_URL", "https://cloud.jira.krafton.com")).rstrip(
        "/"
    )
    jira_email = os.getenv("JIRA_EMAIL")
    jira_api_token = os.getenv("JIRA_API_TOKEN")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if not all([jira_url, jira_email, jira_api_token, openai_api_key]):
        raise EnvironmentError(
            "JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, OPENAI_API_KEY 환경 변수가 필요합니다."
        )

    if not issue_key:
        if issue_url:
            _, issue_key = parse_issue_url(issue_url)
        else:
            raise ValueError("issue_key 또는 issue_url 중 하나는 필수입니다.")

    workflow = JiraTranslatorWorkflow(
        jira_url=jira_url,
        email=jira_email,
        api_token=jira_api_token,
        openai_api_key=openai_api_key,
    )

    state = workflow.run(
        issue_key=issue_key,
        target_language=target_language,
        fields_to_translate=fields,
        perform_update=do_update,
    )

    return {"issue_key": issue_key, **state}


if __name__ == "__main__":
    run_workflow_from_cli()
