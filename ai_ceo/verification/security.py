"""Rule-based security scanner for generated code (and for the platform itself).

Covers secrets, injection sinks, unsafe APIs, insecure randomness,
missing input validation / authentication on APIs, risky configuration and
dependency hygiene. Matched secrets are redacted in every report.

There is no offline vulnerability database: dependency findings are about
hygiene (pinning, allow-list). Run ``pip-audit`` / ``npm audit`` in CI for
CVE coverage.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .issues import Issue

SEVERITY_WEIGHT = {"critical": 40, "high": 20, "medium": 8, "low": 2, "info": 0}
ALLOWED_DEPENDENCIES = {"fastapi", "pydantic", "uvicorn", "starlette"}
_PLACEHOLDER = re.compile(r"your|example|xxx|changeme|placeholder|<|\$\{|process\.env|os\.environ|getenv", re.I)


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    category: str
    pattern: re.Pattern[str]
    message: str
    recommendation: str
    extensions: tuple[str, ...] = ()  # empty = all text files
    secret: bool = False


def _r(p: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(p, flags)


RULES: list[Rule] = [
    # ---- secrets ---------------------------------------------------------------
    Rule("SEC001", "critical", "secret", _r(r"AKIA[0-9A-Z]{16}"), "AWS access key id committed", "Remove it and rotate the key; load from environment.", secret=True),
    Rule("SEC002", "critical", "secret", _r(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----"), "Private key committed", "Remove the key from the repository and rotate it.", secret=True),
    Rule("SEC003", "critical", "secret", _r(r"gh[pousr]_[A-Za-z0-9]{36,}"), "GitHub token committed", "Revoke the token; use a secret store.", secret=True),
    Rule("SEC004", "critical", "secret", _r(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token committed", "Revoke the token; use a secret store.", secret=True),
    Rule("SEC005", "critical", "secret", _r(r"sk-ant-[A-Za-z0-9_\-]{20,}|sk-(?:proj-)?[A-Za-z0-9]{32,}"), "LLM provider API key committed", "Revoke the key; read it from the environment.", secret=True),
    Rule("SEC006", "high", "secret", _r(r"AIza[0-9A-Za-z_\-]{35}"), "Google API key committed", "Restrict or rotate the key; load from config.", secret=True),
    Rule(
        "SEC007",
        "high",
        "secret",
        _r(r"""(?i)\b(api[_-]?key|secret[_-]?key|client[_-]?secret|password|passwd|auth[_-]?token|access[_-]?token)\b["']?\s*[:=]\s*["']([^"'\s]{8,})["']"""),
        "Hard-coded credential",
        "Move credentials to environment variables or a secret manager.",
        secret=True,
    ),
    # ---- JavaScript ------------------------------------------------------------
    Rule("JS001", "high", "injection", _r(r"\beval\s*\("), "eval() executes arbitrary code", "Parse data with JSON.parse or use explicit logic.", (".js", ".html")),
    Rule("JS002", "high", "injection", _r(r"\bnew\s+Function\s*\("), "new Function() executes arbitrary code", "Avoid dynamic code generation.", (".js", ".html")),
    Rule("JS003", "medium", "injection", _r(r"\bset(?:Timeout|Interval)\s*\(\s*['\"`]"), "String passed to setTimeout/setInterval (implicit eval)", "Pass a function instead of a string.", (".js", ".html")),
    Rule("JS004", "medium", "xss", _r(r"\bdocument\.write\s*\("), "document.write can inject unescaped HTML", "Build DOM nodes with createElement/textContent.", (".js", ".html")),
    Rule(
        "JS005",
        "medium",
        "xss",
        _r(r"\.(?:innerHTML|outerHTML)\s*\+?=\s*(?!['\"]\s*['\"];?)(?:`[^`]*\$\{|[A-Za-z_$][\w$.\[\]]*\s*[;+\n]|['\"][^'\"]*['\"]\s*\+)"),
        "Dynamic content assigned to innerHTML (XSS risk if it contains user input)",
        "Use textContent, or escape user-controlled values before inserting HTML.",
        (".js", ".html"),
    ),
    Rule("JS006", "medium", "xss", _r(r"insertAdjacentHTML\s*\([^,]+,\s*(?:`[^`]*\$\{|[A-Za-z_$])"), "Dynamic content passed to insertAdjacentHTML", "Escape user input or use DOM APIs.", (".js", ".html")),
    Rule("JS007", "medium", "sensitive_storage", _r(r"(?i)localStorage\.setItem\(\s*['\"][^'\"]*(password|token|secret|credit)"), "Sensitive value stored in localStorage", "Do not persist secrets client-side.", (".js", ".html")),
    Rule("JS008", "low", "transport", _r(r"""(?i)(?:src|href|fetch\()\s*=?\s*['"]http://(?!localhost|127\.0\.0\.1)"""), "Resource loaded over plain HTTP", "Use HTTPS.", (".js", ".html")),
    # ---- HTML ------------------------------------------------------------------
    Rule("HTML001", "low", "tabnabbing", _r(r"""(?i)<a\b(?=[^>]*target=["']_blank["'])(?![^>]*rel=["'][^"']*noopener)[^>]*>"""), "target=_blank without rel=noopener", 'Add rel="noopener noreferrer".', (".html",)),
    Rule("HTML002", "low", "supply_chain", _r(r"""(?i)<script\b(?=[^>]*src=["']https?://)(?![^>]*integrity=)[^>]*>"""), "Third-party script without Subresource Integrity", "Add an integrity hash or self-host the script.", (".html",)),
    Rule("HTML003", "medium", "transport", _r(r"""(?i)<form\b[^>]*action=["']http://"""), "Form submits over plain HTTP", "Submit forms over HTTPS.", (".html",)),
    # ---- Python ----------------------------------------------------------------
    Rule("PY001", "high", "injection", _r(r"(?<![\w.])(?:eval|exec)\s*\("), "eval/exec executes arbitrary code", "Remove dynamic code execution.", (".py",)),
    Rule("PY002", "high", "command_injection", _r(r"\bos\.system\s*\(|subprocess\.\w+\([^)]*shell\s*=\s*True"), "Shell command execution", "Use subprocess with an argument list and no shell.", (".py",)),
    Rule("PY003", "high", "deserialization", _r(r"\bpickle\.loads?\s*\(|\bmarshal\.loads\s*\("), "Unsafe deserialization", "Use JSON for untrusted data.", (".py",)),
    Rule("PY004", "medium", "deserialization", _r(r"\byaml\.load\s*\((?![^)]*Loader)"), "yaml.load without a safe Loader", "Use yaml.safe_load.", (".py",)),
    Rule(
        "PY005",
        "high",
        "sql_injection",
        _r(r"""\.execute(?:many)?\s*\(\s*(?:f["']|["'][^"']*["']\s*(?:%|\.format|\+))"""),
        "SQL built with string formatting (SQL injection)",
        "Use parameterized queries: cursor.execute('... WHERE id = ?', (value,)).",
        (".py",),
    ),
    Rule("PY006", "medium", "configuration", _r(r"\bdebug\s*=\s*True"), "Debug mode enabled", "Disable debug outside development.", (".py",)),
    Rule("PY007", "low", "configuration", _r(r"""host\s*=\s*["']0\.0\.0\.0["']"""), "Server binds to all interfaces", "Bind to 127.0.0.1 unless remote access is intended.", (".py",)),
    Rule(
        "PY008",
        "medium",
        "cors",
        _r(r"""allow_origins\s*=\s*\[\s*["']\*["']\s*\][\s\S]{0,200}allow_credentials\s*=\s*True"""),
        "CORS allows any origin with credentials",
        "List explicit origins when credentials are allowed.",
        (".py",),
    ),
]


