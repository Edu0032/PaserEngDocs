from __future__ import annotations

"""Central evidence registry for final public JSON.

The parser has several independent evidence producers (physical PDF index,
public numeric evidence, token fidelity, banded closure, budget ownership, and
line/recovery reports).  This module does not extract or invent values.  It
consolidates their outputs into one compact registry so every final-flow tool
and Lovable can inspect the same evidence state.

Global policy, no document-specific hardcode:
- public financial fields should be explainable from physical/evidence reports;
- evidence from earlier tools is preserved and normalized into a common shape;
- the registry is advisory unless quality-gate rules decide a missing evidence
  item is blocking;
- SICRO native engine remains untouched; this registry only records what exists.
"""

from typing import Any, Dict, Iterable, List, Tuple

from app.config.version import CURRENT_RELEASE


_FIELD_KINDS = {
    "quant": "quantity",
    "valor_unit": "unit_price",
    "total": "row_total",
    "custo_unitario_sem_bdi": "budget_unit_without_bdi",
    "custo_unitario_com_bdi": "budget_unit_with_bdi",
    "custo_parcial": "budget_partial",
    "custo_total": "budget_group_total",
    "und": "unit",
}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def _status_of(entry: Dict[str, Any]) -> str:
    ev = entry.get("evidence") if isinstance(entry.get("evidence"), dict) else {}
    status = _clean(ev.get("status") or entry.get("evidence_status"))
    if status:
        return status
    if ev and ev.get("source"):
        return "found"
    return "unknown"


def _entry_from_public_numeric(entry: Dict[str, Any]) -> Dict[str, Any]:
    evidence = entry.get("evidence") if isinstance(entry.get("evidence"), dict) else {}
    status = _status_of(entry)
    field = _clean(entry.get("field"))
    return {
        "path": _clean(entry.get("path")),
        "field": field,
        "field_kind": _FIELD_KINDS.get(field, "other"),
        "value": _clean(entry.get("value")),
        "entity": _clean(entry.get("entity")),
        "section": _clean(evidence.get("section") or entry.get("section")),
        "page": evidence.get("page") or entry.get("page"),
        "source": _clean(evidence.get("source") or entry.get("source") or "public_numeric_evidence"),
        "status": status,
        "confidence": evidence.get("confidence") if evidence.get("confidence") is not None else entry.get("confidence"),
        "anchor": evidence.get("anchor"),
        "anchor_value": evidence.get("anchor_value"),
        "line_text": evidence.get("line_text"),
        "block": entry.get("block"),
        "row_group": entry.get("row_group"),
        "row_index": entry.get("row_index"),
        "codigo": entry.get("codigo"),
        "banco": entry.get("banco"),
        "producer": "public_numeric_evidence",
    }


def _entry_from_patch(patch: Dict[str, Any], producer: str) -> Dict[str, Any]:
    field = _clean(patch.get("field"))
    ev = patch.get("evidence") if isinstance(patch.get("evidence"), dict) else {}
    hit = ev.get("hit") if isinstance(ev.get("hit"), dict) else {}
    return {
        "path": _clean(patch.get("path")),
        "field": field,
        "field_kind": _FIELD_KINDS.get(field, "other"),
        "value": _clean(patch.get("value")),
        "previous_value": _clean(patch.get("previous_value")),
        "entity": "composicao_sinapi_like" if patch.get("block") else "unknown",
        "section": _clean(hit.get("section") or patch.get("section") or "composicoes_analiticas"),
        "page": hit.get("page") or patch.get("page"),
        "source": _clean(patch.get("source") or producer),
        "status": "applied_patch",
        "confidence": patch.get("confidence") or hit.get("confidence"),
        "line_text": hit.get("text") or patch.get("line_text"),
        "block": patch.get("block"),
        "row_group": patch.get("row_group"),
        "row_index": patch.get("row_index"),
        "codigo": patch.get("codigo"),
        "banco": patch.get("banco"),
        "producer": producer,
    }


