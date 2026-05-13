from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.domain.structured_table_models import StructuredColumn, StructuredTable, StructuredTableBundle
from app.config.version import DOCLING_CONTRACT_VERSION

V59_CONTRACT = DOCLING_CONTRACT_VERSION


def _as_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _table_page_range(clean_payload: Dict[str, Any], table_key: str, table_data: Dict[str, Any], source_payload: Dict[str, Any] | None = None) -> Tuple[int, int]:
    source_payload = source_payload or {}
    ranges = dict(source_payload.get("ranges") or clean_payload.get("ranges") or {})
    seeds = dict(source_payload.get("docling_seed_pages") or clean_payload.get("docling_seed_pages") or {})
    if table_key == "budget":
        rg = dict(ranges.get("budget") or {})
        seed = seeds.get("budget") or seeds.get("budget_header_page") or 0
    else:
        rg = dict(ranges.get("compositions") or ranges.get("composition") or {})
        seed = seeds.get("composition") or seeds.get("composition_schema_page") or 0
    start = int(rg.get("start") or seed or 0)
    end = int(rg.get("end") or start or 0)
    # The structure was detected on the seed page, but applies to the whole interval.
    if start <= 0:
        start = int(seed or 0)
    if end < start:
        end = start
    return start, end


def _kind_family(table_key: str, table_data: Dict[str, Any]) -> Tuple[str, str]:
    if table_key == "budget" or str(table_data.get("kind") or "").lower() == "budget":
        return "orcamento_sintetico", "budget"
    return "composicao_sinapi_like", "sinapi_like"


