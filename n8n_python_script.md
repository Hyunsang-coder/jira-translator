# N8N Python Code Node Asset

Copy and paste the following code into an N8N **Code Node** (Language: Python).
This script consolidates `formatting.py` and `language.py` to handle Jira markup and language detection within N8N.

## Usage in N8N
1. **Input**: The node expects the incoming JSON to have fields: `description`, `summary`, `steps` (optional).
2. **Output**: It adds checking results and parsed chunks to the JSON.

```python
import re
import json

# ==========================================
# MODULE: language.py
# ==========================================

def detect_text_language(text, extract_text_func=None):
    if not text:
        return "unknown"
    
    # Simple sanitization if no func provided
    if extract_text_func:
        sanitized = extract_text_func(text)
    else:
        sanitized = extract_detectable_text(text)
        
    if not sanitized:
        return "unknown"
    
    korean_chars = len(re.findall(r"[\uac00-\ud7a3]", sanitized))
    latin_chars = len(re.findall(r"[A-Za-z]", sanitized))
    
    # 3. Korean Particle Patterns
    korean_particle_patterns = [
        r'[\uac00-\ud7a3][이가](?:\s|$|[^\uac00-\ud7a3])',
        r'[\uac00-\ud7a3][을를](?:\s|$|[^\uac00-\ud7a3])',
        r'[\uac00-\ud7a3][은는](?:\s|$|[^\uac00-\ud7a3])',
        r'[\uac00-\ud7a3]에서(?:\s|$)',
        r'[\uac00-\ud7a3]에(?:\s|$)',
        r'[\uac00-\ud7a3]으?로(?:\s|$)',
        r'[\uac00-\ud7a3][와과](?:\s|$)',
        r'[\uac00-\ud7a3]의(?:\s|$)',
        r'[A-Za-z]에서(?:\s|$)',
        r'[A-Za-z]으?로(?:\s|$)',
        r'[A-Za-z][을를](?:\s|$)',
        r'[A-Za-z][이가](?:\s|$)',
        r'[A-Za-z][은는](?:\s|$)',
        r'[A-Za-z]와(?:\s|$)',
    ]
    
    korean_particle_count = 0
    for pattern in korean_particle_patterns:
        korean_particle_count += len(re.findall(pattern, text))
    
    # 4. Korean Ending Patterns
    korean_ending_patterns = [
        r'입니다[.!?\s]?$', r'습니다[.!?\s]?$', r'됩니다[.!?\s]?$',
        r'있습니다[.!?\s]?$', r'없습니다[.!?\s]?$', r'했습니다[.!?\s]?$',
        r'합니다[.!?\s]?$', r'됩니다[.!?\s]?$', r'집니다[.!?\s]?$',
        r'입니까[.!?\s]?$', r'습니까[.!?\s]?$',
        r'세요[.!?\s]?$', r'해요[.!?\s]?$', r'돼요[.!?\s]?$',
        r'[다음임함됨없음있음][.!?\s]?$',
        r'현상입니다', r'현상임', r'발생함', r'확인됨',
        r'느립니다', r'빠릅니다', r'많습니다', r'적습니다',
        r'됩니다', r'않습니다', r'못합니다',
    ]
    
    korean_ending_count = 0
    for pattern in korean_ending_patterns:
        if re.search(pattern, text, re.MULTILINE):
            korean_ending_count += 1
            
    korean_structure_score = korean_particle_count + korean_ending_count
    
    english_sentence_patterns = [
        r'\b(the|a|an)\s+\w+',
        r'\b(is|are|was|were|be)\s+',
        r'\b(have|has|had)\s+(been|to)',
        r'\b(to|for|from|with|by|at|in|on)\s+\w+',
        r'\b(when|where|what|who|why|how)\s+',
        r'\b(if|then|else|because|although)\s+',
        r'\bshould\s+(be|not|have)',
        r'\bcan\s+(be|not|have)',
        r'\bwill\s+(be|not|have)',
    ]
    
    english_sentence_count = 0
    text_lower = text.lower()
    for pattern in english_sentence_patterns:
        english_sentence_count += len(re.findall(pattern, text_lower))
        
    if korean_structure_score >= 1: return "ko"
    if korean_chars >= 1 and english_sentence_count == 0: return "ko"
    if korean_chars > latin_chars: return "ko"
    if english_sentence_count >= 1 and korean_chars == 0: return "en"
    if korean_chars == 0 and latin_chars > 0: return "en"
    if korean_chars > 0: return "ko"
    
    return "unknown"

def extract_detectable_text(text):
    cleaned = text
    cleaned = re.sub(r"![^!]+!", " ", cleaned)
    cleaned = re.sub(r"\[\^[^\]]+\]", " ", cleaned)
    cleaned = re.sub(r"__.*?__", " ", cleaned)
    cleaned = re.sub(r"\{color:[^}]+\}|\{color\}", " ", cleaned)
    cleaned = re.sub(r"`[^`]+`", " ", cleaned)
    cleaned = re.sub(r"[^A-Za-z\uac00-\ud7a3]", "", cleaned)
    return cleaned

def is_description_already_translated(value):
    if not value:
        return False
    return bool(re.search(r"\{color:#4c9aff\}(?!\s*\|?\s*\{color\}).+", value))

# ==========================================
# MODULE: formatting.py
# ==========================================

DESCRIPTION_SECTIONS = ("Observed", "Expected", "Expected Result", "Note", "Notes", "Video", "Etc.")

def extract_attachments_markup(text):
    if not text:
        return [], ""
    attachments = []
    image_pattern = r'!([^!]+?)(?:\|[^!]*)?!'
    attachment_pattern = r'\[\^([^\]]+?)\]'

    def replace_image(match):
        attachments.append(match.group(0))
        return f"__IMAGE_PLACEHOLDER_{len(attachments)-1}__"

    def replace_attachment(match):
        attachments.append(match.group(0))
        return f"__ATTACHMENT_PLACEHOLDER_{len(attachments)-1}__"

    text = re.sub(image_pattern, replace_image, text)
    text = re.sub(attachment_pattern, replace_attachment, text)
    return attachments, text

def restore_attachments_markup(text, attachments):
    for i, attachment_markup in enumerate(attachments):
        text = text.replace(f"__IMAGE_PLACEHOLDER_{i}__", attachment_markup)
        text = text.replace(f"__ATTACHMENT_PLACEHOLDER_{i}__", attachment_markup)
    return text

def match_section_header(line):
    stripped = re.sub(r"\{color:[^}]+\}|\{color\}", "", line or "").strip()
    stripped_no_colon = stripped.rstrip(":").strip("*_ ")
    lowered = stripped_no_colon.lower()
    
    if "/" in lowered:
        left = lowered.split("/", 1)[0].strip()
    else:
        left = lowered
    left = re.split(r"[\(\[]", left, 1)[0].strip()

    for header in DESCRIPTION_SECTIONS:
        normalized = header.lower()
        if left == normalized or left.startswith(f"{normalized} "):
            return stripped
    return None

def extract_description_sections(text):
    if not text:
        return []
    sections = []
    current_header = None
    buffer = []

    def flush():
        nonlocal buffer, current_header
        if not buffer:
            return
        content = "\n".join(buffer).strip("\n")
        buffer = []
        if content:
            sections.append((current_header, content))

    for line in text.splitlines():
        header = match_section_header(line)
        if header:
            flush()
            current_header = header
            continue
        buffer.append(line)
    flush()
    return sections

# ==========================================
# N8N EXECUTION LOGIC
# ==========================================

# Access items from the previous node
# In N8N Python node, 'items' is a list of dictionaries.
# Each dictionary has a 'json' key with the payload.

output_items = []

for item in items:
    data = item.get('json', {})
    
    # 1. Inputs
    description = data.get('description', '')
    summary = data.get('summary', '')
    
    # 2. Check if translation needed
    needs_desc_trans = not is_description_already_translated(description)
    
    # 3. Extract Markup from Description
    desc_attachments, desc_clean = extract_attachments_markup(description)
    
    # 4. Split Description into Sections
    sections = []
    if needs_desc_trans:
        raw_sections = extract_description_sections(desc_clean)
        # Convert to list of dicts for JSON
        for header, content in raw_sections:
            sections.append({
                "header": header,
                "content": content,
                "needs_translation": True # You could add language detection here per section
            })
    
    # 5. Append results to item
    data['analysis'] = {
        "needs_description_translation": needs_desc_trans,
        "description_sections": sections,
        "description_attachments": desc_attachments, # Store to restore later
    }
    
    output_items.append({"json": data})

return output_items
```

### Post-Processing Code (Merging Translations)

Use this in a second Code Node after getting translations from OpenAI.

```python
# ... (Include formatting.py / restore_attachments_markup functions again here) ...

def format_bilingual_block(original, translated, header=None):
    # (Copy the full format_bilingual_block function logic from formatting.py here)
    # Since it is long, refer to the original file for the full specific logic 
    # regarding code blocks and tables.
    # For brevity in this asset, I'll provide a simplified version, 
    # but for production use the full function.
    
    lines = []
    if header:
        lines.append(header)
    lines.append(original)
    lines.append("") # Spacer
    lines.append(f"{{color:#4c9aff}}{translated}{{color}}")
    return "\n".join(lines)

# Execution
output_items = []
for item in items:
    data = item.get('json', {})
    analysis = data.get('analysis', {})
    
    # Assume 'translated_text' comes from OpenAI node, 
    # or you iterate over the sections if you split them in batches.
    
    # Example logic for simple merge
    original_sections = analysis.get('description_sections', [])
    attachments = analysis.get('description_attachments', [])
    
    final_desc_parts = []
    
    # WARNING: This part implies you have mapped the translations back to the sections
    # In a real N8N flow, you might loop over sections, translate, and aggregator.
    # Here we assume 'translated_sections' list is available in the input.
    
    translated_sections = data.get('translated_sections', []) 
    
    for i, section in enumerate(original_sections):
        orig_content = section['content']
        header = section['header']
        
        # Determine translated content
        # (Implementation depends on how you structured the optimization loop)
        trans_content = translated_sections[i] if i < len(translated_sections) else ""
        
        # Restore markup in translation
        trans_restored = restore_attachments_markup(trans_content, attachments)
        
        # Format
        block = format_bilingual_block(orig_content, trans_restored, header)
        final_desc_parts.append(block)
        
    final_description = "\n\n".join(final_desc_parts)
    
    data['final_description'] = final_description
    output_items.append({"json": data})

return output_items
```
