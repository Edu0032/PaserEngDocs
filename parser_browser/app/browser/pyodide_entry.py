from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from app.browser.docling_seed_pdf import build_docling_seed_pdf_file_json, build_selected_pages_pdf_file_json
from app.browser.recovery_agent import apply_targeted_recovery_json as _apply_targeted_recovery_json
from app.browser.service import (
    BrowserParseError,
    BrowserValidationError,
    merge_stages_browser,
    parse_budget_stage_browser,
    parse_compositions_stage_browser,
    parse_document_browser,
)


def parse_pdf_bytes(pdf_bytes: bytes, options: Dict[str, Any]) -> Dict[str, Any]:
    return parse_document_browser(pdf_bytes, options)


def parse_base_pdf_bytes(pdf_bytes: bytes, options: Dict[str, Any]) -> Dict[str, Any]:
    return parse_document_browser(pdf_bytes, options)


def parse_pdf_file(file_path: str, options: Dict[str, Any]) -> Dict[str, Any]:
    pdf_bytes = Path(file_path).read_bytes()
    return parse_document_browser(pdf_bytes, options)


def parse_base_file(file_path: str, options: Dict[str, Any]) -> Dict[str, Any]:
    pdf_bytes = Path(file_path).read_bytes()
    return parse_document_browser(pdf_bytes, options)


def parse_budget_file(file_path: str, options: Dict[str, Any]) -> Dict[str, Any]:
    pdf_bytes = Path(file_path).read_bytes()
    return parse_budget_stage_browser(pdf_bytes, options)


def parse_compositions_file(file_path: str, options: Dict[str, Any]) -> Dict[str, Any]:
    pdf_bytes = Path(file_path).read_bytes()
    return parse_compositions_stage_browser(pdf_bytes, options)


