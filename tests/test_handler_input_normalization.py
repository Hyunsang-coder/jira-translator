import json
import base64

import handler


class _DummyTranslator:
    last_init = None
    last_translate_issue_kwargs = None

    def __init__(self, jira_url: str, email: str, api_token: str, openai_api_key: str):
        _DummyTranslator.last_init = {
            "jira_url": jira_url,
            "email": email,
            "api_token": api_token,
            "openai_api_key": openai_api_key,
        }

    def translate_issue(self, **kwargs):
        _DummyTranslator.last_translate_issue_kwargs = kwargs
        return {"results": {}, "update_payload": {}, "updated": False, "error": None}


def _reset_dummy_state():
    _DummyTranslator.last_init = None
    _DummyTranslator.last_translate_issue_kwargs = None


def _set_required_env(monkeypatch):
    monkeypatch.setenv("JIRA_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "bot@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "token")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


def _clear_required_env(monkeypatch):
    monkeypatch.delenv("JIRA_URL", raising=False)
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_form_update_false_is_not_treated_as_true(monkeypatch):
    _reset_dummy_state()
    _set_required_env(monkeypatch)
    monkeypatch.setattr(handler, "JiraTicketTranslator", _DummyTranslator)

    event = {
        "headers": {"Content-Type": "application/x-www-form-urlencoded"},
        "body": "issue_key=BUG-1&update=false",
    }

    response = handler.lambda_handler(event, context={})

    assert response["statusCode"] == 200
    assert _DummyTranslator.last_translate_issue_kwargs["perform_update"] is False


def test_form_update_true_is_treated_as_true(monkeypatch):
    _reset_dummy_state()
    _set_required_env(monkeypatch)
    monkeypatch.setattr(handler, "JiraTicketTranslator", _DummyTranslator)

    event = {
        "headers": {"Content-Type": "application/x-www-form-urlencoded"},
        "body": "issue_key=BUG-1&update=true",
    }

    response = handler.lambda_handler(event, context={})

    assert response["statusCode"] == 200
    assert _DummyTranslator.last_translate_issue_kwargs["perform_update"] is True


def test_form_repeated_fields_to_translate_preserved_as_list(monkeypatch):
    _reset_dummy_state()
    _set_required_env(monkeypatch)
    monkeypatch.setattr(handler, "JiraTicketTranslator", _DummyTranslator)

    event = {
        "headers": {"Content-Type": "application/x-www-form-urlencoded"},
        "body": (
            "issue_key=BUG-11"
            "&fields_to_translate=summary"
            "&fields_to_translate=description"
            "&fields_to_translate=customfield_10399"
        ),
    }

    response = handler.lambda_handler(event, context={})

    assert response["statusCode"] == 200
    assert _DummyTranslator.last_translate_issue_kwargs["fields_to_translate"] == [
        "summary",
        "description",
        "customfield_10399",
    ]


def test_json_fields_csv_string_is_normalized_to_list(monkeypatch):
    _reset_dummy_state()
    _set_required_env(monkeypatch)
    monkeypatch.setattr(handler, "JiraTicketTranslator", _DummyTranslator)

    event = {
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "issue_key": "BUG-2",
                "fields_to_translate": "summary, description , customfield_10399",
            }
        ),
    }

    response = handler.lambda_handler(event, context={})

    assert response["statusCode"] == 200
    assert _DummyTranslator.last_translate_issue_kwargs["fields_to_translate"] == [
        "summary",
        "description",
        "customfield_10399",
    ]


def test_json_fields_array_string_is_normalized_to_list(monkeypatch):
    _reset_dummy_state()
    _set_required_env(monkeypatch)
    monkeypatch.setattr(handler, "JiraTicketTranslator", _DummyTranslator)

    event = {
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "issue_key": "BUG-3",
                "fields_to_translate": '["summary", "description"]',
            }
        ),
    }

    response = handler.lambda_handler(event, context={})

    assert response["statusCode"] == 200
    assert _DummyTranslator.last_translate_issue_kwargs["fields_to_translate"] == [
        "summary",
        "description",
    ]


def test_json_fields_deduplicates_while_preserving_order(monkeypatch):
    _reset_dummy_state()
    _set_required_env(monkeypatch)
    monkeypatch.setattr(handler, "JiraTicketTranslator", _DummyTranslator)

    event = {
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "issue_key": "BUG-33",
                "fields_to_translate": [
                    "summary",
                    "description",
                    "summary",
                    "customfield_10399",
                    "description",
                ],
            }
        ),
    }

    response = handler.lambda_handler(event, context={})

    assert response["statusCode"] == 200
    assert _DummyTranslator.last_translate_issue_kwargs["fields_to_translate"] == [
        "summary",
        "description",
        "customfield_10399",
    ]