def _flatten_public_numeric_fields(evid: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = evid.get("public_numeric_fields")
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def _closure_rows(evid: Dict[str, Any]) -> List[Dict[str, Any]]:
    root = evid.get("composition_banded_closure") if isinstance(evid.get("composition_banded_closure"), dict) else {}
    rows: List[Dict[str, Any]] = []
    for block in root.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        for row in block.get("rows") or []:
            if not isinstance(row, dict):
                continue
            rows.append({
                "block": block.get("block"),
                "collection": block.get("collection"),
                "row_id": row.get("row_id"),
                "row_group": row.get("row_group"),
                "row_index": row.get("row_index"),
                "codigo": row.get("codigo"),
                "status": row.get("status"),
                "missing": row.get("missing") or [],
                "producer": "composition_banded_closure",
            })
    return rows


def apply_evidence_registry(result: Dict[str, Any], options: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    options = options or {}
    evid = result.setdefault("documento_evidencias", {})
    if not isinstance(evid, dict):
        result["documento_evidencias"] = evid = {}

    entries: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, str, str, str]] = set()

    def add(entry: Dict[str, Any]) -> None:
        if not isinstance(entry, dict):
            return
        key = (
            _clean(entry.get("path")),
            _clean(entry.get("field")),
            _clean(entry.get("value")),
            _clean(entry.get("producer")),
            _clean(entry.get("status")),
        )
        if key in seen:
            return
        seen.add(key)
        entries.append(entry)

    for item in _flatten_public_numeric_fields(evid):
        add(_entry_from_public_numeric(item))

    for p in evid.get("public_token_fidelity_patches") or []:
        if isinstance(p, dict):
            add(_entry_from_patch(p, "public_token_fidelity"))

    cascade = evid.get("cascade_repairs") if isinstance(evid.get("cascade_repairs"), dict) else {}
    for p in cascade.get("applied_repairs") or []:
        if isinstance(p, dict):
            add(_entry_from_patch(p, "cascade_repair"))

    tail_patches = evid.get("physical_numeric_tail_recovery_patches") or evid.get("physical_numeric_tail_patches") or []
    for p in tail_patches or []:
        if isinstance(p, dict):
            add(_entry_from_patch(p, "physical_numeric_tail_recovery"))

    # Many real-flow tools keep compact patch reports under meta.performance to
    # avoid duplicating large payloads in documento_evidencias.  Pull those
    # reports into the central registry so the final JSON has one evidence view.
    perf = ((result.get("meta") or {}).get("performance") or {}) if isinstance(result.get("meta"), dict) else {}
    for key, rep in list(perf.items()) if isinstance(perf, dict) else []:
        if not isinstance(rep, dict):
            continue
        if key.startswith("physical_numeric_tail_recovery") or key.startswith("public_token_fidelity"):
            producer = "physical_numeric_tail_recovery" if key.startswith("physical_numeric_tail") else "public_token_fidelity"
            for pch in rep.get("patches") or []:
                if isinstance(pch, dict):
                    add(_entry_from_patch(pch, producer))
        # The orchestrator nests stage reports; inspect them without assuming a
        # document-specific stage name.
        for stage in rep.get("stages") or []:
            if not isinstance(stage, dict):
                continue
            name = str(stage.get("name") or "")
            srep = stage.get("report") if isinstance(stage.get("report"), dict) else {}
            if name in {"physical_numeric_tail_recovery", "public_token_fidelity"}:
                for pch in srep.get("patches") or []:
                    if isinstance(pch, dict):
                        add(_entry_from_patch(pch, name))

    closure_rows = _closure_rows(evid)
    status_counts: Dict[str, int] = {}
    for e in entries:
        st = _clean(e.get("status") or "unknown")
        status_counts[st] = status_counts.get(st, 0) + 1

    primary = [e for e in entries if e.get("status") in {"found", "applied_patch", "primary_physical_match"} or e.get("source") == "pdf_physical_text"]
    missing = [e for e in entries if e.get("status") in {"not_found", "missing", "unknown"}]
    field_count = sum(1 for e in entries if e.get("field") in _FIELD_KINDS)

    registry = {
        "version": CURRENT_RELEASE,
        "policy": "central_registry_for_all_final_flow_evidence_producers",
        "entry_count": len(entries),
        "field_entry_count": field_count,
        "primary_physical_entry_count": len(primary),
        "missing_or_unknown_entry_count": len(missing),
        "status_counts": status_counts,
        "field_registry": entries[:2500],
        "row_lock_registry": closure_rows[:2500],
        "row_lock_count": len(closure_rows),
        "locked_row_count": sum(1 for r in closure_rows if r.get("status") == "locked"),
        "open_row_count": sum(1 for r in closure_rows if r.get("status") != "locked"),
    }
    evid["evidence_registry"] = registry
    result.setdefault("meta", {}).setdefault("performance", {})["evidence_registry"] = {k: v for k, v in registry.items() if k not in {"field_registry", "row_lock_registry"}}
    result.setdefault("documento_correcao", {})["evidence_registry"] = {k: v for k, v in registry.items() if k not in {"field_registry", "row_lock_registry"}}
    return registry
