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


def rerun_line_certainty_closure_json(final_json: str = "{}", options_json: str = "") -> str:
    try:
        from app.parser.line_certainty_closure import run_line_certainty_closure_engine
        final = json.loads(final_json or "{}")
        options = json.loads(options_json or "{}") if options_json else {}
        max_rounds = int(((options.get("accuracy_profile") or {}).get("max_closure_rounds")) or 8)
        out, report = run_line_certainty_closure_engine(final, apply=True, max_rounds=max_rounds)
        out.setdefault("meta", {}).setdefault("performance", {})["line_certainty_closure_after_recovery"] = report
        return json.dumps(out, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "error": {"code": "line_certainty_reclosure_failed", "message": str(exc), "detail": {"exception_type": exc.__class__.__name__}}}, ensure_ascii=False)


def build_physical_evidence_index_file_json(file_path: str, final_json: str = "{}", options_json: str = "") -> str:
    try:
        from app.parser.physical_evidence_index import build_physical_evidence_index
        final = json.loads(final_json or "{}") if final_json else {}
        options = json.loads(options_json or "{}") if options_json else {}
        index = build_physical_evidence_index(file_path, final, options)
        return json.dumps(index, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "error": {"code": "physical_evidence_index_failed", "message": str(exc), "detail": {"exception_type": exc.__class__.__name__}}}, ensure_ascii=False)


def enrich_physical_evidence_index_file_json(file_path: str, final_json: str = "{}", options_json: str = "") -> str:
    """Build the physical PDF index once, attach it, and rerun closure.

    This is the v61.0.42 mini-flow hook used by the Lovable/Pyodide worker after
    the initial merge.  It makes the physical evidence index active instead of a
    passive report.
    """
    try:
        from app.parser.physical_evidence_index import build_physical_evidence_index
        from app.parser.line_certainty_closure import run_line_certainty_closure_engine
        final = json.loads(final_json or "{}") if final_json else {}
        options = json.loads(options_json or "{}") if options_json else {}
        index = build_physical_evidence_index(file_path, final, options)
        final.setdefault("meta", {}).setdefault("performance", {})["physical_evidence_index"] = index
        max_rounds = int(((options.get("accuracy_profile") or {}).get("max_closure_rounds")) or 8)
        out, report = run_line_certainty_closure_engine(final, apply=True, max_rounds=max_rounds)
        out.setdefault("meta", {}).setdefault("performance", {})["physical_evidence_index"] = index
        out.setdefault("meta", {}).setdefault("performance", {})["line_certainty_closure_after_physical_index"] = report
        if options.get("real_document_regression") or options.get("expected_core"):
            try:
                from app.parser.real_document_regression import run_real_document_regression
                regression = run_real_document_regression(file_path, out, {**options, "physical_evidence_index": index})
                out.setdefault("meta", {}).setdefault("performance", {})["real_document_regression"] = regression
                out.setdefault("documento_correcao", {})["real_document_regression"] = regression
            except Exception as _reg_exc:
                out.setdefault("documento_correcao", {}).setdefault("warnings", []).append({"tipo": "real_document_regression_failed", "message": str(_reg_exc)})
        return json.dumps(out, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "error": {"code": "physical_evidence_index_enrichment_failed", "message": str(exc), "detail": {"exception_type": exc.__class__.__name__}}}, ensure_ascii=False)


def run_physical_numeric_tail_recovery_file_json(file_path: str, final_json: str = "{}", options_json: str = "") -> str:
    """Backward-compatible export that now runs the real integrity orchestrator.

    Historically this function called only the numeric-tail tool.  In v61.0.64
    it calls the same mandatory final orchestration used by the real Lovable
    flow so standalone/manual calls cannot diverge from production behavior.
    """
    try:
        from app.parser.integrity_orchestrator import run_final_integrity_orchestrator_file
        final = json.loads(final_json or "{}") if final_json else {}
        options = json.loads(options_json or "{}") if options_json else {}
        out, _report = run_final_integrity_orchestrator_file(
            file_path, final, options, perf_key="standalone_integrity_orchestrator"
        )
        return json.dumps(out, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "error": {"code": "physical_numeric_tail_recovery_failed", "message": str(exc), "detail": {"exception_type": exc.__class__.__name__}}}, ensure_ascii=False)



