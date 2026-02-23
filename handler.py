from __future__ import annotations

import base64
import json
import os
import re
import urllib.parse
from collections.abc import Sequence

from jira_trans import JiraTicketTranslator, parse_issue_url


def _json_response(status_code: int, payload: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, ensure_ascii=False),
    }


def _coerce_bool(value) -> bool:
    """외부 입력값을 보수적으로 bool로 정규화."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "t", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "f", "no", "n", "off", ""}:
            return False
        return False
    return bool(value)


def _normalize_fields_to_translate(value) -> list[str] | None:
    """fields_to_translate 입력을 list[str]로 정규화."""
    if value is None:
        return None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None

        # JSON 배열 문자열 지원: '["summary","description"]'
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, Sequence) and not isinstance(parsed, (str, bytes, bytearray)):
                    normalized = [str(item).strip() for item in parsed if str(item).strip()]
                    value = normalized or None
            except Exception:
                pass

        if isinstance(value, str):
            # CSV/단일 문자열 지원
            parts = [part.strip() for part in text.split(",")]
            normalized = [part for part in parts if part]
            value = normalized or None

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        normalized = [str(item).strip() for item in value if str(item).strip()]
        value = normalized or None

    if not value:
        return None

    allowed_base = {"summary", "description"}
    invalid = [
        field for field in value
        if field not in allowed_base and not re.fullmatch(r"customfield_\d+", field)
    ]
    if invalid:
        raise ValueError(
            f"Invalid fields_to_translate: {', '.join(invalid)}. "
            "Allowed: summary, description, customfield_<digits>."
        )

    # 중복 필드는 순서를 유지한 채 제거한다.
    deduped = list(dict.fromkeys(value))
    return deduped


def _parse_request_payload(event: dict) -> dict:
    """API Gateway 이벤트에서 body를 파싱해 event에 병합한 사본을 반환."""
    merged = dict(event or {})
    body_raw = merged.get("body") or ""

    if merged.get("isBase64Encoded"):
        if isinstance(body_raw, str):
            body_raw = body_raw.encode("utf-8", "ignore")
        body_raw = base64.b64decode(body_raw).decode("utf-8", "ignore")

    headers = merged.get("headers") or {}
    content_type = headers.get("content-type") or headers.get("Content-Type") or ""
    content_type = content_type.lower() if isinstance(content_type, str) else ""

    parsed: dict = {}
    parse_error: Exception | None = None
    try:
        if "application/json" in content_type:
            parsed = json.loads(body_raw or "{}")
        elif "application/x-www-form-urlencoded" in content_type:
            parsed = {}
            for k, v in urllib.parse.parse_qs(body_raw).items():
                # 반복 키로 들어오는 fields_to_translate는 배열 형태를 유지한다.
                if k == "fields_to_translate":
                    parsed[k] = v if isinstance(v, list) else [v]
                else:
                    parsed[k] = v[0] if isinstance(v, list) else v
    except Exception as exc:
        parsed = {}
        parse_error = exc

    if parse_error and str(body_raw).strip():
        raise ValueError("요청 본문을 파싱할 수 없습니다. JSON 또는 form 형식을 확인하세요.")

    if isinstance(parsed, dict):
        merged.update(parsed)

    return merged


def _load_required_env() -> tuple[str, str, str, str]:
    jira_url = os.getenv("JIRA_URL", "https://cloud.jira.krafton.com").rstrip("/")
    jira_email = os.getenv("JIRA_EMAIL")
    jira_api_token = os.getenv("JIRA_API_TOKEN")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if not all([jira_url, jira_email, jira_api_token, openai_api_key]):
        raise EnvironmentError(
            "JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, OPENAI_API_KEY 환경 변수가 필요합니다."
        )

    return jira_url, jira_email, jira_api_token, openai_api_key


def _resolve_issue_key(issue_key, issue_url) -> str:
    # issue_key 우선, 없으면 URL에서 추출
    if issue_key:
        return issue_key
    if issue_url:
        _, resolved_issue_key = parse_issue_url(issue_url)
        return resolved_issue_key
    raise ValueError("issue_key 또는 issue_url 중 하나는 필수입니다.")


def lambda_handler(event, context):
    """
    AWS Lambda 진입점.
    - API Gateway proxy event(body/json/form) 파싱
    - 환경 변수 기반으로 Jira/OpenAI 설정 로드
    - JiraTicketTranslator 호출 후 JSON 응답 반환
    """
    try:
        event = _parse_request_payload(event or {})

        issue_key = _resolve_issue_key(event.get("issue_key"), event.get("issue_url"))
        fields = _normalize_fields_to_translate(event.get("fields_to_translate"))  # None이면 자동 결정
        do_update = _coerce_bool(event.get("update", False))

        # 보안을 위해 외부 주입 차단: 환경 변수 기반으로만 구성
        jira_url, jira_email, jira_api_token, openai_api_key = _load_required_env()

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

        return _json_response(200, response_data)

    except ValueError as e:
        print(f"❌ Bad Request: {str(e)}")
        return _json_response(400, {"error": str(e), "type": type(e).__name__})
    except EnvironmentError as e:
        print(f"❌ Configuration Error: {str(e)}")
        return _json_response(500, {"error": str(e), "type": type(e).__name__})
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return _json_response(500, {"error": str(e), "type": type(e).__name__})
