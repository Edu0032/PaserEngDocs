from __future__ import annotations

"""Output contract validator for Lovable (v61.0.57)."""

from typing import Any, Dict, List

VERSION = "v61.0.75-correction-output-contract-and-review-index"

FORBIDDEN_PAYLOAD_KEYS = {
    "docling_api_url", "docling_api_key", "docling_timeout_ms", "normalizer_api_url",
    "normalizer_api_key", "bypass_cache", "clear_docling_cache_before_run",
    "targeted_recovery_max_pages_per_batch", "runtime", "performance", "output_options",
    "parser_contract", "fixed_contract", "docling_execution_policy", "geometry_normalizer",
    "template_merge_policy", "crop_policy", "header_window_policy", "ocr_enabled",
}


def _as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _walk_dict_keys(value: Any, path: str = ""):
    if isinstance(value, dict):
        for k, v in value.items():
            p = f"{path}.{k}" if path else str(k)
            yield p, str(k)
            yield from _walk_dict_keys(v, p)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk_dict_keys(v, f"{path}[{i}]")


def validate_output_contract(final_result: Dict[str, Any] | None, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    final = final_result if isinstance(final_result, dict) else {}
    issues: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    for key, expected_type in (
        ("orcamento_sintetico", dict),
        ("composicoes", dict),
        ("documento_correcao", dict),
        ("documento_evidencias", dict),
        ("documento_enriquecimento", dict),
        ("analise_orcamentaria", dict),
    ):
        if not isinstance(final.get(key), expected_type):
            issues.append({"code": "missing_or_invalid_output_section", "path": key, "expected": expected_type.__name__})

    enrich = _as_dict(final.get("documento_enriquecimento"))
    if enrich and enrich.get("document_type") not in {"documento_enriquecimento", "enrichment_document", None}:
        warnings.append({"code": "enrichment_document_type_unexpected", "value": enrich.get("document_type")})
    if enrich and _as_dict(enrich.get("approval_policy")).get("auto_apply_to_base_config") is not False:
        issues.append({"code": "enrichment_auto_apply_not_disabled"})
    evidence = _as_dict(final.get("documento_evidencias"))
    if evidence and evidence.get("document_type") not in {"documento_evidencias", "evidence_document", None}:
        warnings.append({"code": "evidence_document_type_unexpected", "value": evidence.get("document_type")})
    analysis = _as_dict(final.get("analise_orcamentaria"))
    if not isinstance(analysis.get("entity_confidence_report"), dict):
        warnings.append({"code": "missing_entity_confidence_report", "policy": "v53 recomenda expor confiança por entidade para Lovable, mas isso não bloqueia o JSON"})

    # Check role separation. Evidence details should not be inside enrichment.
    for forbidden in ("applied_repairs", "cascade_repairs", "math_field_summary", "source_of_truth_policy"):
        if forbidden in enrich:
            issues.append({"code": "evidence_data_inside_enrichment", "field": forbidden})

    payload_issues: List[Dict[str, Any]] = []
    if isinstance(payload, dict):
        for path, key in _walk_dict_keys(payload):
            if key in FORBIDDEN_PAYLOAD_KEYS:
                payload_issues.append({"path": path, "key": key, "policy": "runtime/admin config belongs in base_config or worker options, not document payload"})
    # v61.0.57: stable output schema metadata.  These are warnings, not
    # blockers, because older saved results may not have the envelope yet.
    expected_doc_types = {
        "documento_correcao": "documento_correcao",
        "documento_evidencias": "evidence_document",
        "documento_enriquecimento": "enrichment_document",
        "analise_orcamentaria": "analytics_document",
    }
    for path, expected in expected_doc_types.items():
        obj = _as_dict(final.get(path))
        if obj and obj.get("schema_version") not in {"outputs.v1", None}:
            warnings.append({"code": "unexpected_schema_version", "path": path, "value": obj.get("schema_version")})
        if obj and obj.get("document_type") not in {expected, path, None}:
            warnings.append({"code": "unexpected_document_type", "path": path, "expected": expected, "value": obj.get("document_type")})
    if not isinstance(_as_dict(_as_dict(final.get("analise_orcamentaria")).get("outputs_package_manifest")).get("documents"), list):
        warnings.append({"code": "missing_outputs_package_manifest", "policy": "v56 recomenda manifesto de pacote para Lovable baixar/consumir outputs"})

    ok = not issues and not payload_issues
    return {
        "version": VERSION,
        "schema_version": "outputs.v1",
        "ok": ok,
        "issues": issues,
        "warnings": warnings,
        "payload_boundary": {
            "ok": not payload_issues,
            "forbidden_runtime_or_admin_keys": payload_issues[:80],
            "policy": "payload carrega apenas informações do documento; base_config carrega regras fixas/admin/runtime",
        },
        "required_sections_present": {k: isinstance(final.get(k), dict) for k in ("orcamento_sintetico", "composicoes", "documento_correcao", "documento_evidencias", "documento_enriquecimento", "analise_orcamentaria")},
    }
