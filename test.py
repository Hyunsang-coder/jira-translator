import os
import re
from collections.abc import Sequence
from typing import Optional
from urllib.parse import urlparse

import requests
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

class JiraTicketTranslator:
    """Jira 티켓을 번역하면서 이미지/첨부파일 마크업을 유지하는 클래스"""
    
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
        
        # LangChain LLM 초기화
        self.llm = ChatOpenAI(
            model="gpt-4o",
            api_key=openai_api_key,
            temperature=0
        )
        
        # 번역 프롬프트 템플릿
        self.translation_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a professional translator. Translate the following text to {target_language}. "
                      "Preserve any Jira markup syntax like *bold*, _italic_, {{code}}, etc. "
                      "Only translate the actual text content, not the markup symbols."),
            ("user", "{text}")
        ])
        self.translation_chain = self.translation_prompt | self.llm | StrOutputParser()
    
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
        
        result = self.translation_chain.invoke({
            "text": text,
            "target_language": target_language
        })
        
        return result
    
    def translate_field(self, field_value: str, target_language: str = "Korean") -> str:
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
        
        # 1. 이미지/첨부파일 마크업 추출
        attachments, clean_text = self.extract_attachments_markup(field_value)
        
        # 2. 텍스트만 번역
        translated_text = self.translate_text(clean_text, target_language)
        
        # 3. 마크업 복원
        final_text = self.restore_attachments_markup(translated_text, attachments)
        
        return final_text
    
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
        
        response = self.session.get(endpoint, params=params)
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
    
    def translate_issue(
        self, 
        issue_key: str, 
        target_language: str = "Korean",
        fields_to_translate: Optional[list[str]] = None
    ) -> dict:
        """
        Jira 이슈를 번역
        
        Args:
            issue_key: Jira 이슈 키 (예: 'BUG-123')
            target_language: 목표 언어
            fields_to_translate: 번역할 필드 리스트 (기본: ['summary', 'description'])
            
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
            return {}
        
        # 2. 각 필드 번역
        translation_results = {}
        
        for field in fields_to_translate:
            field_value = issue_fields.get(field)
            
            if field_value:
                print(f"🔄 Translating {field}...")
                translated_value = self.translate_field(field_value, target_language)
                translation_results[field] = {
                    'original': field_value,
                    'translated': translated_value
                }

        return translation_results


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
    
    results = translator.translate_issue(
        issue_key=issue_key,
        target_language="Korean",
        fields_to_translate=['summary', 'description', 'customfield_10399']
    )
    
    # 결과 출력
    if not results:
        print("⚠️ 번역 결과가 없습니다.")
    else:
        print("\n📊 Translation Results:")
        print("="*50)
        for field, content in results.items():
            print(f"\n{field.upper()}:")
            print("Original:")
            print(content['original'])
            print("\nTranslated:")
            print(content['translated'])