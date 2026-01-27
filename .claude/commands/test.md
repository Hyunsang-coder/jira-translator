# Run Tests

Execute pytest with proper configuration for this project.

## Context
See `_context.md` for project structure.

## Instructions

1. Run the test suite:
   ```bash
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
   ```

2. If a specific test file is provided as argument, run only that file:
   ```bash
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q <test_file>
   ```

3. Report results clearly:
   - Number of tests passed/failed
   - If failures, show the failing test names and error messages
   - Suggest fixes if obvious

4. **On success**: Confirm ready for `/commit` or `/push`
5. **On failure**: Do NOT proceed with commit/push, fix first

## Arguments

- `$ARGUMENTS` - Optional: specific test file or test pattern (e.g., `tests/test_formatting.py`, `tests/test_formatting.py::test_extract_attachments`)

## Critical Tests

These tests protect against markup regression:
- `test_formatting.py` - Image/code block preservation
- `test_batch_translation.py` - Multi-field translation
- `test_ticket_type_logic.py` - Project detection

## Example Usage

```
/test                              # Run all tests
/test tests/test_formatting.py     # Run specific file
```

## Called By
- `/commit` - When core modules changed
- `/push` - Before deployment
