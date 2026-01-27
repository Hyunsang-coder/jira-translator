# Validate Glossary Files

Check all glossary JSON files for validity and consistency.

## Context
See `_context.md` for project structure.

## Instructions

1. Find all glossary files:
   ```bash
   ls glossaries/*.json
   ```

2. For each glossary file, validate:
   - **JSON syntax**: Parse with Python's json module
   - **Required structure**: Must have `"terms"` object
   - **No empty values**: All terms must have non-empty translations
   - **No duplicate keys**: Check for duplicate Korean or English terms across files

3. Run validation script:
   ```python
   import json
   from pathlib import Path

   glossary_dir = Path("glossaries")
   all_terms = {}
   errors = []

   for f in glossary_dir.glob("*.json"):
       try:
           data = json.loads(f.read_text(encoding="utf-8"))
           if "terms" not in data:
               errors.append(f"{f.name}: missing 'terms' key")
               continue
           for k, v in data["terms"].items():
               if not k or not v:
                   errors.append(f"{f.name}: empty term or translation for '{k}'")
               if k in all_terms:
                   errors.append(f"{f.name}: duplicate term '{k}' (also in {all_terms[k]})")
               all_terms[k] = f.name
       except json.JSONDecodeError as e:
           errors.append(f"{f.name}: invalid JSON - {e}")

   if errors:
       print("Errors found:")
       for e in errors:
           print(f"  - {e}")
   else:
       print(f"All {len(list(glossary_dir.glob('*.json')))} glossary files valid")
       print(f"Total terms: {len(all_terms)}")
   ```

4. Report:
   - Number of glossary files checked
   - Total term count
   - Any errors or warnings found

## Glossary Files

| File | Project |
|------|---------|
| `pubg_glossary.json` | PUBG |
| `bsg_glossary.json` | BSG |
| `heist_glossary.json` | HeistRoyale |
| `pbb_glossary.json` | PBB (default) |

## Called By
- `/commit` - When glossary files changed
- `/push` - When glossary files changed since last commit