def _all_physical_columns(table_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    cols: List[Dict[str, Any]] = []
    for col in list(table_data.get("columns") or []):
        item = dict(col)
        item["ignore_in_domain"] = False
        item["structural_only"] = False
        cols.append(item)
    for col in list(table_data.get("ignored_columns") or []):
        item = dict(col)
        item["ignore_in_domain"] = True
        item["structural_only"] = True
        cols.append(item)
    # Physical order matters for effective bounds.
    cols.sort(key=lambda c: (int(c.get("physical_index") if c.get("physical_index") is not None else 9999), _as_float(c.get("x0"), 1e9) or 1e9))
    return cols


def _effective_bounds(columns: List[Dict[str, Any]], *, right_padding: float = 24.0) -> Dict[int, Dict[str, float]]:
    """Build extraction boundaries using x0 anchors.

    Docling x1 is kept as raw geometry, but parser extraction works better when
    each column ends at the next physical column start. This function includes
    ignored/structural columns because they delimit text fields.
    """
    with_x = [c for c in columns if _as_float(c.get("x0")) is not None]
    with_x.sort(key=lambda c: (_as_float(c.get("x0"), 0.0) or 0.0, int(c.get("physical_index") or 0)))
    out: Dict[int, Dict[str, float]] = {}
    for idx, col in enumerate(with_x):
        physical_index = int(col.get("physical_index") or idx)
        x0 = _as_float(col.get("x0"), 0.0) or 0.0
        raw_x1 = _as_float(col.get("x1"), None)
        if idx + 1 < len(with_x):
            next_x0 = _as_float(with_x[idx + 1].get("x0"), None)
            eff_x1 = float(next_x0) if next_x0 is not None and float(next_x0) > x0 else (raw_x1 if raw_x1 and raw_x1 > x0 else x0 + 1.0)
        else:
            eff_x1 = raw_x1 if raw_x1 and raw_x1 > x0 else x0 + right_padding
            eff_x1 = max(eff_x1, x0 + 1.0)
        out[physical_index] = {"effective_x0": round(x0, 3), "effective_x1": round(float(eff_x1), 3), "effective_width": round(float(eff_x1) - x0, 3)}
    return out


def adapt_clean_docling_payload(
    payload: Dict[str, Any] | None,
    *,
    source_payload: Dict[str, Any] | None = None,
) -> StructuredTableBundle:
    """Adapt the clean v58.10+ API Docling JSON into parser StructuredTableBundle.

    The clean payload is expected to look like:
      {"version": "v58.12...", "tables": {"budget": {...}, "composition": {...}}}

    The adapter keeps the payload clean for the public API and stores raw/effective
    geometry in metadata for parser reconstruction. Ignored columns are preserved
    as structural columns so they can delimit neighboring fields.
    """
    payload = dict(payload or {})
    source_payload = dict(source_payload or {})
    tables_obj = payload.get("tables") or {}
    if isinstance(tables_obj, list):
        iterable = [(str(t.get("family") or t.get("kind") or f"table_{i}"), t) for i, t in enumerate(tables_obj)]
    else:
        iterable = [(str(k), dict(v or {})) for k, v in dict(tables_obj).items()]

    structured_tables: List[StructuredTable] = []
    for table_key, table_data in iterable:
        key_norm = "budget" if table_key in {"budget", "orcamento", "orcamento_sintetico"} else "composition"
        kind, family = _kind_family(key_norm, table_data)
        page_start, page_end = _table_page_range(payload, key_norm, table_data, source_payload)
        all_cols = _all_physical_columns(table_data)
        eff = _effective_bounds(all_cols)
        structured_columns: List[StructuredColumn] = []
        for col in all_cols:
            physical_index = int(col.get("physical_index") or 0)
            raw_x0 = _as_float(col.get("x0"), None)
            raw_x1 = _as_float(col.get("x1"), None)
            raw_width = _as_float(col.get("width"), None)
            eb = eff.get(physical_index, {})
            x0 = eb.get("effective_x0", raw_x0)
            x1 = eb.get("effective_x1", raw_x1)
            width = eb.get("effective_width", raw_width)
            metadata = {
                "source_clean_payload_version": payload.get("version"),
                "geometry_source": col.get("geometry_source") or "docling_clean_payload",
                "geometry_confidence": col.get("geometry_confidence"),
                "raw_x0": raw_x0,
                "raw_x1": raw_x1,
                "raw_width": raw_width,
                "effective_x0": x0,
                "effective_x1": x1,
                "effective_width": width,
                "ignore_in_domain": bool(col.get("ignore_in_domain")),
                "structural_only": bool(col.get("structural_only")),
            }
            structured_columns.append(StructuredColumn(
                physical_index=physical_index,
                canonical_name=str(col.get("canonical") or col.get("canonical_name") or ""),
                header_text=str(col.get("header") or col.get("header_text") or ""),
                kind="structural" if col.get("structural_only") else "mapped",
                x0=x0,
                x1=x1,
                width=width,
                confidence=float(col.get("geometry_confidence") or table_data.get("confidence") or 0.95),
                metadata=metadata,
            ))
        structured_columns.sort(key=lambda c: int(c.physical_index))
        table_id = str(table_data.get("template_id") or table_data.get("table_id") or f"{key_norm}:docling_clean")
        bbox = []
        x0s = [c.x0 for c in structured_columns if c.x0 is not None]
        x1s = [c.x1 for c in structured_columns if c.x1 is not None]
        if x0s and x1s:
            bbox = [min(x0s), 0.0, max(x1s), 0.0]
        structured_tables.append(StructuredTable(
            table_id=table_id,
            kind=kind,
            family=family,
            page_start=page_start,
            page_end=page_end,
            bbox=bbox,
            header_rows=[0],
            body_rows_start=1,
            column_schema=structured_columns,
            rows=[],
            confidence=max((float(c.confidence or 0.0) for c in structured_columns), default=0.95),
            source=str(table_data.get("source") or payload.get("source") or "docling_clean_payload"),
            metadata={
                "clean_payload_table_key": table_key,
                "grouped_headers": list(table_data.get("grouped_headers") or []),
                "ignored_columns": list(table_data.get("ignored_columns") or []),
                "warnings": list(table_data.get("warnings") or []),
                "source_version": payload.get("version"),
                "effective_bounds_rule": "x0_to_next_physical_x0",
            },
        ))
    return StructuredTableBundle(
        contract_version=str(payload.get("version") or V59_CONTRACT),
        source="docling_clean_payload",
        tables=structured_tables,
        metadata={
            "adapter": "docling_clean_adapter",
            "adapter_version": V59_CONTRACT,
            "source_payload_version": payload.get("version"),
        },
    )


def clean_payload_summary(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    payload = dict(payload or {})
    out = {"version": payload.get("version"), "tables": {}}
    for key, table in dict(payload.get("tables") or {}).items():
        table = dict(table or {})
        out["tables"][key] = {
            "kind": table.get("kind"),
            "source": table.get("source"),
            "template_id": table.get("template_id"),
            "columns": len(table.get("columns") or []),
            "ignored_columns": len(table.get("ignored_columns") or []),
            "warnings": list(table.get("warnings") or []),
        }
    return out


def _source_table_hints(source_payload: Dict[str, Any] | None) -> Dict[str, Any]:
    source_payload = dict(source_payload or {})
    tables = source_payload.get("tables")
    if isinstance(tables, dict) and tables:
        return dict(tables)
    ai_hints = dict(source_payload.get("ai_hints") or {})
    table_hints = ai_hints.get("table_hints")
    return dict(table_hints or {})


def _expected_headers_for_table(source_payload: Dict[str, Any] | None, table_key: str) -> Dict[str, Dict[str, Any]]:
    hints = _source_table_hints(source_payload)
    table = dict(hints.get(table_key) or {})
    out: Dict[str, Dict[str, Any]] = {}
    for entry in list(table.get("observed_headers") or []):
        if not isinstance(entry, dict):
            continue
        entry = dict(entry or {})
        canonical = str(entry.get("canonical") or "").strip()
        if not canonical:
            continue
        out[canonical] = entry
    return out


def _table_key_from_structured(table: StructuredTable) -> str:
    family = str(table.family or "").strip().lower()
    kind = str(table.kind or "").strip().lower()
    if family == "budget" or kind == "orcamento_sintetico":
        return "budget"
    return "composition"


def build_clean_docling_payload_from_bundle(
    bundle: StructuredTableBundle,
    *,
    source_payload: Dict[str, Any] | None = None,
    version: str = V59_CONTRACT,
) -> Dict[str, Any]:
    """Create the compact post-Docling payload consumed by the parser.

    v60.2 keeps the API light: Docling returns whatever table structure it can
    find on the seed pages. Missing columns are not fatal; the parser receives
    available_columns/missing_expected_columns/usable_for and can use the legacy
    browser parser for the missing parts while still using Docling bands for
    long text, units and numeric validation.
    """
    source_payload = dict(source_payload or {})
    clean: Dict[str, Any] = {"version": version, "tables": {}}
    for table in list(bundle.tables or []):
        key = _table_key_from_structured(table)
        expected = _expected_headers_for_table(source_payload, key)
        table_hints = _source_table_hints(source_payload).get(key) or {}
        expected_order = [
            str(x.get("canonical") or "").strip()
            for x in list(table_hints.get("observed_headers") or [])
            if isinstance(x, dict) and str(x.get("canonical") or "").strip()
        ]
        expected_by_index = {idx: canonical for idx, canonical in enumerate(expected_order)}
        first_samples = list(table_hints.get('first_row_samples') or table_hints.get('first_content_samples') or [])
        first_samples_by_index = {idx: (item if isinstance(item, dict) else {'sample_text': item}) for idx, item in enumerate(first_samples)}
        seen: set[str] = set()
        columns: List[Dict[str, Any]] = []
        ignored: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = list(table.metadata.get("warnings") or [])
        for col in sorted(list(table.column_schema or []), key=lambda c: int(c.physical_index)):
            physical_index = int(col.physical_index)
            raw_canonical = str(col.canonical_name or "").strip()
            canonical = raw_canonical
            # If Docling/semantic mapper produced an old or unknown alias, prefer
            # the IA-declared canonical at the same physical index. This avoids
            # polluted aliases such as custo_unit_com_bdi without hardcoding names.
            if canonical not in expected and physical_index in expected_by_index:
                canonical = expected_by_index[physical_index]
                warnings.append({
                    "code": "canonical_recovered_by_payload_order",
                    "physical_index": physical_index,
                    "from": raw_canonical,
                    "to": canonical,
                })
            if not canonical:
                continue
            hint = dict(expected.get(canonical) or {})
            ignore = bool(hint.get("ignore_in_domain") or (col.metadata or {}).get("ignore_in_domain"))
            item: Dict[str, Any] = {
                "canonical": canonical,
                "header": str(hint.get("text") or hint.get("header_text") or col.header_text or canonical),
                "header_text": str(hint.get("header_text") or hint.get("text") or col.header_text or canonical),
                "sample_text": str(hint.get("sample_text") or hint.get("content_text") or hint.get("first_row_text") or hint.get("first_content_text") or first_samples_by_index.get(physical_index, {}).get("sample_text") or ""),
                "content_text": str(hint.get("content_text") or hint.get("sample_text") or hint.get("first_row_text") or first_samples_by_index.get(physical_index, {}).get("content_text") or first_samples_by_index.get(physical_index, {}).get("sample_text") or ""),
                "physical_index": physical_index,
            }
            if col.x0 is not None:
                item["x0"] = round(float(col.x0), 3)
            if col.x1 is not None:
                item["x1"] = round(float(col.x1), 3)
            if col.width is not None:
                item["width"] = round(float(col.width), 3)
            item["geometry_source"] = str((col.metadata or {}).get("geometry_source") or table.source or bundle.source or "docling")
            item["geometry_confidence"] = round(float((col.metadata or {}).get("geometry_confidence") or col.confidence or table.confidence or 0.0), 3)
            seen.add(canonical)
            if ignore:
                ignored.append(item)
            else:
                columns.append(item)
        expected_non_ignored = [c for c in expected_order if not bool((expected.get(c) or {}).get("ignore_in_domain"))]
        expected_all = list(expected_order)
        found_all = sorted(seen, key=lambda c: expected_all.index(c) if c in expected_all else 999)
        missing_all = [c for c in expected_all if c not in seen]
        missing_non_ignored = [c for c in expected_non_ignored if c not in seen]
        usable_for = [c for c in found_all if c not in missing_all]
        partial_structure = bool(missing_all)
        if partial_structure:
            warnings.append({
                "code": "partial_docling_structure",
                "missing_expected_columns": missing_all,
                "usable_for": usable_for,
                "action": "parser_should_use_available_bands_and_legacy_fallback_for_missing_columns",
            })
        table_payload = {
            "kind": key,
            "source": str(table.source or bundle.source or "docling"),
            "template_id": table.table_id,
            "partial_structure": partial_structure,
            "available_columns": found_all,
            "missing_expected_columns": missing_all,
            "missing_domain_columns": missing_non_ignored,
            "usable_for": usable_for,
            "columns": columns,
            "ignored_columns": ignored,
            "grouped_headers": list(table_hints.get("header_groups") or table_hints.get("grouped_headers") or table.metadata.get("grouped_headers") or []),
            "warnings": warnings,
        }
        clean["tables"][key] = table_payload
    clean["runtime"] = dict(bundle.metadata.get("runtime") or {})
    clean["docling_trace"] = dict(bundle.metadata.get("docling_trace") or {})
    clean.setdefault("metadata", {})
    clean["metadata"].update({
        "api_mode": "seed_pages_light",
        "structure_only": True,
        "docling_scope": "seed_pages_only",
        "parser_expected_to_process_full_ranges": True,
    })
    return clean
