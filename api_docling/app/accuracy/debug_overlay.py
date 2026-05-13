from __future__ import annotations

from typing import Any, Dict, List

VERSION = "v61.0.35-candidate-profile-consensus-engine"


def _tables_from_docling(docling_payload: Dict[str, Any] | None) -> Dict[str, Any]:
    payload = docling_payload or {}
    return payload.get("tables") if isinstance(payload.get("tables"), dict) else payload


def build_debug_overlay(final_result: Dict[str, Any] | None = None, docling_payload: Dict[str, Any] | None = None, recovery_result: Dict[str, Any] | None = None, accuracy_report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Return a lightweight dashboard payload for Lovable/HTML tests.

    It is JSON-only and intentionally small: columns, quality issues, patches,
    unresolved recovery targets and accuracy summary.  A UI can render it as an
    overlay or as a diagnostic panel without needing the private parser state.
    """
    final_result = final_result or {}
    tables = _tables_from_docling(docling_payload)
    columns: List[Dict[str, Any]] = []
    if isinstance(tables, dict):
        for table_name, table in tables.items():
            if not isinstance(table, dict):
                continue
            for col in table.get("columns") or []:
                if isinstance(col, dict):
                    columns.append({
                        "table": table_name,
                        "canonical": col.get("canonical") or col.get("canonical_name"),
                        "header": col.get("header") or col.get("header_text"),
                        "x0": col.get("x0"),
                        "x1": col.get("x1"),
                        "confidence": col.get("geometry_confidence") or col.get("confidence"),
                        "source": col.get("geometry_source"),
                    })
    recovery = recovery_result or ((final_result.get("meta") or {}).get("targeted_recovery") or {})
    quality_gate = ((final_result.get("auditoria_final") or {}).get("quality_gate") or {}) if isinstance(final_result.get("auditoria_final"), dict) else {}
    docling_meta = (docling_payload or {}).get("metadata") if isinstance(docling_payload, dict) else {}
    return {
        "version": VERSION,
        "summary": {
            "quality_gate_ok": bool(quality_gate.get("ok")) if quality_gate else None,
            "quality_issue_count": len(quality_gate.get("issues") or []) if isinstance(quality_gate, dict) else 0,
            "columns": len(columns),
            "patches": len(recovery.get("patches") or []) if isinstance(recovery, dict) else 0,
            "unresolved": len(recovery.get("unresolved") or []) if isinstance(recovery, dict) else 0,
            "accuracy": (accuracy_report or {}).get("overall_field_accuracy"),
            "docling_cache_status": ((docling_meta or {}).get("cache") or {}).get("status") if isinstance(docling_meta, dict) else None,
        },
        "columns": columns[:200],
        "quality_issues": (quality_gate.get("issues") or [])[:100] if isinstance(quality_gate, dict) else [],
        "patches": (recovery.get("patches") or [])[:100] if isinstance(recovery, dict) else [],
        "unresolved": (recovery.get("unresolved") or [])[:100] if isinstance(recovery, dict) else [],
        "accuracy_report": accuracy_report or {},
        "docling_profile": (docling_meta or {}).get("calibrated_document_profile") if isinstance(docling_meta, dict) else None,
    }
