"""HTTP API tests against a running generated backend."""

from __future__ import annotations

import json
from typing import Any

import httpx


def run_api_cases(base_url: str, cases: list[dict[str, Any]], timeout_s: float = 10.0) -> list[dict[str, Any]]:
    results = []
    with httpx.Client(base_url=base_url, timeout=timeout_s) as client:
        for case in cases[:15]:
            out: dict[str, Any] = {
                "name": case.get("name", ""),
                "method": case.get("method", "GET"),
                "path": case.get("path", "/"),
                "passed": False,
                "status": None,
                "error": "",
            }
            path = case.get("path", "/")
            if not path.startswith("/") or "://" in path:
                out["error"] = "invalid path (must be a local absolute path)"
                out["defect"] = "test"
                results.append(out)
                continue
            body = None
            raw_body = (case.get("body_json") or "").strip()
            if raw_body and raw_body not in ("{}", "null", "none", ""):
                try:
                    body = json.loads(raw_body)
                except json.JSONDecodeError:
                    out["error"] = f"test case has invalid JSON body: {raw_body[:80]}"
                    out["defect"] = "test"
                    results.append(out)
                    continue
            try:
                r = client.request(out["method"], path, json=body)
            except httpx.HTTPError as e:
                out["error"] = f"request failed: {type(e).__name__}"
                out["defect"] = "app"
                results.append(out)
                continue
            out["status"] = r.status_code
            expected = int(case.get("expect_status") or 200)
            contains = (case.get("expect_contains") or "").strip()
            text = r.text[:5000]
            if r.status_code != expected:
                out["error"] = f"expected HTTP {expected}, got {r.status_code}: {text[:200]}"
                out["defect"] = "app"
            elif contains and contains.lower() not in text.lower():
                out["error"] = f"response does not contain '{contains}': {text[:200]}"
                out["defect"] = "app"
            else:
                out["passed"] = True
            results.append(out)
    return results
