# test-translation

Generate a read-only translation quality report for any Jira issue.

## Usage

```bash
/test-translation ISSUE_OR_URL
```

## Arguments

- `ISSUE_OR_URL`: Jira issue key or URL (e.g., `PAYDAY-104` or full Jira browse URL)

## What it does

1. Fetches issue fields in read-only mode (`summary`, `description`, detected steps field)
2. Strips existing translation artifacts (blue color block / bilingual summary / bilingual steps)
3. Re-runs translation with the same engine rules used by production flow
4. Builds an HTML report with 3 panes per field:
   - source (extracted)
   - translated (raw assembly)
   - bilingual (final ticket-format output)
5. Opens the report locally

## Instructions

Run:

```bash
python translation_style_report.py $ARGS
```

Optional examples:

```bash
python translation_style_report.py PAYDAY-104 --target-language Korean
python translation_style_report.py https://cloud.jira.krafton.com/browse/P2-70735 --output /tmp/p2-70735-preview.html
```

After execution, summarize:
- whether report generation succeeded
- key style observations
- generated report path
- confirm no Jira update was performed