def _apply_mandatory_real_flow_recovery(file_path: str, final: Dict[str, Any], options: Dict[str, Any], *, perf_key: str) -> Dict[str, Any]:
    """Run the mandatory integrity stage used by the real Lovable flow."""
    from app.parser.integrity_orchestrator import run_final_integrity_orchestrator_file
    out, _report = run_final_integrity_orchestrator_file(file_path, final, options, perf_key=perf_key)
    return out


def run_real_flow_mandatory_recovery_file_json(file_path: str, final_json: str = "{}", options_json: str = "") -> str:
    """Exported real-flow final safeguard.

    The worker calls this after the output-document organizer so late organizer
    passes cannot leave stale public numeric fields or stale quality gates.
    """
    try:
        final = json.loads(final_json or "{}") if final_json else {}
        options = json.loads(options_json or "{}") if options_json else {}
        out = _apply_mandatory_real_flow_recovery(file_path, final, options, perf_key="mandatory_real_flow_recovery_after_organizer")
        return json.dumps(out, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "error": {"code": "mandatory_real_flow_recovery_failed", "message": str(exc), "detail": {"exception_type": exc.__class__.__name__}}}, ensure_ascii=False)

def run_core_extraction_accuracy_flow_file_json(file_path: str, final_json: str = "{}", options_json: str = "") -> str:
    """Run the real output-contract accuracy enrichment flow.

    This wraps the physical evidence enrichment + line closure + output document
    organizer so Lovable can explicitly request the final JSON, correction
    document and enrichment document contracts after the initial merge.
    """
    try:
        options = json.loads(options_json or "{}") if options_json else {}
        # Real-flow mandatory repair runs before any optional evidence/organizer
        # pass so known blocking numeric holes are closed from the PDF first.
        initial_final = json.loads(final_json or "{}") if final_json else {}
        try:
            pre_repaired = _apply_mandatory_real_flow_recovery(file_path, initial_final, options, perf_key="mandatory_real_flow_recovery_pre_output_contract")
            final_json = json.dumps(pre_repaired, ensure_ascii=False)
        except Exception as _pre_exc:
            initial_final.setdefault("documento_correcao", {}).setdefault("warnings", []).append({"tipo": "mandatory_real_flow_recovery_failed", "message": str(_pre_exc)})
            final_json = json.dumps(initial_final, ensure_ascii=False)
        # The full physical-evidence/closure flow is intentionally opt-in here.
        # The real Lovable worker calls this hook in the middle of its pipeline,
        # then runs targeted recovery/organizer afterwards.  The mandatory PDF
        # recovery must be fast and always-on; the heavy full-PDF evidence pass
        # is useful but must not be required for fixing known blocking rows.
        acc = options.get("accuracy_profile") if isinstance(options.get("accuracy_profile"), dict) else {}
        explicit_heavy = bool(acc.get("run_full_output_contract_flow") or acc.get("run_full_physical_evidence_index"))
        explicit_skip = acc.get("enable_physical_evidence_index") is False
        try:
            pdf_size_bytes = Path(file_path).stat().st_size
        except Exception:
            pdf_size_bytes = 0
        # Keep legacy tiny-PDF test/recovery behavior, but do not force a full
        # physical-evidence sweep on large real documents.  Large documents get
        # the mandatory targeted PDF recovery, then the worker continues with
        # targeted recovery and a final mandatory safeguard.
        run_heavy_output_flow = explicit_heavy or (not explicit_skip and pdf_size_bytes and pdf_size_bytes < 1_200_000)
        if not run_heavy_output_flow:
            enriched = json.loads(final_json or "{}")
            return json.dumps(enriched, ensure_ascii=False)
        else:
            enriched = json.loads(enrich_physical_evidence_index_file_json(file_path, final_json, options_json) or "{}")
        if enriched.get("status") == "error":
            return json.dumps(enriched, ensure_ascii=False)
        try:
            from app.parser.line_certainty_closure import run_line_certainty_closure_engine
            from app.parser.output_documents_organizer import organize_lovable_output_documents
            from app.core.output_compact import refresh_quality_gate_after_repairs
            # v61.0.60: before the final closure/organizer, recover missing or
            # scale-lost SINAPI-like numeric tails from the same physical PDF
            # composition block.  Math may select/validate candidates, but only
            # tokens found in the PDF are written to public fields.
            try:
                from app.parser.physical_numeric_tail_recovery import apply_physical_numeric_tail_recovery_file
                enriched, numeric_tail_report = apply_physical_numeric_tail_recovery_file(file_path, enriched, {**options, "mandatory_targeted": True})
                enriched.setdefault("meta", {}).setdefault("performance", {})["physical_numeric_tail_recovery_accuracy_flow"] = numeric_tail_report
                from app.parser.budget_total_ownership import apply_budget_total_ownership_repair
                enriched, budget_owner_report = apply_budget_total_ownership_repair(enriched)
                enriched.setdefault("meta", {}).setdefault("performance", {})["budget_total_ownership_repair_accuracy_flow"] = budget_owner_report
                from app.parser.lovable_policy import apply_lovable_consumption_policy
                apply_lovable_consumption_policy(enriched)
            except Exception as _tail_exc:
                enriched.setdefault("documento_correcao", {}).setdefault("warnings", []).append({"tipo": "physical_numeric_tail_recovery_failed", "message": str(_tail_exc)})
            # v61.0.51: force the late closure/cascade pass to run in the same
            # browser flow returned to Lovable.  This prevents stale v49/v50
            # artifacts where the correction document was organized before the
            # principal-composition cascade repaired missing quant/valor/total.
            enriched, forced_closure = run_line_certainty_closure_engine(enriched, apply=True, max_rounds=int(((options.get("accuracy_profile") or {}).get("max_closure_rounds")) or 8))
            try:
                from app.parser.semantic_consistency import apply_semantic_consistency_pass
                enriched, semantic_report = apply_semantic_consistency_pass(enriched)
                enriched.setdefault("meta", {}).setdefault("performance", {})["semantic_consistency_after_closure"] = semantic_report
            except Exception as _sem_exc:
                enriched.setdefault("documento_correcao", {}).setdefault("warnings", []).append({"tipo": "semantic_consistency_failed", "message": str(_sem_exc)})
            enriched.setdefault("meta", {}).setdefault("performance", {})["line_certainty_closure_after_output_contract_flow"] = forced_closure
            refresh_quality_gate_after_repairs(enriched)
            organize_lovable_output_documents(enriched, forced_closure)
        except Exception as _org_exc:
            enriched.setdefault("documento_correcao", {}).setdefault("warnings", []).append({"tipo": "output_documents_organizer_failed", "message": str(_org_exc)})
        # Last real-flow safeguard after organizer/closure: no stale organizer or
        # late cascade can leave blocking numeric holes in final_result.
        try:
            enriched = _apply_mandatory_real_flow_recovery(file_path, enriched, options, perf_key="mandatory_real_flow_recovery_final_output_contract")
        except Exception as _final_recovery_exc:
            enriched.setdefault("documento_correcao", {}).setdefault("warnings", []).append({"tipo": "mandatory_real_flow_recovery_final_failed", "message": str(_final_recovery_exc)})
        return json.dumps(enriched, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "error": {"code": "core_extraction_accuracy_flow_failed", "message": str(exc), "detail": {"exception_type": exc.__class__.__name__}}}, ensure_ascii=False)




