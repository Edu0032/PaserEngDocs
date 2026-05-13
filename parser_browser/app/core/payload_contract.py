from __future__ import annotations

from typing import Any, Dict, List

DOC_VARIABLE_TABLE_KEYS = {
    "observed_headers",
    "headers_observed",
    "header_rows_observed",
    "multiline_header",
    "physical_column_count_expected",
    "logical_column_count_expected",
    "domain_column_count_expected",
    "table_parent_header",
    "first_row_samples",
    "first_content_samples",
    "header_groups",
    "grouped_headers",
    "non_column_context",
    "header_noise_terms",
    "control_column",
}

FIXED_PAYLOAD_KEYS = {
    "fixed_contract",
    "parser_contract",
    "runtime",
    "post_api_integration",
    "docling_clean_payload",
    "normalizer_clean_payload",
    "normalizer_report",
    "docling_api_key",
    "docling_api_url",
    "normalizer_api_key",
    "normalizer_api_url",
    "docling_timeout_ms",
    "normalizer_timeout_ms",
    "normalizer_enabled",
    "normalizer_mode",
    "docling_seed_pdf_policy",
    "request_timeout_ms",
    "bypass_cache",
    "clear_docling_cache_before_run",
    "performance",
    "output_options",
}


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if value == "":
        return False
    if isinstance(value, (list, tuple, set, dict)) and len(value) == 0:
        return False
    return True


def clean_table_hints_for_docling(tables: Dict[str, Any] | None) -> Dict[str, Any]:
    """Keep only document-variable context useful to Docling.

    The IA/Lovable payload should keep the observed PDF header -> canonical
    association, plus samples from the first real data row. Parser execution
    rules, regexes, retry policies and output policies belong to base_config and
    must not be forwarded as Docling guidance.
    """
    cleaned: Dict[str, Any] = {}
    for key, raw in dict(tables or {}).items():
        if not isinstance(raw, dict):
            continue
        item: Dict[str, Any] = {}
        for k in DOC_VARIABLE_TABLE_KEYS:
            if k in raw and _is_present(raw.get(k)):
                item[k] = raw.get(k)
        # Preserve header <-> canonical mapping in common Lovable shapes.
        cols = raw.get("columns") or raw.get("observed_columns") or raw.get("canonical_columns")
        if not isinstance(cols, list):
            cols = raw.get("observed_headers") or raw.get("headers_observed") or []
        if isinstance(cols, list):
            kept_cols: List[Dict[str, Any]] = []
            for col in cols:
                if not isinstance(col, dict):
                    continue
                kept = {}
                # observed_headers usually use text/header_text instead of header.
                if col.get("text") not in (None, "") and col.get("header") in (None, ""):
                    kept["header"] = col.get("text")
                for ck in ("canonical", "canonical_name", "header", "header_text", "observed_header", "text", "sample_text", "content_text", "first_row_sample", "first_row_text"):
                    if col.get(ck) not in (None, ""):
                        kept[ck] = col.get(ck)
                if kept:
                    kept_cols.append(kept)
            if kept_cols:
                item["columns"] = kept_cols
        if item:
            item.setdefault("source", raw.get("source") or "lovable_document_context")
            cleaned[str(key)] = item
    return cleaned


def payload_usage_report(payload: Dict[str, Any] | None, tables: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = dict(payload or {})
    tables = clean_table_hints_for_docling(tables if tables is not None else payload.get("tables") or {})
    table_usage = {}
    for key, tbl in tables.items():
        headers = tbl.get("observed_headers") or tbl.get("headers_observed") or []
        samples = tbl.get("first_row_samples") or tbl.get("first_content_samples") or []
        columns = tbl.get("columns") or []
        header_maps_raw = list(headers if isinstance(headers, list) else []) + list(columns if isinstance(columns, list) else [])
        seen_maps = set(); header_maps = []
        for c in header_maps_raw:
            if not isinstance(c, dict):
                continue
            marker = (str(c.get("canonical") or c.get("canonical_name") or ""), str(c.get("header") or c.get("header_text") or c.get("observed_header") or c.get("text") or ""))
            if marker in seen_maps:
                continue
            seen_maps.add(marker); header_maps.append(c)
        canonical_maps = [c for c in header_maps if isinstance(c, dict) and (c.get("canonical") or c.get("canonical_name"))]
        first_row_marks = [c for c in header_maps if isinstance(c, dict) and (c.get("sample_text") or c.get("content_text") or c.get("first_row_sample") or c.get("first_row_text"))]
        table_usage[key] = {
            "headers_used": bool(headers or columns),
            "first_row_samples_used": bool(samples or first_row_marks),
            "canonical_mapping_used": bool(canonical_maps),
            "observed_header_count": len(headers) if isinstance(headers, list) else 0,
            "first_row_sample_count": (len(samples) if isinstance(samples, list) else 0) + len(first_row_marks),
            "column_mapping_count": len(canonical_maps),
        }
    return {
        "payload_contract": "doc_variable_context_only",
        "fixed_keys_detected": sorted([k for k in FIXED_PAYLOAD_KEYS if _is_present(payload.get(k))]),
        "fixed_keys_forwarded_to_docling": [],
        "tables": table_usage,
    }



def split_lovable_document_and_runtime_payload(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    """Return the official separation: document semantics vs runtime config."""
    payload = dict(payload or {})
    document_keys = {"base_id", "document", "ranges", "seed_pages", "docling_seed_pages", "tables", "observed_tables", "document_hints", "ai_hints", "metadata_extraida_ia"}
    runtime_keys = set(FIXED_PAYLOAD_KEYS)
    return {
        "document_payload": {k: v for k, v in payload.items() if k in document_keys},
        "runtime_config": {k: v for k, v in payload.items() if k in runtime_keys and _is_present(v)},
        "ignored_unknown_keys": sorted([k for k in payload.keys() if k not in document_keys and k not in runtime_keys]),
    }

def validate_lovable_payload_contract(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    payload = dict(payload or {})
    warnings = []
    errors = []
    ranges = payload.get("ranges") if isinstance(payload.get("ranges"), dict) else {}
    if not (ranges.get("budget") and ranges.get("compositions")):
        errors.append({"code": "missing_ranges", "message": "Payload deve informar ranges.budget e ranges.compositions."})
    seed = payload.get("seed_pages") or payload.get("docling_seed_pages")
    if not isinstance(seed, dict):
        errors.append({"code": "missing_seed_pages", "message": "Payload deve informar seed_pages/docling_seed_pages."})
    fixed = sorted([k for k in FIXED_PAYLOAD_KEYS if _is_present(payload.get(k))])
    if fixed:
        warnings.append({"code": "fixed_keys_should_live_in_base_config", "keys": fixed, "message": "Essas chaves são aceitas por compatibilidade, mas não devem ser pedidas à IA nem enviadas ao Docling."})
    tables = payload.get("tables") or payload.get("observed_tables") or {}
    cleaned = clean_table_hints_for_docling(tables if isinstance(tables, dict) else {})
    if not cleaned:
        warnings.append({"code": "missing_docling_table_context", "message": "Sem headers observados/canônicos/samples, Docling terá menos contexto."})
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "docling_table_context": cleaned,
        "payload_usage": payload_usage_report(payload, cleaned),
    }
