# Open WebUI Template Variables Documentation

This document describes all template variables available in Open WebUI prompt templates.

## Template Processing Architecture

### Processing Order

Templates are processed through multiple functions, each handling different variable types:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Template Processing Flow                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. prompt_variables_template()  ─── User-defined variables     │
│           ↓                          (from request metadata)     │
│  2. prompt_template()            ─── System variables            │
│           ↓                          (date, time, user info)     │
│  3. rag_template()               ─── RAG-specific variables      │
│           ↓                          (context, query, KBs)       │
│  4. replace_*_variable()         ─── Special processing          │
│                                      (prompt truncation, etc.)   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Where Variables Are Replaced

| Function | Applied To | Location |
|----------|------------|----------|
| `prompt_template()` | System prompts, RAG templates, all task templates | `utils/task.py:39` |
| `rag_template()` | RAG templates only | `utils/task.py:187` |
| `prompt_variables_template()` | System prompts with metadata | `utils/payload.py:28` |
| `replace_prompt_variable()` | Title generation, follow-up, tags | `utils/task.py:112` |
| `replace_messages_variable()` | Templates needing message history | `utils/task.py:142` |

---

## Variable Reference

### RAG Template Variables

These are specific to the RAG template (`RAG_TEMPLATE` setting).

| Variable | Alias | Description | Example Value |
|----------|-------|-------------|---------------|
| `{{CONTEXT}}` | `[context]` | Retrieved document chunks formatted as XML | `<source id="1" name="doc.pdf">content</source>` |
| `{{QUERY}}` | `[query]` | The user's question/message | `What is the vacation policy?` |
| `{{KNOWLEDGE_BASES}}` | - | Knowledge base metadata (name + description) | `<kb name="HR" description="..."/>` |

**Context Format:**
```xml
<source id="1" name="HR_Policies.pdf">
First retrieved chunk from HR policies...
</source>
<source id="2" name="Employee_Handbook.pdf">
Chunk from employee handbook...
</source>
<source id="1" name="HR_Policies.pdf">
Second chunk from HR policies (same id reused)...
</source>
```

**Knowledge Bases Format:**
```xml
<kb id="kb-uuid-1" name="HR Policies" description="Company policies covering leave, benefits, and conduct guidelines"/>
<kb id="kb-uuid-2" name="Technical Docs" description="API documentation and architecture guides"/>
```

Note: The `{{KNOWLEDGE_BASES}}` variable is populated automatically from knowledge bases
attached to the chat. Values are HTML-escaped to prevent injection attacks.
If no knowledge bases are used, this variable will be empty.

### System Variables (Global)

Available in ALL templates that call `prompt_template()`.

| Variable | Description | Example Value |
|----------|-------------|---------------|
| `{{CURRENT_DATE}}` | Today's date | `2026-01-14` |
| `{{CURRENT_TIME}}` | Current time (12h format) | `01:30:45 PM` |
| `{{CURRENT_DATETIME}}` | Date and time combined | `2026-01-14 01:30:45 PM` |
| `{{CURRENT_WEEKDAY}}` | Day of week | `Tuesday` |

### User Variables (Global)

Available when user context is passed to `prompt_template()`.

| Variable | Description | Source | Default |
|----------|-------------|--------|---------|
| `{{USER_NAME}}` | User's display name | `user.name` | `Unknown` |
| `{{USER_BIO}}` | User's biography | `user.bio` | `Unknown` |
| `{{USER_GENDER}}` | User's gender | `user.gender` | `Unknown` |
| `{{USER_BIRTH_DATE}}` | User's birth date | `user.date_of_birth` | `Unknown` |
| `{{USER_AGE}}` | Calculated age | Derived from birth date | `Unknown` |
| `{{USER_LOCATION}}` | User's location | `user.info.location` | `Unknown` |

**Note:** In RAG templates, user variables currently resolve to `Unknown` because the user object is not passed through.

### User-Defined Variables

Custom variables passed via `metadata.variables` in the request body.

**How to use:**
```json
{
  "model": "gpt-4",
  "messages": [...],
  "metadata": {
    "variables": {
      "{{COMPANY_NAME}}": "Acme Corp",
      "{{DEPARTMENT}}": "Engineering",
      "{{CUSTOM_VAR}}": "any value"
    }
  }
}
```

These are replaced in **system prompts only** via `prompt_variables_template()`.