def organize_output_documents_json(final_json: str = "{}", closure_json: str = "{}") -> str:
    """Rebuild v61.0.48 output documents after recovery/reclosure.

    Lovable can call this after any late patch cycle so `documento_correcao`,
    `documento_evidencias` and `documento_enriquecimento` reflect the current
    final JSON instead of an earlier pre-recovery snapshot.
    """
    try:
        from app.parser.output_documents_organizer import organize_lovable_output_documents
        final = json.loads(final_json or "{}") if final_json else {}
        closure = json.loads(closure_json or "{}") if closure_json else {}
        if not closure:
            perf = (final.get("meta") or {}).get("performance") or {}
            closure = perf.get("line_certainty_closure_after_physical_index") or perf.get("line_certainty_closure_after_recovery") or perf.get("line_certainty_closure_engine") or {}
        try:
            from app.parser.composition_principal_cascade_repair import apply_composition_principal_cascade_repair
            from app.core.output_compact import refresh_quality_gate_after_repairs
            final, cascade_report = apply_composition_principal_cascade_repair(final)
            final.setdefault("meta", {}).setdefault("performance", {})["composition_principal_cascade_repair_late_organizer"] = cascade_report
            try:
                from app.parser.semantic_consistency import apply_semantic_consistency_pass
                final, semantic_report = apply_semantic_consistency_pass(final)
                final.setdefault("meta", {}).setdefault("performance", {})["semantic_consistency_late_organizer"] = semantic_report
            except Exception as _sem_exc:
                final.setdefault("documento_correcao", {}).setdefault("warnings", []).append({"tipo": "semantic_consistency_failed", "message": str(_sem_exc)})
            refresh_quality_gate_after_repairs(final)
        except Exception as _late_exc:
            final.setdefault("documento_correcao", {}).setdefault("warnings", []).append({"tipo": "late_output_sanity_failed", "message": str(_late_exc)})
        organize_lovable_output_documents(final, closure)
        return json.dumps(final, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "error": {"code": "output_documents_organizer_failed", "message": str(exc), "detail": {"exception_type": exc.__class__.__name__}}}, ensure_ascii=False)