def _redact(text: str) -> str:
    text = text.strip()
    return text[:4] + "...[redacted]" if len(text) > 4 else "[redacted]"


def redact_secrets(text: str) -> str:
    """Redact anything that looks like a secret; applied to every evidence snippet."""
    for rule in RULES:
        if not rule.secret:
            continue

        def _sub(m: re.Match[str]) -> str:
            value = m.group(m.lastindex or 0)
            if _PLACEHOLDER.search(value):
                return m.group(0)
            return m.group(0).replace(value, _redact(value))

        text = rule.pattern.sub(_sub, text)
    return text


def _line_of(src: str, pos: int) -> int:
    return src.count("\n", 0, pos) + 1


def _scan_rules(path: str, src: str) -> list[Issue]:
    ext = PurePosixPath(path).suffix.lower()
    found: list[Issue] = []
    for rule in RULES:
        if rule.extensions and ext not in rule.extensions:
            continue
        for m in rule.pattern.finditer(src):
            if rule.secret:
                value = m.group(m.lastindex or 0)
                if _PLACEHOLDER.search(value):
                    continue
                snippet = src[m.start() : m.end()].replace(value, _redact(value))
            else:
                line_start = src.rfind("\n", 0, m.start()) + 1
                line_end = src.find("\n", m.end())
                snippet = redact_secrets(src[line_start : line_end if line_end != -1 else len(src)].strip()[:200])
            found.append(
                Issue(
                    rule.severity,
                    rule.category,
                    f"[{rule.id}] {rule.message}",
                    file=path,
                    line=_line_of(src, m.start()),
                    source="security",
                    evidence=snippet,
                    suggestion=rule.recommendation,
                )
            )
            if len(found) > 50:
                return found
    return found


