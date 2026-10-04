"""Model-output parsing: the root cause of the original prototype's failure."""

import pytest

from ai_ceo.llm.parsing import ParseError, extract_code, extract_files, extract_json, to_strict_schema
from ai_ceo.schemas import ArchitectureOutput, ReviewOutput
from ai_ceo.schemas import TestPlanOutput as PlanOutput

# Verbatim shape of llama3.1:8b's reply to the original prototype's prompt.
LLAMA_REPLY = """**index.html**
```html
<!DOCTYPE html>
<html><head><link rel="stylesheet" href="style.css"></head>
<body><button id="go">Go</button><script src="script.js"></script></body></html>
```

**style.css**
```css
body { color: red; }
```

**script.js**
```javascript
document.getElementById('go').addEventListener('click', () => alert(1));
```
"""


def test_extract_files_handles_markdown_headings():
    files = extract_files(LLAMA_REPLY)
    assert set(files) == {"index.html", "style.css", "script.js"}
    assert files["style.css"].strip() == "body { color: red; }"


@pytest.mark.parametrize(
    "filename,expected_start",
    [("index.html", "<!DOCTYPE html>"), ("script.js", "document.getElementById"), ("style.css", "body {")],
)
def test_extract_code_picks_the_right_block(filename, expected_start):
    assert extract_code(LLAMA_REPLY, filename).startswith(expected_start)


def test_extract_code_falls_back_to_language_tag():
    assert extract_code(LLAMA_REPLY, "app.js").startswith("document.getElementById")


def test_extract_code_info_string_filename():
    text = "```js app.js\nconsole.log(1)\n```\n```js other.js\nconsole.log(2)\n```"
    assert extract_code(text, "other.js").strip() == "console.log(2)"


def test_extract_code_unterminated_fence_from_truncated_output():
    assert extract_code("```html\n<html><body>hi", "index.html").strip() == "<html><body>hi"


def test_extract_code_bare_code_with_prose_prefix():
    assert extract_code("Here is the file:\nbody{}", "style.css").strip() == "body{}"


def test_extract_code_empty_raises():
    with pytest.raises(ParseError):
        extract_code("   ", "app.js")


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('Sure!\n```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}
    assert extract_json('prefix {"b": "x}"} suffix') == {"b": "x}"}
    with pytest.raises(ParseError):
        extract_json("no json here")


@pytest.mark.parametrize("model", [ArchitectureOutput, ReviewOutput, PlanOutput])
def test_strict_schema_is_self_contained(model):
    schema = to_strict_schema(model)
    text = str(schema)
    assert "$ref" not in text and "$defs" not in text
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


def test_review_score_is_clamped():
    assert ReviewOutput(approved=True, score=42, issues=[], strengths=[], summary="").score == 10
