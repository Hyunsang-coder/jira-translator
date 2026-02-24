#!/usr/bin/env python3
"""
translate_test_ticket.py

테스트용 티켓 P2-70735를 번역하고 Jira에 업데이트한다.
/update-test-ticket으로 원문을 복사한 뒤 실행하는 용도.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from jira_trans import JiraTicketTranslator

TEST_TICKET = "P2-70735"


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    load_dotenv(repo_root / ".env")

    jira_url = (os.getenv("JIRA_URL") or "").rstrip("/")
    jira_email = os.getenv("JIRA_EMAIL", "").strip()
    jira_api_token = os.getenv("JIRA_API_TOKEN", "").strip()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model = os.getenv("OPENAI_MODEL", "gpt-5.2").strip() or "gpt-5.2"

    missing = [k for k, v in {
        "JIRA_URL": jira_url,
        "JIRA_EMAIL": jira_email,
        "JIRA_API_TOKEN": jira_api_token,
        "OPENAI_API_KEY": openai_api_key,
    }.items() if not v]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    translator = JiraTicketTranslator(
        jira_url=jira_url,
        email=jira_email,
        api_token=jira_api_token,
        openai_api_key=openai_api_key,
    )
    translator.openai_model = openai_model

    print(f"➡️  {TEST_TICKET} 번역 중...")
    results_obj = translator.translate_issue(
        issue_key=TEST_TICKET,
        target_language=None,
        perform_update=False,
    )

    translations = results_obj.get("results") or {}
    payload = results_obj.get("update_payload") or translator.build_field_update_payload(translations)

    if not payload:
        print("⚠️ 번역 결과가 없습니다.")
        return 1

    print("\n=== 번역 결과 ===")
    for field, content in translations.items():
        original = (content.get("original") or "").replace("\n", " ")[:100]
        translated = (content.get("translated") or "").replace("\n", " ")[:100]
        print(f"  [{field}]")
        print(f"    원문:  {original}{'...' if len(content.get('original','')) > 100 else ''}")
        print(f"    번역:  {translated}{'...' if len(content.get('translated','')) > 100 else ''}")

    print(f"\n✏️  {TEST_TICKET} 업데이트 중...")
    translator.update_issue_fields(TEST_TICKET, payload)
    print(f"✅ {TEST_TICKET} 번역 완료.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
