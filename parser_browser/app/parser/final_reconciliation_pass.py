from __future__ import annotations

"""Final reconciliation audit before exporting JSON (v61.0.40)."""

from typing import Any, Dict, List

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def run_final_reconciliation(final_result: Dict[str, Any], closure_report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    closure_report = closure_report if isinstance(closure_report, dict) else {}
    issues: List[Dict[str, Any]] = []
    rows = closure_report.get("rows") or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        grades = row.get("field_evidence_grades") or {}
        if row.get("row_status") == "closed_100":
            for field, record in grades.items():
                if isinstance(record, dict) and not record.get("public_supported", True):
                    issues.append({"code": "closed_row_has_unsupported_public_field", "row_id": row.get("row_id"), "field": field, "grade": record.get("evidence_grade")})
        if row.get("row_status") == "closed_100" and row.get("missing_fields"):
            issues.append({"code": "closed_row_has_missing_fields", "row_id": row.get("row_id"), "missing_fields": row.get("missing_fields")})
    unresolved = int((closure_report.get("summary") or {}).get("unresolved") or 0)
    sicro_issues = int((closure_report.get("summary") or {}).get("sicro_issues") or 0)
    ok = not issues and unresolved == 0 and sicro_issues == 0
    report = {"version": VERSION, "ok": ok, "issues": issues, "issue_count": len(issues), "unresolved_rows": unresolved, "sicro_issues": sicro_issues}
    doc = final_result.setdefault("documento_correcao", {})
    if isinstance(doc, dict):
        doc["final_reconciliation_pass"] = report
    if not ok:
        final_result.setdefault("validacao", {}).setdefault("ocorrencias", []).append({
            "codigo": "final_reconciliation_pending_evidence",
            "severidade": "aviso",
            "categoria": "validacao",
            "mensagem": "Reconciliação final encontrou linhas/campos ainda sem prova suficiente.",
            "etapa": "final_reconciliation_pass",
            "evidencia": report,
        })
    return report
