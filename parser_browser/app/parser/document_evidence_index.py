from __future__ import annotations

"""Document Evidence Index (v61.0.41).

Builds one normalized, in-memory index of evidence that is already present in the
parsed result/ledger.  The heavy PDF sweep can later enrich the same key space,
but the closure engine can already use this index to avoid repeatedly scanning
row lists and to make field consensus decisions by codigo+banco.

This module deliberately does not open PDFs and does not duplicate the SICRO-only
engine.  SICRO evidence is indexed only as evidence produced by its own pipeline.
"""

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Tuple

VERSION = "v61.0.75-correction-output-contract-and-review-index"

PUBLIC_FIELDS = (
    "descricao",
    "especificacao",
    "und",
    "quant",
    "valor_unit",
    "total",
    "custo_unitario_sem_bdi",
    "custo_unitario_com_bdi",
    "custo_parcial",
    "custo_total",
    "codigo",
    "banco",
    "fonte",
)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def _norm_bank(value: Any) -> str:
    text = _clean(value).upper()
    return "PROPRIO" if text == "PRÓPRIO" else text


def code_bank_key(codigo: Any, banco: Any) -> str:
    code = _clean(codigo)
    bank = _norm_bank(banco)
    return f"{code}|{bank}" if code else ""


def _row_key(row: Any) -> str:
    try:
        key = getattr(row, "key", "")
        if key:
            # Normalize only the bank side when possible.
            if "|" in str(key):
                code, bank = str(key).split("|", 1)
                return code_bank_key(code, bank)
            return str(key)
        data = getattr(row, "row", {}) or {}
        return code_bank_key(data.get("codigo"), data.get("banco") or data.get("fonte"))
    except Exception:
        return ""


def _value_for(row: Any, field: str) -> Any:
    data = getattr(row, "row", {}) or {}
    if not isinstance(data, dict):
        return None
    if field == "descricao" and not data.get("descricao"):
        return data.get("especificacao")
    if field == "especificacao" and not data.get("especificacao"):
        return data.get("descricao")
    return data.get(field)


def _row_status_map(closure_rows: Iterable[Dict[str, Any]] | None) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for record in closure_rows or []:
        if isinstance(record, dict) and record.get("row_id"):
            out[str(record.get("row_id"))] = str(record.get("row_status") or "")
    return out