def merge_stages(budget_payload: Dict[str, Any], compositions_payload: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
    return merge_stages_browser(budget_payload, compositions_payload, options)


def _error_json(exc: Exception) -> str:
    payload = {
        'status': 'error',
        'error': {
            'code': getattr(exc, 'code', 'browser_parse_error'),
            'message': str(exc),
            'detail': getattr(exc, 'detail', None),
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def parse_base_file_json(file_path: str, options_json: str) -> str:
    options = json.loads(options_json) if options_json else {}
    try:
        result = parse_base_file(file_path, options)
        return json.dumps(result, ensure_ascii=False)
    except (BrowserValidationError, BrowserParseError) as exc:
        return _error_json(exc)
    except Exception as exc:  # pragma: no cover - fallback defensivo
        payload = {
            'status': 'error',
            'error': {
                'code': 'internal_browser_error',
                'message': str(exc),
                'detail': {'exception_type': exc.__class__.__name__},
            },
        }
        return json.dumps(payload, ensure_ascii=False)


def parse_budget_file_json(file_path: str, options_json: str) -> str:
    options = json.loads(options_json) if options_json else {}
    try:
        result = parse_budget_file(file_path, options)
        return json.dumps(result, ensure_ascii=False)
    except (BrowserValidationError, BrowserParseError) as exc:
        return _error_json(exc)
    except Exception as exc:
        return json.dumps({'status': 'error', 'error': {'code': 'internal_browser_error', 'message': str(exc), 'detail': {'exception_type': exc.__class__.__name__}}}, ensure_ascii=False)


def parse_compositions_file_json(file_path: str, options_json: str) -> str:
    options = json.loads(options_json) if options_json else {}
    try:
        result = parse_compositions_file(file_path, options)
        return json.dumps(result, ensure_ascii=False)
    except (BrowserValidationError, BrowserParseError) as exc:
        return _error_json(exc)
    except Exception as exc:
        return json.dumps({'status': 'error', 'error': {'code': 'internal_browser_error', 'message': str(exc), 'detail': {'exception_type': exc.__class__.__name__}}}, ensure_ascii=False)


def merge_stages_json(budget_json: str, compositions_json: str, options_json: str) -> str:
    options = json.loads(options_json) if options_json else {}
    budget_payload = json.loads(budget_json) if budget_json else {}
    comp_payload = json.loads(compositions_json) if compositions_json else {}
    try:
        result = merge_stages(budget_payload, comp_payload, options)
        return json.dumps(result, ensure_ascii=False)
    except (BrowserValidationError, BrowserParseError) as exc:
        return _error_json(exc)
    except Exception as exc:
        return json.dumps({'status': 'error', 'error': {'code': 'internal_browser_error', 'message': str(exc), 'detail': {'exception_type': exc.__class__.__name__}}}, ensure_ascii=False)




# Compatibilidade com chamadas antigas
parse_pdf_file_json = parse_base_file_json
parse_pdf_json = parse_base_file_json




def apply_targeted_recovery_json(final_json: str, recovery_json: str, options_json: str = "") -> str:
    return _apply_targeted_recovery_json(final_json, recovery_json, options_json)


# ---------------------------------------------------------------------------
# Local PyMuPDF Normalizer exports for browser/Lovable worker
# ---------------------------------------------------------------------------
def _parse_json_obj(value: str) -> Dict[str, Any]:
    try:
        data = json.loads(value or "{}")
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def normalizer_exports_json() -> str:
    payload = {
        "status": "ok",
        "exports": {
            "refine_table_structure_local_file_json": True,
            "recover_fields_local_file_json": True,
            "refine_table_structure_local_json": True,
            "recover_fields_local_json": True,
            "build_debug_overlay_json": True,
            "generate_accuracy_report_json": True,
        },
        "version": "v61.0.35-candidate-profile-consensus-engine",
    }
    return json.dumps(payload, ensure_ascii=False)


def refine_table_structure_local_file_json(file_path: str, payload_json: str = "") -> str:
    """Refine Docling table structure locally with PyMuPDF geometry.

    This is the browser/Pyodide equivalent of the old Normalizer API endpoint.
    The JS worker passes a mini-PDF/seed-PDF path plus a JSON payload.
    """
    try:
        from app.normalizer.column_refiner import refine_table_structure
        pdf_bytes = Path(file_path).read_bytes()
        payload = _parse_json_obj(payload_json)
        result = refine_table_structure(pdf_bytes, payload)
        result.setdefault("metadata", {})
        result["metadata"].setdefault("normalizer_mode", "local_pymupdf_pyodide")
        result["metadata"]["entrypoint_export"] = "refine_table_structure_local_file_json"
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "ok": False,
            "error": {"code": "normalizer_local_refine_failed", "message": str(exc), "type": exc.__class__.__name__},
        }, ensure_ascii=False)


def refine_table_structure_local_json(file_path: str, payload_json: str = "") -> str:
    return refine_table_structure_local_file_json(file_path, payload_json)


def recover_fields_local_file_json(file_path: str, payload_json: str = "") -> str:
    """Recover missing/truncated fields locally from a focused mini-PDF.

    Expected payload follows the former Normalizer API: page_map + targets + table hints.
    """
    try:
        from app.normalizer.field_recovery import recover_fields
        pdf_bytes = Path(file_path).read_bytes()
        payload = _parse_json_obj(payload_json)
        result = recover_fields(pdf_bytes, payload)
        result.setdefault("metadata", {})
        result["metadata"].setdefault("normalizer_mode", "local_pymupdf_pyodide")
        result["metadata"]["entrypoint_export"] = "recover_fields_local_file_json"
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "ok": False,
            "error": {"code": "normalizer_local_recovery_failed", "message": str(exc), "type": exc.__class__.__name__},
            "patches": [],
            "unresolved": [],
        }, ensure_ascii=False)


def recover_fields_local_json(file_path: str, payload_json: str = "") -> str:
    return recover_fields_local_file_json(file_path, payload_json)


def build_debug_overlay_json(final_json: str = "{}", docling_json: str = "{}", recovery_json: str = "{}", accuracy_json: str = "{}") -> str:
    try:
        from app.accuracy.debug_overlay import build_debug_overlay
        final = json.loads(final_json or "{}")
        docling = json.loads(docling_json or "{}")
        recovery = json.loads(recovery_json or "{}")
        accuracy = json.loads(accuracy_json or "{}")
        return json.dumps(build_debug_overlay(final, docling, recovery, accuracy), ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"version": "v61.0.35-candidate-profile-consensus-engine", "status": "error", "error": {"code": "debug_overlay_failed", "message": str(exc), "type": exc.__class__.__name__}}, ensure_ascii=False)


def generate_accuracy_report_json(actual_json: str = "{}", expected_json: str = "{}", version: str = "") -> str:
    try:
        from app.accuracy.metrics import generate_accuracy_report
        actual = json.loads(actual_json or "{}")
        expected = json.loads(expected_json or "{}")
        report = generate_accuracy_report(version or "v61.0.35-candidate-profile-consensus-engine", [{"name": "lovable_expected_result", "actual": actual, "expected": expected}])
        return json.dumps(report, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"version": "v61.0.35-candidate-profile-consensus-engine", "status": "error", "error": {"code": "accuracy_report_failed", "message": str(exc), "type": exc.__class__.__name__}}, ensure_ascii=False)
