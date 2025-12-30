import requests
from typing import Optional, Sequence
import urllib.parse
import re

class JiraClient:
    def __init__(self, jira_url: str, email: str, api_token: str):
        self.jira_url = jira_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (email, api_token)

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

