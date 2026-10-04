"""Static checks, security scanner and browser harness."""

import pytest

from ai_ceo.verification.security import redact_secrets, scan_files, score
from ai_ceo.verification.static_checks import run_static_checks

HTML = """<!DOCTYPE html><html lang="en"><head><meta name="viewport" content="width=device-width"><title>T</title>
<link rel="stylesheet" href="style.css"></head><body><input id="name"><output id="out"></output>
<script src="app.js" defer></script></body></html>"""


def categories(issues):
    return {i.category for i in issues if i.severity == "error"}


def test_clean_project_has_no_errors():
    files = {"index.html": HTML, "style.css": "body{color:#111}", "app.js": "document.getElementById('name').value = 'x';"}
    assert categories(run_static_checks(files, list(files))) == set()


def test_static_checks_find_common_small_model_bugs():
    files = {
        "index.html": HTML.replace('href="style.css"', 'href="styles.css"'),
        "app.js": "const c = require('crypto-js');\ndocument.getElementById('nmae');\nfunction broken( {",
        "style.css": "body { color: red;",
    }
    cats = categories(run_static_checks(files, ["index.html", "app.js", "style.css", "missing.js"]))
    assert {"broken_reference", "browser_compat", "dom_reference", "syntax", "missing_file"} <= cats


def test_python_import_policy():
    issues = run_static_checks({"backend/main.py": "import requests\nfrom fastapi import FastAPI\n"}, [])
    assert any(i.category == "dependency" and "requests" in i.message for i in issues)


def test_security_findings_and_redaction():
    files = {
        "app.js": "el.innerHTML = `<b>${userInput}</b>`;\nconst api_key = 'sk-ant-abcdefghijklmnopqrstuvwxyz0123';\nconst pw = Math.random(); // password",
        "backend/main.py": (
            "from fastapi import FastAPI\napp = FastAPI()\n@app.post('/x')\ndef x(data: dict):\n"
            "    cur.execute(f\"SELECT * FROM t WHERE id={data['id']}\")\n"
        ),
        "index.html": '<a href="https://x.com" target="_blank">x</a>',
    }
    findings = scan_files(files)
    text = " ".join(f.message for f in findings)
    for expected in ("LLM provider API key", "innerHTML", "Math.random", "SQL", "unvalidated", "noopener"):
        assert expected in text, expected
    assert all("abcdefghijklmnop" not in f.evidence for f in findings), "secrets must be redacted in evidence"
    assert score(findings) < 50


def test_placeholders_are_not_reported_as_secrets():
    assert not [f for f in scan_files({"a.js": "const api_key = 'your-api-key-here';"}) if f.category == "secret"]


def test_redact_secrets_helper():
    assert "ghp_" in redact_secrets("token ghp_" + "a" * 40) and "a" * 40 not in redact_secrets("token ghp_" + "a" * 40)


@pytest.mark.browser
def test_browser_harness_semantics(tmp_path):
    from ai_ceo.verification.browser import run_browser_suite
    from ai_ceo.verification.servers import StaticServer

    (tmp_path / "index.html").write_text(
        '<!DOCTYPE html><html><body><input id="pw"><button id="go">Go</button>'
        "<script>document.getElementById('go').onclick=()=>{document.getElementById('pw').value='abcdefghij'}</script></body></html>"
    )
    steps = lambda *s: [{"action": a, "selector": sel, "value": v} for a, sel, v in s]  # noqa: E731
    scenarios = [
        {"name": "value via expect_text", "steps": steps(("click", "#go", ""), ("expect_text", "#pw", "abcdef"))},
        {"name": "length", "steps": steps(("click", "#go", ""), ("expect_length", "#pw", "10"))},
        {"name": "empty expectation is not vacuous", "steps": steps(("expect_text", "#pw", ""))},
        {"name": "hallucinated selector", "steps": steps(("click", "#does-not-exist", ""))},
    ]
    with StaticServer(tmp_path) as srv:
        r = run_browser_suite(srv.url, "index.html", scenarios, channel="auto", screenshot_path=None,
                              source_text=(tmp_path / "index.html").read_text(), step_timeout_ms=1500)
    res = {s["name"]: s for s in r["scenarios"]}
    assert res["value via expect_text"]["passed"]
    assert res["length"]["passed"]
    assert not res["empty expectation is not vacuous"]["passed"]
    assert res["hallucinated selector"]["defect"] == "test"


def test_static_server_blocks_dotfiles(tmp_path):
    import httpx

    from ai_ceo.verification.servers import StaticServer

    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret")
    (tmp_path / "index.html").write_text("ok")
    with StaticServer(tmp_path) as srv:
        assert httpx.get(srv.url + "/index.html").status_code == 200
        assert httpx.get(srv.url + "/.git/config").status_code == 404
        assert httpx.get(srv.url + "/%2Egit/config").status_code == 404
