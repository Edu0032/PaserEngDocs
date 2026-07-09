from __future__ import annotations

"""Real-document regression and error-driven tuning helpers (v61.0.46).

This module is intentionally lightweight: it does not replace the parser.  It
uses the same Physical Evidence Index and an optional expected_core contract to
measure whether a real PDF still provides the anchors that matter for budget
parsing.  It is useful both in tests and in Lovable/debug flows.
"""

from typing import Any, Dict, List, Tuple

from app.parser.physical_evidence_index import build_physical_evidence_index

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def _find_field_value(index: Dict[str, Any], key: str, field: str, expected: str) -> Tuple[bool, Dict[str, Any]]:
    bucket = ((index.get("keys") or {}).get(key) or {}) if isinstance(index, dict) else {}
    data = ((bucket.get("fields") or {}).get(field) or {}) if isinstance(bucket, dict) else {}
    expected_clean = _clean(expected)
    for value_rec in data.get("values") or []:
        if _clean(value_rec.get("value")) == expected_clean:
            return True, value_rec
    return False, {}


def run_real_document_regression(pdf_path: str, final_result: Dict[str, Any], options: Dict[str, Any] | None = None) -> Dict[str, Any]:
    options = options if isinstance(options, dict) else {}
    expected_core = options.get("expected_core") or (options.get("real_document_regression") or {}).get("expected_core") or {}
    physical_index = options.get("physical_evidence_index") if isinstance(options.get("physical_evidence_index"), dict) else None
    if not physical_index:
        physical_index = build_physical_evidence_index(pdf_path, final_result, options)

    expected_items = expected_core.get("items") if isinstance(expected_core, dict) else []
    checks: List[Dict[str, Any]] = []
    passed = 0
    failed = 0
    for item in expected_items or []:
        if not isinstance(item, dict):
            continue
        key = f"{_clean(item.get('codigo'))}|{_clean(item.get('banco') or item.get('fonte')).upper()}"
        # normalize PRÓPRIO to PROPRIO the same way physical index does
        key = key.replace("PRÓPRIO", "PROPRIO")
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        for field, expected in fields.items():
            ok, evidence = _find_field_value(physical_index, key, str(field), str(expected))
            checks.append({
                "codigo_banco": key,
                "field": field,
                "expected": expected,
                "ok": ok,
                "evidence": {k: evidence.get(k) for k in ("value", "count", "pages", "max_confidence", "source_count") if k in evidence},
            })
            if ok:
                passed += 1
            else:
                failed += 1
    key_count = int(physical_index.get("key_count") or 0) if isinstance(physical_index, dict) else 0
    occurrence_count = int(physical_index.get("occurrence_count") or 0) if isinstance(physical_index, dict) else 0
    section_counts = (physical_index.get("document_section_counts") or {}) if isinstance(physical_index, dict) else {}
    policy_counts = (physical_index.get("evidence_policy_counts") or {}) if isinstance(physical_index, dict) else {}
    return {
        "version": VERSION,
        "mode": "real_document_regression_and_error_driven_tuning",
        "status": "ok" if failed == 0 else "needs_review",
        "summary": {
            "physical_index_keys": key_count,
            "physical_index_occurrences": occurrence_count,
            "expected_checks": passed + failed,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / max(passed + failed, 1), 4),
            "document_section_counts": section_counts,
            "evidence_policy_counts": policy_counts,
        },
        "checks": checks,
        "tuning_findings": _tuning_findings(physical_index),
    }


def _tuning_findings(physical_index: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if not isinstance(physical_index, dict):
        return findings
    section_counts = physical_index.get("document_section_counts") or {}
    if section_counts.get("memoria_calculo"):
        findings.append({
            "type": "section_policy_active",
            "section": "memoria_calculo",
            "impact": "calculation-memory occurrences can support quantities/context but cannot overwrite public price fields",
        })
    if section_counts.get("curva_abc"):
        findings.append({
            "type": "section_policy_active",
            "section": "curva_abc",
            "impact": "ABC curve values are kept diagnostic to avoid contaminating budget/composition prices",
        })
    if (physical_index.get("source_zone_counts") or {}).get("outside_known_intervals"):
        findings.append({
            "type": "raw_context_scan_active",
            "impact": "code+banco occurrences outside declared ranges are retained as raw evidence with conservative write policies",
        })
    return findings[:50]