def _insecure_randomness(path: str, src: str) -> list[Issue]:
    if not path.endswith((".js", ".html")):
        return []
    if "Math.random" in src and re.search(r"(?i)password|token|secret|passphrase", src) and "getRandomValues" not in src:
        return [
            Issue(
                "medium",
                "weak_randomness",
                "Math.random() used to generate secrets/passwords (not cryptographically secure)",
                file=path,
                line=_line_of(src, src.find("Math.random")),
                source="security",
                suggestion="Use crypto.getRandomValues() for passwords and tokens.",
            )
        ]
    return []


def _api_checks(path: str, src: str) -> list[Issue]:
    """FastAPI-specific: input validation and authentication on mutating endpoints."""
    if not path.endswith(".py") or "fastapi" not in src.lower():
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    issues: list[Issue] = []
    mutating = 0
    has_auth = bool(re.search(r"Depends\(|HTTPBearer|APIKeyHeader|OAuth2", src))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            method = dec.func.attr
            if method not in ("post", "put", "patch", "delete"):
                continue
            mutating += 1
            body_src = ast.unparse(node)
            for arg in node.args.args:
                ann = ast.unparse(arg.annotation) if arg.annotation else ""
                # A Request parameter is only a problem when its raw body is parsed by hand.
                reads_raw = re.search(rf"\b{arg.arg}\.(json|form|body)\(", body_src) is not None
                if ann in ("dict", "Dict", "dict[str, Any]", "Any") or (ann == "Request" and reads_raw):
                    issues.append(
                        Issue(
                            "medium",
                            "input_validation",
                            f"endpoint '{node.name}' accepts unvalidated '{ann}' input",
                            file=path,
                            line=node.lineno,
                            source="security",
                            suggestion="Declare a pydantic model for the request body so FastAPI validates it.",
                        )
                    )
    if mutating and not has_auth:
        issues.append(
            Issue(
                "info",
                "authentication",
                f"{mutating} state-changing endpoint(s) have no authentication",
                file=path,
                source="security",
                suggestion="Acceptable for a local single-user app; add auth before exposing it on a network.",
            )
        )
    return issues


def _dependency_checks(path: str, src: str) -> list[Issue]:
    issues: list[Issue] = []
    name = PurePosixPath(path).name
    if name == "requirements.txt":
        for line in src.splitlines():
            line = line.split("#")[0].strip()
            if not line:
                continue
            pkg = re.split(r"[<>=!~\[ ;]", line, maxsplit=1)[0].lower()
            if pkg not in ALLOWED_DEPENDENCIES:
                issues.append(Issue("medium", "dependency", f"unvetted dependency '{pkg}'", file=path, source="security", suggestion="Only use approved packages."))
            if "==" not in line:
                issues.append(Issue("low", "dependency", f"dependency '{pkg}' is not pinned", file=path, source="security", suggestion="Pin exact versions for reproducible, auditable builds."))
    elif name == "package.json":
        try:
            pkg_json = json.loads(src)
        except json.JSONDecodeError:
            return [Issue("low", "configuration", "package.json is not valid JSON", file=path, source="security")]
        for section in ("dependencies", "devDependencies"):
            for dep, ver in (pkg_json.get(section) or {}).items():
                if isinstance(ver, str) and ver.startswith(("^", "~", "*", "latest")):
                    issues.append(Issue("low", "dependency", f"npm dependency '{dep}' uses a floating version ({ver})", file=path, source="security"))
    elif name == "Dockerfile" and not re.search(r"(?im)^\s*USER\s+(?!root)", src):
        issues.append(Issue("low", "configuration", "container runs as root", file=path, source="security", suggestion="Add a non-root USER."))
    return issues


def scan_files(files: dict[str, str]) -> list[Issue]:
    issues: list[Issue] = []
    for path, src in files.items():
        if PurePosixPath(path).name.startswith(".env"):
            issues.append(Issue("high", "secret", ".env file present in project", file=path, source="security", suggestion="Never commit .env files."))
        issues.extend(_scan_rules(path, src))
        issues.extend(_insecure_randomness(path, src))
        issues.extend(_api_checks(path, src))
        issues.extend(_dependency_checks(path, src))
    return issues


def score(issues: list[Issue]) -> int:
    return max(0, 100 - sum(SEVERITY_WEIGHT.get(i.severity, 0) for i in issues))
