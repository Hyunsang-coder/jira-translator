# test-translation

Test translation style and quality using P2-70735 test ticket.

## Usage

```
/test-translation SOURCE_TICKET
```

## Arguments

- `SOURCE_TICKET`: Source Jira ticket key or URL to copy content from (e.g., `P2-12345` or full URL)

## What it does

1. **Reset**: Copies source ticket content to test ticket (P2-70735), removing any existing translations
2. **Translate**: Runs full translation pipeline on the test ticket
3. **Verify**: Outputs translation results with style checks (e.g., '습니다'체 for EN→KO)

## Example

```
/test-translation P2-72155
/test-translation https://cloud.jira.krafton.com/browse/P2-72155
```

## Instructions

Run the test translation script:

```bash
python test_translation_style.py $ARGS
```

After execution, provide a summary:
- Whether the translation completed successfully
- Key style observations (습니다체 usage for EN→KO, symptom-first titles for KO→EN)
- Link to the test ticket for manual verification
