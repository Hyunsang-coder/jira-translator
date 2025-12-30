from __future__ import annotations

import base64
import json
import os
import urllib.parse

from jira_trans import JiraTicketTranslator, parse_issue_url


def lambda_handler(event, context):
    """
    AWS Lambda 진입점.
    - API Gateway proxy event(body/json/form) 파싱
    - 환경 변수 기반으로 Jira/OpenAI 설정 로드
    - JiraTicketTranslator 호출 후 JSON 응답 반환
    """
    try:
        event = event or {}
        body_raw = event.get("body") or ""

        if event.get("isBase64Encoded"):
            if isinstance(body_raw, str):
                body_raw = body_raw.encode("utf-8", "ignore")
            body_raw = base64.b64decode(body_raw).decode("utf-8", "ignore")

        headers = event.get("headers") or {}
        content_type = headers.get("content-type") or headers.get("Content-Type") or ""
        content_type = content_type.lower() if isinstance(content_type, str) else ""

        parsed: dict = {}
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

        # 보안을 위해 외부 주입 차단: 환경 변수 기반으로만 구성
        jira_url = os.getenv("JIRA_URL", "https://cloud.jira.krafton.com").rstrip("/")
        jira_email = os.getenv("JIRA_EMAIL")
        jira_api_token = os.getenv("JIRA_API_TOKEN")
        openai_api_key = os.getenv("OPENAI_API_KEY")

        if not all([jira_url, jira_email, jira_api_token, openai_api_key]):
            raise EnvironmentError(
                "JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, OPENAI_API_KEY 환경 변수가 필요합니다."
            )

        # issue_key 우선, 없으면 URL에서 추출
        if not issue_key:
            if issue_url:
                _, issue_key = parse_issue_url(issue_url)
            else:
                raise ValueError("issue_key 또는 issue_url 중 하나는 필수입니다.")

        translator = JiraTicketTranslator(
            jira_url=jira_url,
            email=jira_email,
            api_token=jira_api_token,
            openai_api_key=openai_api_key,
        )

        results_obj = translator.translate_issue(
            issue_key=issue_key,
            fields_to_translate=fields,
            perform_update=do_update,
        )

        response_data = {
            "issue_key": issue_key,
            **results_obj,
        }

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(response_data, ensure_ascii=False),
        }

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e), "type": type(e).__name__}, ensure_ascii=False),
        }