### Message Variables

Used in title generation, follow-up suggestions, and similar templates.

| Variable | Variants | Description |
|----------|----------|-------------|
| `{{MESSAGES}}` | - | Full message history formatted |
| `{{MESSAGES:START:N}}` | N = number | First N messages |
| `{{MESSAGES:END:N}}` | N = number | Last N messages |
| `{{MESSAGES:MIDDLETRUNCATE:N}}` | N = number | First half + last half (total N) |

### Prompt Variables

Used in templates that need the user's input.

| Variable | Variants | Description |
|----------|----------|-------------|
| `{{prompt}}` | - | Full user prompt |
| `{{prompt:start:N}}` | N = chars | First N characters |
| `{{prompt:end:N}}` | N = chars | Last N characters |
| `{{prompt:middletruncate:N}}` | N = chars | Truncated with `...` in middle |

### Task-Specific Variables

| Variable | Used In | Description |
|----------|---------|-------------|
| `{{TYPE}}` | Emoji generation | Content type (tweet, email, etc.) |
| `{{TOOLS}}` | Function calling | JSON tool specifications |

---

## Extensibility Analysis

### Current Architecture Limitations

1. **Not centralized**: Variables are scattered across multiple functions
2. **No registry**: New variables require code changes in multiple places
3. **No env var support**: Cannot use environment variables in templates
4. **Limited user vars**: User-defined vars only work in system prompts
5. **No model vars**: Cannot access model name/ID in templates

### How to Add New Variables

**For RAG templates** (`rag_template()`):
```python
# In utils/task.py, modify rag_template():
def rag_template(template: str, context: str, query: str, knowledge_bases: str = ""):
    # ... existing code ...
    template = template.replace("{{KNOWLEDGE_BASES}}", knowledge_bases)
    return template
```

**For all templates** (`prompt_template()`):
```python
# In utils/task.py, modify prompt_template():
template = template.replace("{{NEW_VAR}}", value)
```

### Recommended Improvements

1. **Variable Registry Pattern**:
```python
TEMPLATE_VARIABLES = {
    "{{CURRENT_DATE}}": lambda ctx: datetime.now().strftime("%Y-%m-%d"),
    "{{USER_NAME}}": lambda ctx: ctx.get("user", {}).get("name", "Unknown"),
    "{{ENV:VAR_NAME}}": lambda ctx: os.environ.get("VAR_NAME", ""),
}
```

2. **Environment Variable Support**:
```python
# Pattern: {{ENV:VARIABLE_NAME}}
env_pattern = r"\{\{ENV:([A-Z_]+)\}\}"
template = re.sub(env_pattern, lambda m: os.environ.get(m.group(1), ""), template)
```

3. **User Settings Access**:
```python
# Pattern: {{SETTINGS:key.path}}
# Would allow: {{SETTINGS:rag.top_k}}
```

---

## Template Examples

### RAG Template with Knowledge Base Context
```
### Available Knowledge Bases:
{{KNOWLEDGE_BASES}}

### Task:
Answer the user's question using the provided context.
Cite sources using [id] format.

### Context:
{{CONTEXT}}

### Question:
{{QUERY}}
```

### System Prompt with User Info
```
You are assisting {{USER_NAME}} from {{USER_LOCATION}}.
Today is {{CURRENT_DATE}} ({{CURRENT_WEEKDAY}}).

User bio: {{USER_BIO}}
```

### System Prompt with Custom Variables
```
You are a {{DEPARTMENT}} assistant for {{COMPANY_NAME}}.
Follow all {{COMPANY_NAME}} guidelines.
```

---

## File References

| File | Purpose |
|------|---------|
| `utils/task.py:39-109` | `prompt_template()` - System/user variables |
| `utils/task.py:187-225` | `rag_template()` - RAG variables |
| `utils/task.py:33-36` | `prompt_variables_template()` - Custom variables |
| `utils/task.py:112-139` | `replace_prompt_variable()` - Prompt truncation |
| `utils/task.py:142-179` | `replace_messages_variable()` - Message handling |
| `utils/payload.py:14-42` | `apply_system_prompt_to_body()` - Where vars are applied |
| `utils/middleware.py:290-337` | `apply_source_context_to_messages()` - Context building |
| `config.py:2933-2957` | `DEFAULT_RAG_TEMPLATE` - Default template |
