#!/usr/bin/env python3
"""
update_test_ticket.py

소스 티켓의 원문을 추출해 테스트용 티켓 P2-70735에 복사한다.
번역 파이프라인 테스트 전 샌드박스 초기화 용도.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from jira_trans import JiraTicketTranslator, parse_issue_url
from modules import formatting, language

TEST_TICKET = "P2-70735"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            f"Copy source ticket's original text into the test ticket ({TEST_TICKET}). "
            "Strips any existing translations before copying."
        )
    )
    parser.add_argument(
        "source",
        help=f"Source Jira issue key or URL (e.g., PAYDAY-105 or https://.../browse/P2-12345)",
    )
    parser.add_argument(
        "--test-ticket",
        dest="test_ticket",
        default=TEST_TICKET,
        help=f"Target test ticket key (default: {TEST_TICKET})",
    )
    parser.add_argument(
        "-y", "--yes",
        dest="yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    return parser.parse_args()


def normalize_issue_input(issue_input: str, default_jira_url: str) -> tuple[str, str]:
    raw = (issue_input or "").strip()
    if not raw:
        raise ValueError("Issue key or URL is required.")
    if raw.startswith("http://") or raw.startswith("https://"):
        jira_url, issue_key = parse_issue_url(raw)
        return jira_url.rstrip("/"), issue_key.upper()
    issue_key = raw.upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", issue_key):
        raise ValueError(f"Invalid issue key: {issue_input}")
    return default_jira_url.rstrip("/"), issue_key


def _strip_translation_color_blocks(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(
        r"\{color:#4c9aff\}.*?\{color\}",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # color 블록 제거 후 "* " 처럼 불릿만 남은 빈 줄 제거
    cleaned = re.sub(r"^[ \t]*\*[ \t]*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_source_summary(text: str) -> str:
    cleaned = _strip_translation_color_blocks(text)
    if not cleaned:
        return ""
    prefix, core = formatting.split_bracket_prefix(cleaned)
    sep_match = re.search(r" /\s*", core)
    if not sep_match:
        return cleaned
    left = core[:sep_match.start()]
    right = core[sep_match.end():]
    left_lang = language.detect_text_language(left)
    right_lang = language.detect_text_language(right)
    if left_lang != "unknown" and right_lang != "unknown" and left_lang != right_lang:
        return f"{prefix}{left.strip()}".strip()
    return cleaned


def extract_source_steps(text: str) -> str:
    cleaned = _strip_translation_color_blocks(text)
    if not cleaned:
        return ""
    parts = [part.strip() for part in re.split(r"\n{2,}", cleaned) if part.strip()]
    if len(parts) < 2:
        return cleaned
    first_lang = language.detect_text_language(parts[0])
    last_lang = language.detect_text_language(parts[-1])
    # 첫 파트와 마지막 파트 언어가 다를 때만 번역 suffix가 있다고 판단
    if first_lang == "unknown" or last_lang == "unknown" or first_lang == last_lang:
        return cleaned
    kept: list[str] = []
    for part in parts:
        current_lang = language.detect_text_language(part)
        if current_lang in {first_lang, "unknown"}:
            kept.append(part)
            continue
        break
    return "\n\n".join(kept).strip() if kept else cleaned


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    load_dotenv(repo_root / ".env")

    jira_url_env = os.getenv("JIRA_URL", "").strip()
    jira_email = os.getenv("JIRA_EMAIL", "").strip()
    jira_api_token = os.getenv("JIRA_API_TOKEN", "").strip()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()

    missing = [k for k, v in {
        "JIRA_URL": jira_url_env,
        "JIRA_EMAIL": jira_email,
        "JIRA_API_TOKEN": jira_api_token,
        "OPENAI_API_KEY": openai_api_key,
    }.items() if not v]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    jira_url, source_key = normalize_issue_input(args.source, jira_url_env)
    test_key = args.test_ticket.upper()

    if source_key == test_key:
        raise ValueError(f"Source and test ticket are the same: {source_key}")

    translator = JiraTicketTranslator(
        jira_url=jira_url,
        email=jira_email,
        api_token=jira_api_token,
        openai_api_key=openai_api_key,
    )

    # 소스 티켓의 steps field 감지
    source_project = source_key.split("-", 1)[0].upper()
    steps_field = translator.jira_client.detect_steps_field(source_project)
    if not steps_field:
        steps_field = translator._fallback_steps_field(source_project)

    fields_to_fetch = ["summary", "description", steps_field]

    print(f"📥 Fetching source ticket: {source_key} ...")
    fetched = translator.fetch_issue_fields(source_key, fields_to_fetch)

    # 원문만 추출 (기존 번역 suffix 제거)
    source_fields: dict[str, str] = {}
    if fetched.get("summary"):
        source_fields["summary"] = extract_source_summary(fetched["summary"])
    if fetched.get("description"):
        source_fields["description"] = _strip_translation_color_blocks(fetched["description"])
    if fetched.get(steps_field):
        source_fields[steps_field] = extract_source_steps(fetched[steps_field])

    # 테스트 티켓의 steps field (P2 프로젝트)
    test_project = test_key.split("-", 1)[0].upper()
    test_steps_field = translator.jira_client.detect_steps_field(test_project)
    if not test_steps_field:
        test_steps_field = translator._fallback_steps_field(test_project)

    # payload 구성: 소스의 steps field → 테스트 티켓의 steps field로 매핑
    payload: dict[str, str] = {}
    if source_fields.get("summary"):
        payload["summary"] = source_fields["summary"]
    if source_fields.get("description"):
        payload["description"] = source_fields["description"]
    if source_fields.get(steps_field):
        payload[test_steps_field] = source_fields[steps_field]

    if not payload:
        print("⚠️  No fields to copy.")
        return 1

    print(f"\n📋 Fields to copy → {test_key}:")
    for field, value in payload.items():
        preview = value.replace("\n", " ")[:80]
        print(f"  [{field}] {preview}{'...' if len(value) > 80 else ''}")

    if not args.yes:
        try:
            confirm = input(f"\nUpdate {test_key} with the above content? [y/N]: ").strip().lower()
        except EOFError:
            confirm = "y"  # 비대화형 환경에서는 자동 승인
    else:
        confirm = "y"

    if confirm != "y":
        print("❌ Cancelled.")
        return 0

    print(f"\n✏️  Updating {test_key} ...")
    translator.jira_client.update_issue_fields(test_key, payload)
    print(f"✅ {test_key} updated with original content from {source_key}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
