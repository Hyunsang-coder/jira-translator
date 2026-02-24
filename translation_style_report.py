#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from jira_trans import JiraTicketTranslator, parse_issue_url
from modules import formatting, language


DEFAULT_REPORT_PATH_TEMPLATE = "/tmp/{issue_key}_translation.html"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a read-only translation report for a Jira issue. "
            "Report includes source text, plain translation, and final bilingual output."
        )
    )
    parser.add_argument(
        "issue",
        help="Jira issue key or URL (e.g., PAYDAY-104 or https://.../browse/P2-70735)",
    )
    parser.add_argument(
        "--target-language",
        dest="target_language",
        default=None,
        help="Optional output language hint (Korean/English, ko/en).",
    )
    parser.add_argument(
        "--output",
        dest="output",
        default=None,
        help=f"Optional output HTML path (default: {DEFAULT_REPORT_PATH_TEMPLATE})",
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
    # " / " 또는 " /" (공백 없이 붙은 경우) 모두 처리
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


def extract_source_description(text: str) -> str:
    return _strip_translation_color_blocks(text)


def extract_source_steps(text: str) -> str:
    cleaned = _strip_translation_color_blocks(text)
    if not cleaned:
        return ""

    parts = [part.strip() for part in re.split(r"\n{2,}", cleaned) if part.strip()]
    if len(parts) < 2:
        return cleaned

    first_lang = language.detect_text_language(parts[0])
    second_lang = language.detect_text_language(parts[1])
    if first_lang == "unknown" or second_lang == "unknown" or first_lang == second_lang:
        return cleaned

    # Keep contiguous blocks in the first paragraph's language.
    kept: list[str] = []
    for part in parts:
        current_lang = language.detect_text_language(part)
        if current_lang in {first_lang, "unknown"}:
            kept.append(part)
            continue
        break

    if kept:
        return "\n\n".join(kept).strip()
    return cleaned


def extract_source_field(field: str, value: str, steps_field: str) -> str:
    if field == "summary":
        return extract_source_summary(value)
    if field == "description":
        return extract_source_description(value)
    if field == steps_field:
        return extract_source_steps(value)
    return _strip_translation_color_blocks(value)


def configure_glossary(translator: JiraTicketTranslator, issue_key: str) -> tuple[str, str, str]:
    project_key = issue_key.split("-", 1)[0].upper()
    glossary_file, glossary_name = translator._determine_glossary(project_key)
    translator.translation_engine.load_glossary(glossary_file, glossary_name)
    return project_key, glossary_file, glossary_name


def resolve_steps_field(translator: JiraTicketTranslator, project_key: str) -> str:
    detected = translator.jira_client.detect_steps_field(project_key)
    if detected:
        return detected
    return translator._fallback_steps_field(project_key)


def translate_source_fields(
    translator: JiraTicketTranslator,
    source_fields: dict[str, str],
    fields_order: list[str],
    target_language: str | None,
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    translation_results: dict[str, dict[str, str]] = {}
    jobs = {}
    all_chunks = []

    for field in fields_order:
        source_value = source_fields.get(field, "")
        if not source_value:
            continue

        translation_results[field] = {
            "original": source_value,
            "translated": "",
        }
        job = translator._plan_field_translation_job(field, source_value)
        if not job:
            continue
        jobs[field] = job
        all_chunks.extend(job.chunks)

    chunk_translations: dict[str, str] = {}
    if all_chunks:
        try:
            chunk_translations = translator._call_openai_batch(all_chunks, target_language)
        except Exception as exc:
            print(f"⚠️ Batch translation failed, fallback to per-chunk mode: {exc}")
            chunk_translations = translator._translate_chunks_individually(jobs, target_language)

    for field, job in jobs.items():
        assembled: list[str] = []
        for chunk in job.chunks:
            translated_raw = chunk_translations.get(chunk.id, "")
            restored = translator.restore_attachments_markup(translated_raw, chunk.attachments)
            if job.mode == "description":
                if chunk.skip_translation:
                    block_parts: list[str] = []
                    if chunk.header:
                        block_parts.append(chunk.header)
                    if chunk.original_text:
                        block_parts.append(chunk.original_text)
                    block = "\n".join(block_parts).strip()
                else:
                    block = translator._format_bilingual_block(
                        chunk.original_text,
                        restored,
                        header=chunk.header,
                    )
                if block:
                    assembled.append(block)
            else:
                if restored:
                    assembled.append(restored)

        if job.mode == "description":
            translated_value = "\n\n".join(filter(None, assembled)).strip()
        else:
            translated_value = "\n\n".join(filter(None, assembled))
        translation_results[field]["translated"] = translated_value

    update_payload = translator.build_field_update_payload(translation_results)
    return translation_results, update_payload


def _html_pre(text: str) -> str:
    return f"<pre>{html.escape(text or '')}</pre>"


def build_html_report(
    *,
    issue_key: str,
    jira_url: str,
    model: str,
    glossary_name: str,
    steps_field: str,
    fields_order: list[str],
    source_fields: dict[str, str],
    translation_results: dict[str, dict[str, str]],
    update_payload: dict[str, str],
) -> str:
    jira_link = f"{jira_url.rstrip('/')}/browse/{issue_key}"
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sections: list[str] = []
    for field in fields_order:
        source_text = source_fields.get(field, "")
        bilingual_text = update_payload.get(field, "")
        if not source_text and not bilingual_text:
            continue

        field_label = f"{field} (steps)" if field == steps_field else field
        sections.append(
            f"""
            <section>
              <h2>{html.escape(field_label)}</h2>
              <div class="compare">
                <div class="col source">
                  <div class="label">Source (Original)</div>
                  {_html_pre(source_text)}
                </div>
                <div class="col bilingual">
                  <div class="label">Bilingual (Final Ticket Format)</div>
                  {_html_pre(bilingual_text)}
                </div>
              </div>
            </section>
            """
        )

    sections_html = "\n".join(sections) if sections else "<p>No translatable fields found.</p>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(issue_key)} Translation Preview</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --panel: #ffffff;
      --text: #1f2a37;
      --muted: #6b7280;
      --source-bg: #fffbe6;
      --source-border: #facc15;
      --translated-bg: #eef2ff;
      --translated-border: #818cf8;
      --bilingual-bg: #ecfeff;
      --bilingual-border: #06b6d4;
    }}
    body {{
      margin: 0;
      padding: 24px;
      background: radial-gradient(circle at top right, #dbeafe 0%, var(--bg) 38%);
      color: var(--text);
      font-family: "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      margin-bottom: 20px;
      padding: 20px;
      background: var(--panel);
      border-radius: 12px;
      box-shadow: 0 2px 10px rgba(15, 23, 42, 0.06);
    }}
    header h1 {{
      margin: 0 0 6px;
      font-size: 1.35rem;
    }}
    header .meta {{
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.5;
    }}
    header a {{
      color: #0f4c81;
    }}
    section {{
      background: var(--panel);
      border-radius: 12px;
      padding: 18px;
      margin-bottom: 18px;
      box-shadow: 0 2px 10px rgba(15, 23, 42, 0.06);
    }}
    section h2 {{
      margin: 0 0 12px;
      font-size: 0.95rem;
      letter-spacing: 0.02em;
      color: #374151;
    }}
    .compare {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .col {{
      border-radius: 10px;
      border: 1px solid transparent;
      padding: 12px;
      min-height: 120px;
    }}
    .source {{
      background: var(--source-bg);
      border-color: var(--source-border);
    }}
    .translated {{
      background: var(--translated-bg);
      border-color: var(--translated-border);
    }}
    .bilingual {{
      background: var(--bilingual-bg);
      border-color: var(--bilingual-border);
    }}
    .label {{
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      font-weight: 700;
      color: #334155;
      margin-bottom: 8px;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "SF Mono", Menlo, Monaco, Consolas, monospace;
      font-size: 0.82rem;
      line-height: 1.5;
    }}
    @media (max-width: 1200px) {{
      .compare {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Translation Preview: {html.escape(issue_key)}</h1>
    <div class="meta">
      Jira: <a href="{html.escape(jira_link)}" target="_blank" rel="noopener noreferrer">{html.escape(jira_link)}</a><br>
      Generated: {html.escape(generated_at)}<br>
      Model: {html.escape(model)} | Glossary: {html.escape(glossary_name)} | Steps field: {html.escape(steps_field)}
    </div>
  </header>
  {sections_html}
</body>
</html>
"""


def write_report(path: str, html_text: str) -> str:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(html_text, encoding="utf-8")
    return str(resolved)


def open_report(path: str) -> None:
    for cmd in (["open", path], ["xdg-open", path]):
        try:
            result = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                return
        except FileNotFoundError:
            continue


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    env_path = repo_root / ".env"
    load_dotenv(env_path)

    jira_url_env = os.getenv("JIRA_URL", "").strip()
    jira_email = os.getenv("JIRA_EMAIL", "").strip()
    jira_api_token = os.getenv("JIRA_API_TOKEN", "").strip()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model = os.getenv("OPENAI_MODEL", "gpt-5.2").strip() or "gpt-5.2"

    missing = []
    if not jira_url_env:
        missing.append("JIRA_URL")
    if not jira_email:
        missing.append("JIRA_EMAIL")
    if not jira_api_token:
        missing.append("JIRA_API_TOKEN")
    if not openai_api_key:
        missing.append("OPENAI_API_KEY")
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    jira_url, issue_key = normalize_issue_input(args.issue, jira_url_env)
    translator = JiraTicketTranslator(
        jira_url=jira_url,
        email=jira_email,
        api_token=jira_api_token,
        openai_api_key=openai_api_key,
    )
    translator.openai_model = openai_model

    project_key, _, glossary_name = configure_glossary(translator, issue_key)
    steps_field = resolve_steps_field(translator, project_key)
    fields_order = ["summary", "description", steps_field]

    fetched_fields = translator.fetch_issue_fields(issue_key, fields_order)
    source_fields = {
        field: extract_source_field(field, fetched_fields.get(field, ""), steps_field)
        for field in fields_order
    }

    translation_results, update_payload = translate_source_fields(
        translator=translator,
        source_fields=source_fields,
        fields_order=fields_order,
        target_language=args.target_language,
    )

    output_path = args.output or DEFAULT_REPORT_PATH_TEMPLATE.format(issue_key=issue_key)
    report_html = build_html_report(
        issue_key=issue_key,
        jira_url=jira_url,
        model=translator.openai_model,
        glossary_name=glossary_name,
        steps_field=steps_field,
        fields_order=fields_order,
        source_fields=source_fields,
        translation_results=translation_results,
        update_payload=update_payload,
    )
    report_path = write_report(output_path, report_html)
    open_report(report_path)

    print(f"✅ Translation preview report created: {report_path}")
    print(f"   - Issue: {issue_key}")
    print(f"   - Model: {translator.openai_model}")
    print(f"   - Glossary: {glossary_name}")
    print("   - Jira update: not performed (read-only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
