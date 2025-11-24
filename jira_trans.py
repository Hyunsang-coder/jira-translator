import os
import json
import base64
import requests
from typing import Optional


class JiraTicketUpdater:
    """번역된 내용을 받아서 Jira 티켓을 업데이트하는 클래스"""

    def __init__(self, jira_url: str, email: str, api_token: str):
        self.jira_url = jira_url.rstrip("/")
        self.email = email
        self.api_token = api_token
        self.session = requests.Session()
        self.session.auth = (email, api_token)

    def format_summary_value(self, original: str, translated: str) -> str:
        """Summary 포맷: 원문 / 번역문"""
        original = (original or "").strip()
        translated = (translated or "").strip()
        if not original:
            return translated
        if not translated:
            return original
        return f"{original} / {translated}"

    def format_description_value(self, original: str, translated: str) -> str:
        """
        Description 포맷: 섹션별로 원문 라인 + 파란색 번역 라인
        
        예:
        Observed/관찰 결과
        After placing the Sim Station...
        {color:#4c9aff}Sim Station을 배치한 후...{color}
        
        For example, if the Client enters...
        {color:#4c9aff}예를 들어, 클라이언트가...{color}
        """
        original = (original or "").strip()
        translated = (translated or "").strip()
        
        if not original:
            return f"{{color:#4c9aff}}{translated}{{color}}" if translated else ""
        if not translated:
            return original
        
        # 원문과 번역문을 라인별로 분리
        original_lines = original.splitlines()
        translated_lines = translated.splitlines()
        
        result_lines = []
        trans_index = 0
        
        for orig_line in original_lines:
            # 원문 라인 추가
            result_lines.append(orig_line)
            
            stripped = orig_line.strip()
            
            # 빈 줄, 미디어 라인, 헤더 라인은 번역 스킵
            if not stripped or self._is_media_line(stripped) or self._is_section_header(stripped):
                continue
            
            # 대응하는 번역 라인 찾기
            if trans_index < len(translated_lines):
                trans_line = translated_lines[trans_index].strip()
                trans_index += 1
                
                # 번역 라인도 미디어나 헤더면 스킵
                if trans_line and not self._is_media_line(trans_line) and not self._is_section_header(trans_line):
                    result_lines.append(f"{{color:#4c9aff}}{trans_line}{{color}}")
        
        return "\n".join(result_lines)

    def format_steps_value(self, original: str, translated: str) -> str:
        """Steps to Reproduce 포맷: 원문 블록\n\n번역 블록"""
        original = (original or "").strip()
        translated = (translated or "").strip()
        if original and translated:
            return f"{original}\n\n{translated}"
        return original or translated

    def _is_media_line(self, line: str) -> bool:
        """이미지나 첨부파일 라인인지 확인"""
        stripped = line.strip()
        return stripped.startswith("!") or stripped.startswith("[^") or stripped.startswith("[")

    def _is_section_header(self, line: str) -> bool:
        """섹션 헤더인지 확인 (Observed/관찰 결과, Expected/기대 결과 등)"""
        stripped = line.strip().lower()
        headers = [
            "observed", "관찰", 
            "expected", "기대", 
            "note", "참고",
            "video", "영상",
            "etc", "기타"
        ]
        return any(header in stripped for header in headers)

    def build_field_update_payload(self, translations: dict) -> dict:
        """번역 결과를 Jira 업데이트 페이로드로 변환"""
        payload = {}
        
        for field, content in translations.items():
            original = content.get('original', '')
            translated = content.get('translated', '')
            
            if field == "summary":
                formatted = self.format_summary_value(original, translated)
            elif field == "description":
                formatted = self.format_description_value(original, translated)
            elif field == "customfield_10399":  # Steps to Reproduce
                formatted = self.format_steps_value(original, translated)
            else:
                formatted = translated or original
            
            if formatted:
                payload[field] = formatted
        
        return payload

    def update_issue_fields(self, issue_key: str, field_payload: dict) -> None:
        """Jira 티켓 필드 업데이트"""
        if not field_payload:
            print("ℹ️ 업데이트할 필드가 없습니다.")
            return
        
        endpoint = f"{self.jira_url}/rest/api/2/issue/{issue_key}"
        response = self.session.put(
            endpoint, 
            json={"fields": field_payload}, 
            timeout=30
        )
        response.raise_for_status()
        print(f"✅ Jira 이슈 {issue_key}가 업데이트되었습니다.")


def handler(event, context):
    """Lambda 핸들러"""
    
    # 환경 변수 로드
    JIRA_URL = os.getenv("JIRA_URL", "https://cloud.jira.krafton.com")
    JIRA_EMAIL = os.getenv("JIRA_EMAIL")
    JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
    
    if not all([JIRA_EMAIL, JIRA_API_TOKEN]):
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "success": False,
                "error": "Missing JIRA_EMAIL or JIRA_API_TOKEN environment variables"
            })
        }
    
    # Body 파싱
    try:
        body_raw = event.get("body", "{}")
        
        # Base64 인코딩 확인
        if event.get("isBase64Encoded"):
            body_raw = base64.b64decode(body_raw).decode("utf-8")
        
        # JSON 파싱
        body = json.loads(body_raw)
        
    except json.JSONDecodeError as e:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "success": False,
                "error": f"Invalid JSON in body: {str(e)}"
            })
        }
    except Exception as e:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "success": False,
                "error": f"Failed to parse body: {str(e)}"
            })
        }
    
    # 파라미터 추출
    issue_key = body.get("issue_key")
    translations = body.get("translations")
    
    if not issue_key:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "success": False,
                "error": "Missing issue_key in request body"
            })
        }
    
    if not translations or not isinstance(translations, dict):
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "success": False,
                "error": "Missing or invalid translations in request body"
            })
        }
    
    # Jira 업데이트 실행
    try:
        updater = JiraTicketUpdater(
            jira_url=JIRA_URL,
            email=JIRA_EMAIL,
            api_token=JIRA_API_TOKEN
        )
        
        payload = updater.build_field_update_payload(translations)
        updater.update_issue_fields(issue_key, payload)
        
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "success": True,
                "message": f"Successfully updated {issue_key}",
                "issue_key": issue_key,
                "updated_fields": list(payload.keys())
            }, ensure_ascii=False)
        }
        
    except requests.HTTPError as e:
        error_detail = ""
        try:
            error_detail = e.response.text
        except:
            pass
            
        return {
            "statusCode": e.response.status_code if hasattr(e, 'response') else 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "success": False,
                "error": f"Jira API error: {str(e)}",
                "details": error_detail
            }, ensure_ascii=False)
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "success": False,
                "error": f"Internal error: {str(e)}"
            }, ensure_ascii=False)
        }