def test_json_fields_rejects_invalid_field_name(monkeypatch):
    _reset_dummy_state()
    _set_required_env(monkeypatch)
    monkeypatch.setattr(handler, "JiraTicketTranslator", _DummyTranslator)

    event = {
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "issue_key": "BUG-4",
                "fields_to_translate": "summary,evil_field",
            }
        ),
    }

    response = handler.lambda_handler(event, context={})
    body = json.loads(response["body"])

    assert response["statusCode"] == 400
    assert body["type"] == "ValueError"
    assert "Invalid fields_to_translate" in body["error"]
    assert _DummyTranslator.last_translate_issue_kwargs is None


def test_invalid_issue_url_returns_400(monkeypatch):
    _reset_dummy_state()
    _set_required_env(monkeypatch)
    monkeypatch.setattr(handler, "JiraTicketTranslator", _DummyTranslator)

    event = {
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "issue_url": "not-a-valid-url",
                "update": False,
            }
        ),
    }

    response = handler.lambda_handler(event, context={})
    body = json.loads(response["body"])

    assert response["statusCode"] == 400
    assert body["type"] == "ValueError"
    assert _DummyTranslator.last_translate_issue_kwargs is None


def test_issue_url_is_resolved_to_issue_key(monkeypatch):
    _reset_dummy_state()
    _set_required_env(monkeypatch)
    monkeypatch.setattr(handler, "JiraTicketTranslator", _DummyTranslator)

    event = {
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "issue_url": "https://example.atlassian.net/browse/BUG-777",
                "update": False,
            }
        ),
    }

    response = handler.lambda_handler(event, context={})
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["issue_key"] == "BUG-777"
    assert _DummyTranslator.last_translate_issue_kwargs["issue_key"] == "BUG-777"


def test_missing_issue_key_and_issue_url_returns_400(monkeypatch):
    _reset_dummy_state()
    _set_required_env(monkeypatch)
    monkeypatch.setattr(handler, "JiraTicketTranslator", _DummyTranslator)

    event = {
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"update": False}),
    }

    response = handler.lambda_handler(event, context={})
    body = json.loads(response["body"])

    assert response["statusCode"] == 400
    assert body["type"] == "ValueError"
    assert "issue_key 또는 issue_url" in body["error"]
    assert _DummyTranslator.last_translate_issue_kwargs is None


def test_malformed_json_body_returns_400(monkeypatch):
    _reset_dummy_state()
    _set_required_env(monkeypatch)
    monkeypatch.setattr(handler, "JiraTicketTranslator", _DummyTranslator)

    event = {
        "headers": {"Content-Type": "application/json"},
        "body": '{"issue_key":"BUG-5",',
    }

    response = handler.lambda_handler(event, context={})
    body = json.loads(response["body"])

    assert response["statusCode"] == 400
    assert body["type"] == "ValueError"
    assert "파싱할 수 없습니다" in body["error"]
    assert _DummyTranslator.last_translate_issue_kwargs is None


def test_base64_encoded_json_body_is_parsed(monkeypatch):
    _reset_dummy_state()
    _set_required_env(monkeypatch)
    monkeypatch.setattr(handler, "JiraTicketTranslator", _DummyTranslator)

    raw_body = json.dumps({"issue_key": "BUG-66", "update": "true"})
    event = {
        "headers": {"Content-Type": "application/json"},
        "body": base64.b64encode(raw_body.encode("utf-8")).decode("utf-8"),
        "isBase64Encoded": True,
    }

    response = handler.lambda_handler(event, context={})

    assert response["statusCode"] == 200
    assert _DummyTranslator.last_translate_issue_kwargs["perform_update"] is True


def test_missing_env_returns_500_environment_error(monkeypatch):
    _reset_dummy_state()
    _clear_required_env(monkeypatch)
    monkeypatch.setattr(handler, "JiraTicketTranslator", _DummyTranslator)

    event = {
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"issue_key": "BUG-6"}),
    }

    response = handler.lambda_handler(event, context={})
    body = json.loads(response["body"])

    assert response["statusCode"] == 500
    assert body["type"] == "OSError"
    assert "환경 변수가 필요합니다" in body["error"]
    assert _DummyTranslator.last_init is None