def build_document_evidence_index(rows: Iterable[Any], ledger: Any = None, *, closure_rows: Iterable[Dict[str, Any]] | None = None, limit_per_key: int = 80) -> Dict[str, Any]:
    """Build a compact evidence index grouped by codigo+banco.

    ``rows`` are ClosureRow-like objects from the main closure engine.  ``ledger``
    is optional and can contribute cross/extracted evidence already registered by
    previous steps.
    """
    status_by_row = _row_status_map(closure_rows)
    by_key: Dict[str, Dict[str, Any]] = {}
    field_counts: Dict[Tuple[str, str, str], int] = defaultdict(int)

    for r in list(rows or []):
        key = _row_key(r)
        if not key:
            continue
        bucket = by_key.setdefault(key, {"key": key, "occurrences": [], "fields": defaultdict(list), "families": defaultdict(int), "pages": set()})
        row_data = getattr(r, "row", {}) or {}
        row_id = str(getattr(r, "row_id", "") or "")
        occurrence = {
            "row_id": row_id,
            "family": str(getattr(r, "family", "") or ""),
            "collection": str(getattr(r, "collection", "") or ""),
            "group": str(getattr(r, "group", "") or ""),
            "path": list(getattr(r, "path", []) or []),
            "page": getattr(r, "page", None),
            "item": str(getattr(r, "item", "") or ""),
            "closed_status": status_by_row.get(row_id, "unknown"),
            "source": "existing_extraction",
        }
        if len(bucket["occurrences"]) < limit_per_key:
            bucket["occurrences"].append(occurrence)
        bucket["families"][occurrence["family"]] += 1
        if occurrence["page"] is not None:
            try:
                bucket["pages"].add(int(occurrence["page"]))
            except Exception:
                pass
        for field in PUBLIC_FIELDS:
            value = _value_for(r, field)
            if value in (None, ""):
                continue
            norm_value = _clean(value)
            if not norm_value:
                continue
            source = f"existing_extraction:{occurrence['family']}:{occurrence['collection']}:{occurrence['group']}"
            if occurrence["closed_status"] == "closed_100":
                source = "locked_closed_row_evidence"
            record = {
                "field": field,
                "value": norm_value,
                "row_id": row_id,
                "family": occurrence["family"],
                "collection": occurrence["collection"],
                "group": occurrence["group"],
                "path": occurrence["path"] + [field],
                "page": occurrence["page"],
                "source": source,
                "confidence": 0.96 if occurrence["closed_status"] == "closed_100" else 0.86,
            }
            dedupe_key = (key, field, norm_value)
            field_counts[dedupe_key] += 1
            if len(bucket["fields"][field]) < limit_per_key:
                bucket["fields"][field].append(record)

    # Optional ledger contribution.  The ledger structure is intentionally used
    # defensively because older versions may change serialization details.
    try:
        ledger_dump = ledger.as_dict(limit=1000) if ledger is not None and hasattr(ledger, "as_dict") else {}
        evidence_items = ledger_dump.get("evidence") or ledger_dump.get("items") or []
        if isinstance(evidence_items, dict):
            iterable = []
            for key, fields in evidence_items.items():
                for field, items in (fields or {}).items():
                    for item in items or []:
                        iterable.append({"key": key, "field": field, **(item if isinstance(item, dict) else {})})
        else:
            iterable = evidence_items if isinstance(evidence_items, list) else []
        for ev in iterable:
            if not isinstance(ev, dict):
                continue
            key = str(ev.get("key") or ev.get("codebank") or "")
            if key and "|" in key:
                code, bank = key.split("|", 1)
                key = code_bank_key(code, bank)
            field = str(ev.get("field") or "")
            value = _clean(ev.get("value"))
            if not key or not field or not value:
                continue
            bucket = by_key.setdefault(key, {"key": key, "occurrences": [], "fields": defaultdict(list), "families": defaultdict(int), "pages": set()})
            record = {"field": field, "value": value, "source": ev.get("source") or "field_evidence_ledger", "path": ev.get("path") or [], "confidence": float(ev.get("confidence") or 0.82)}
            if len(bucket["fields"][field]) < limit_per_key:
                bucket["fields"][field].append(record)
    except Exception:
        pass

    keys_out: Dict[str, Any] = {}
    total_occurrences = 0
    for key, bucket in by_key.items():
        field_summary: Dict[str, Any] = {}
        for field, records in (bucket.get("fields") or {}).items():
            values: Dict[str, Dict[str, Any]] = {}
            for rec in records:
                val = _clean(rec.get("value"))
                if not val:
                    continue
                current = values.setdefault(val, {"value": val, "count": 0, "sources": [], "pages": set(), "max_confidence": 0.0, "records": []})
                current["count"] += 1
                current["sources"].append(str(rec.get("source") or ""))
                if rec.get("page") is not None:
                    try:
                        current["pages"].add(int(rec.get("page")))
                    except Exception:
                        pass
                current["max_confidence"] = max(float(current.get("max_confidence") or 0.0), float(rec.get("confidence") or 0.0))
                if len(current["records"]) < 12:
                    current["records"].append(rec)
            normalized_values = []
            for data in values.values():
                pages = sorted(data.pop("pages"))
                data["pages"] = pages
                data["source_count"] = len(set(s for s in data.get("sources", []) if s))
                normalized_values.append(data)
            normalized_values.sort(key=lambda d: (d.get("count", 0), d.get("source_count", 0), d.get("max_confidence", 0.0)), reverse=True)
            field_summary[field] = {"values": normalized_values[:20], "candidate_count": len(records)}
        occ = list(bucket.get("occurrences") or [])
        total_occurrences += len(occ)
        keys_out[key] = {
            "key": key,
            "occurrences": occ[:limit_per_key],
            "occurrence_count": len(occ),
            "families": dict(bucket.get("families") or {}),
            "pages": sorted(bucket.get("pages") or []),
            "fields": field_summary,
        }

    return {
        "version": VERSION,
        "mode": "global_extracted_document_evidence_index",
        "key_count": len(keys_out),
        "occurrence_count": total_occurrences,
        "keys": keys_out,
    }


def compact_index_report(index: Dict[str, Any], *, max_keys: int = 40) -> Dict[str, Any]:
    keys = index.get("keys") if isinstance(index, dict) else {}
    sample = {}
    for key, bucket in list((keys or {}).items())[:max_keys]:
        sample[key] = {
            "occurrence_count": bucket.get("occurrence_count"),
            "families": bucket.get("families"),
            "pages": bucket.get("pages"),
            "fields": {f: {"candidate_count": d.get("candidate_count"), "top": (d.get("values") or [])[:3]} for f, d in (bucket.get("fields") or {}).items()},
        }
    return {
        "version": VERSION,
        "mode": index.get("mode"),
        "key_count": index.get("key_count", 0),
        "occurrence_count": index.get("occurrence_count", 0),
        "sample_keys": sample,
    }
