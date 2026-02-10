import requests
from typing import Optional, Sequence
import urllib.parse
import re

# Steps 필드 후보 ID 목록 (알려진 커스텀 필드, 우선순위 순)
STEPS_FIELD_CANDIDATES = ["customfield_10237", "customfield_10399"]


class JiraClient:
    def __init__(self, jira_url: str, email: str, api_token: str):
        self.jira_url = jira_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (email, api_token)
        self._steps_field_cache: dict[str, Optional[str]] = {}

    def detect_steps_field(self, project_key: str) -> Optional[str]:
        """createmeta API로 프로젝트의 steps 필드 자동 탐지.

        탐지 우선순위:
        1. STEPS_FIELD_CANDIDATES에 있는 알려진 필드 ID 매칭
        2. 필드 이름에 'step'과 'reproduce' 모두 포함된 커스텀필드 (대소문자 무시)

        API 실패 시 None을 반환하며 예외를 발생시키지 않는다.
        결과는 프로젝트 키별로 캐시된다.
        """
        if project_key in self._steps_field_cache:
            return self._steps_field_cache[project_key]

        try:
            endpoint = f"{self.jira_url}/rest/api/2/issue/createmeta"
            params = {
                "projectKeys": project_key,
                "expand": "projects.issuetypes.fields",
                "issuetypeNames": "버그,Bug",
            }
            response = self.session.get(endpoint, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            for proj in data.get("projects", []):
                for issuetype in proj.get("issuetypes", []):
                    fields = issuetype.get("fields", {})
                    # 1순위: 알려진 후보 ID 매칭
                    for candidate in STEPS_FIELD_CANDIDATES:
                        if candidate in fields:
                            self._steps_field_cache[project_key] = candidate
                            return candidate
                    # 2순위: 필드 이름 기반 탐지
                    for field_id, field_meta in fields.items():
                        name = (field_meta.get("name") or "").lower()
                        if "step" in name and "reproduce" in name:
                            self._steps_field_cache[project_key] = field_id
                            return field_id
        except Exception as exc:
            print(f"⚠️ Steps field detection failed for {project_key}: {exc}")

        self._steps_field_cache[project_key] = None
        return None

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

def parse_issue_url(issue_url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(issue_url.strip())

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