def run_output_contract_final_flow_file_json(file_path: str, final_json: str = "{}", options_json: str = "") -> str:
    """Run the v61.0.48 definitive output-contract flow.

    This keeps the v47 core extraction flow but emits the corrected contract:
    correction document, evidence document and enrichment document are separated.
    """
    return run_core_extraction_accuracy_flow_file_json(file_path, final_json, options_json)


def generate_output_accuracy_report_json(final_json: str = "{}", closure_json: str = "{}") -> str:
    try:
        from app.parser.output_accuracy_report import build_output_accuracy_report
        final = json.loads(final_json or "{}") if final_json else {}
        closure = json.loads(closure_json or "{}") if closure_json else {}
        return json.dumps(build_output_accuracy_report(final, closure), ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"version": "v61.0.75-correction-output-contract-and-review-index", "status": "error", "error": {"code": "output_accuracy_report_failed", "message": str(exc), "type": exc.__class__.__name__}}, ensure_ascii=False)


def validate_output_contract_json(final_json: str = "{}", payload_json: str = "{}") -> str:
    try:
        from app.parser.output_contract_validator import validate_output_contract
        final = json.loads(final_json or "{}") if final_json else {}
        payload = json.loads(payload_json or "{}") if payload_json else {}
        return json.dumps(validate_output_contract(final, payload), ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"version": "v61.0.75-correction-output-contract-and-review-index", "ok": False, "issues": [{"code": "output_contract_validation_failed", "message": str(exc), "type": exc.__class__.__name__}]}, ensure_ascii=False)

def run_real_document_regression_file_json(file_path: str, final_json: str = "{}", options_json: str = "") -> str:
    """Run v61.0.46 real-document regression checks against a PDF.

    This is a diagnostic/dev endpoint for Lovable or local HTML tests.  It does
    not mutate the parser result; it reports whether physical evidence and
    section-aware policies can prove the expected core anchors of a real PDF.
    """
    try:
        from app.parser.real_document_regression import run_real_document_regression
        final = json.loads(final_json or "{}") if final_json else {}
        options = json.loads(options_json or "{}") if options_json else {}
        report = run_real_document_regression(file_path, final, options)
        return json.dumps(report, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "error": {"code": "real_document_regression_failed", "message": str(exc), "detail": {"exception_type": exc.__class__.__name__}}}, ensure_ascii=False)



def build_extraction_coverage_report_json(final_json: str = "{}", closure_json: str = "{}") -> str:
    try:
        from app.parser.extraction_coverage import build_extraction_coverage_report
        final = json.loads(final_json or "{}") if final_json else {}
        closure = json.loads(closure_json or "{}") if closure_json else {}
        return json.dumps(build_extraction_coverage_report(final, closure), ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"version": "v61.0.75-correction-output-contract-and-review-index", "status": "error", "error": {"code": "extraction_coverage_failed", "message": str(exc), "type": exc.__class__.__name__}}, ensure_ascii=False)


def build_base_config_layering_report_json(final_json: str = "{}", options_json: str = "{}") -> str:
    try:
        from app.parser.extraction_coverage import build_base_config_layering_report
        final = json.loads(final_json or "{}") if final_json else {}
        options = json.loads(options_json or "{}") if options_json else {}
        return json.dumps(build_base_config_layering_report(final, options), ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"version": "v61.0.75-correction-output-contract-and-review-index", "status": "error", "error": {"code": "base_config_layering_report_failed", "message": str(exc), "type": exc.__class__.__name__}}, ensure_ascii=False)



def build_lovable_contract_reference_json() -> str:
    try:
        from app.pipeline.stage_registry import build_lovable_contract_reference
        return json.dumps(build_lovable_contract_reference(), ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"version": "v61.0.75-correction-output-contract-and-review-index", "status": "error", "error": {"code": "lovable_contract_reference_failed", "message": str(exc), "type": exc.__class__.__name__}}, ensure_ascii=False)

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
            "rerun_line_certainty_closure_json": True,
            "build_physical_evidence_index_file_json": True,
            "enrich_physical_evidence_index_file_json": True,
            "run_real_document_regression_file_json": True,
            "run_core_extraction_accuracy_flow_file_json": True,
            "run_output_contract_final_flow_file_json": True,
            "run_real_flow_mandatory_recovery_file_json": True,
            "organize_output_documents_json": True,
            "generate_output_accuracy_report_json": True,
            "validate_output_contract_json": True,
            "build_extraction_coverage_report_json": True,
            "build_base_config_layering_report_json": True,
            "build_lovable_contract_reference_json": True,
        },
        "version": "v61.0.75-correction-output-contract-and-review-index",
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
        return json.dumps({"version": "v61.0.75-correction-output-contract-and-review-index", "status": "error", "error": {"code": "debug_overlay_failed", "message": str(exc), "type": exc.__class__.__name__}}, ensure_ascii=False)


def generate_accuracy_report_json(actual_json: str = "{}", expected_json: str = "{}", version: str = "") -> str:
    try:
        from app.accuracy.metrics import generate_accuracy_report
        actual = json.loads(actual_json or "{}")
        expected = json.loads(expected_json or "{}")
        report = generate_accuracy_report(version or "v61.0.75-correction-output-contract-and-review-index", [{"name": "lovable_expected_result", "actual": actual, "expected": expected}])
        return json.dumps(report, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"version": "v61.0.75-correction-output-contract-and-review-index", "status": "error", "error": {"code": "accuracy_report_failed", "message": str(exc), "type": exc.__class__.__name__}}, ensure_ascii=False)
