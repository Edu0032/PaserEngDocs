from __future__ import annotations

"""Selective Field Reparse Executor.

This module is deliberately conservative.  It does not try to replace the
PyMuPDF targeted recovery; instead it runs a document-wide, evidence-only pass
that can safely repair weak description fields using already extracted facts.
Any remaining weak fields are emitted as surgical reparse targets for the
local recovery engine.
"""

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Tuple

from app.parser.broken_line_recovery import (
    codebank,
    is_sicro_bank,
    is_truncated_text,
    pollution_reason,
    similarity,
    text_quality_score,
)
from app.parser.code_value_classifier import clean_text, norm_text
from app.parser.description_ownership_resolver import (
    ownership_report,
    choose_clean_subcandidate_from_current,
)

VERSION = "v61.0.35-candidate-profile-consensus-engine"

DESCRIPTION_FIELDS = {"descricao", "especificacao"}
CONNECTOR_TAILS = {"DE", "DA", "DO", "DAS", "DOS", "PARA", "COM", "E", "EM", "A", "O", "AO"}


@dataclass
class RowRef:
    path: List[Any]
    row: Dict[str, Any]
    field: str
    family: str
    source: str
    codigo: str = ""
    banco: str = ""
    item: str = ""
    page: int | None = None
    neighbor_context: Dict[str, Any] = field(default_factory=dict)

    @property
    def current(self) -> str:
        return _clean(self.row.get(self.field) or self.row.get("descricao") or self.row.get("especificacao") or "")

    @property
    def key(self) -> str:
        return codebank(self.codigo, self.banco)


@dataclass
class EvidenceCandidate:
    descricao: str
    key: str
    sources: List[str] = field(default_factory=list)
    paths: List[List[Any]] = field(default_factory=list)
    occurrences: int = 0
    quality: float = 0.0

    def add(self, source: str, path: List[Any], quality: float) -> None:
        self.occurrences += 1
        self.sources.append(source)
        self.paths.append(list(path))
        self.quality = max(self.quality, quality)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "descricao": self.descricao,
            "occurrences": self.occurrences,
            "sources": self.sources[:8],
            "quality": round(self.quality, 4),
            "confirmed": is_confirmed_candidate(self),
        }


def _clean(value: Any) -> str:
    return clean_text(value)


def _field_value(row: Dict[str, Any], field: str) -> str:
    return _clean(row.get(field) or row.get("descricao") or row.get("especificacao") or "")


def _is_weak_description(value: Any) -> str:
    text = _clean(value)
    if not text:
        return "empty"
    if text.lstrip().startswith("-"):
        return "polluted:leading_orphan_fragment"
    if norm_text(text).count("AF_") >= 2:
        return "polluted:multiple_service_anchors"
    polluted = pollution_reason(text)
    if polluted:
        return f"polluted:{polluted}"
    tail = (norm_text(text).split() or [""])[-1]
    if tail in CONNECTOR_TAILS:
        return "ends_with_connector"
    if is_truncated_text(text):
        return "truncated"
    return ""


def _candidate_clean_enough(text: Any) -> Tuple[bool, str]:
    value = _clean(text)
    if not value:
        return False, "empty_candidate"
    if value.lstrip().startswith("-"):
        return False, "leading_orphan_fragment"
    if norm_text(value).count("AF_") >= 2:
        return False, "multiple_service_anchors"
    reason = pollution_reason(value)
    if reason:
        return False, reason
    if len(value) < 3:
        return False, "too_short"
    return True, ""


def _long_risk(current: str, candidate: str) -> bool:
    current = _clean(current)
    candidate = _clean(candidate)
    if not current or not candidate:
        return False
    if norm_text(candidate).startswith(norm_text(current)) and is_truncated_text(current):
        return False
    return len(candidate) > max(len(current) * 1.70, len(current) + 65)


def _contains_token_sequence(container: Any, part: Any) -> bool:
    c = norm_text(container).split()
    p = norm_text(part).split()
    if not c or not p or len(p) > len(c):
        return False
    for i in range(0, len(c) - len(p) + 1):
        if c[i : i + len(p)] == p:
            return True
    return False


def _candidate_quality(text: str) -> float:
    base = text_quality_score(text)
    if not is_truncated_text(text):
        base += 0.55
    # Penalize over-concatenated descriptions even when the generic pollution
    # guard did not veto them.  A single SINAPI service can be long, but many
    # independent AF anchors are a sign that multiple rows were joined.
    af_count = norm_text(text).count("AF_")
    if af_count >= 3:
        base -= 1.5
    if text.startswith("-"):
        base -= 1.0
    return max(0.0, base)


def _score_candidate_for_row(row: RowRef, candidate: EvidenceCandidate) -> Dict[str, Any]:
    current = row.current
    candidate_text = _clean(candidate.descricao)
    out = {
        "candidate": candidate_text,
        "score": 0.0,
        "decision": "rejected",
        "reasons": [],
        "source_count": candidate.occurrences,
        "sources": candidate.sources[:6],
    }
    ok, reason = _candidate_clean_enough(candidate_text)
    if not ok:
        out["reasons"].append(reason)
        return out
    ownership = ownership_report(candidate_text, current_value=current, target_confirmed=candidate_text, neighbor_context=row.neighbor_context)
    out["ownership"] = ownership
    if ownership.get("has_neighbor_hit"):
        out["reasons"].append("candidate_owned_by_neighbor")
        return out
    reverse = choose_clean_subcandidate_from_current(current, candidate_text, row.neighbor_context)
    reverse_repair = bool(reverse.get("accepted"))
    if reverse_repair:
        out["reverse_repair"] = reverse
    if current and similarity(current, candidate_text) >= 0.985:
        out["reasons"].append("current_already_matches_candidate")
        return out
    if current and not _is_weak_description(current) and not reverse_repair:
        # Keep a clean current value unless the candidate is essentially the
        # same text plus a clearly compatible completion.
        if not (is_truncated_text(current) or norm_text(candidate_text).startswith(norm_text(current))):
            out["reasons"].append("current_not_weak")
            return out
    if current and _long_risk(current, candidate_text):
        out["reasons"].append("candidate_too_long_for_current")
        return out
    sim = similarity(current, candidate_text) if current else 0.0
    prefix = bool(current and norm_text(candidate_text).startswith(norm_text(current)))
    contains = bool(current and _contains_token_sequence(candidate_text, current))
    confirmed = is_confirmed_candidate(candidate)
    score = 0.0
    score += min(candidate.quality, 5.0)
    score += float(ownership.get("score_delta") or 0.0)
    score += 2.25 if reverse_repair else 0.0
    score += 1.35 if confirmed else 0.0
    score += 1.25 if prefix else 0.0
    score += 0.65 if contains else 0.0
    score += 0.85 if (not current or _is_weak_description(current)) else 0.0
    score += sim
    if candidate.occurrences >= 2:
        score += 0.65
    if row.source.startswith("budget") and any(str(s).startswith("composition") for s in candidate.sources):
        score += 0.75
    if row.source.startswith("composition") and any(str(s).startswith("budget") for s in candidate.sources):
        score += 0.75
    if current and sim < 0.62 and not prefix and not contains:
        score -= 2.0
    if current and not _is_weak_description(current) and len(candidate_text) > len(current) + 18:
        score -= 1.4
    out["score"] = round(max(0.0, score), 4)
    threshold = 4.25 if reverse_repair else (4.65 if current else 3.65)
    if out["score"] >= threshold:
        out["decision"] = "accepted"
    else:
        out["reasons"].append("score_below_threshold")
    return out


def is_confirmed_candidate(candidate: EvidenceCandidate) -> bool:
    sources = set(candidate.sources)
    has_budget = any(str(s).startswith("budget") for s in sources)
    has_composition = any(str(s).startswith("composition") for s in sources)
    if candidate.occurrences >= 2 and candidate.quality >= 2.4:
        return True
    if has_budget and has_composition and candidate.quality >= 2.0:
        return True
    if candidate.quality >= 3.35 and len(candidate.descricao) >= 45 and not is_truncated_text(candidate.descricao):
        return True
    return False


def _iter_budget_rows(final_result: Dict[str, Any]) -> Iterable[RowRef]:
    def walk(nodes: Any, base: List[Any]) -> Iterable[RowRef]:
        if not isinstance(nodes, list):
            return
        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            path = base + [idx]
            if str(node.get("tipo") or "").lower() == "item" or node.get("codigo"):
                yield RowRef(
                    path=path,
                    row=node,
                    field="especificacao" if "especificacao" in node else "descricao",
                    family="budget",
                    source=f"budget.{node.get('item') or '.'.join(map(str, path))}",
                    codigo=_clean(node.get("codigo")),
                    banco=_clean(node.get("fonte") or node.get("banco")),
                    item=_clean(node.get("item")),
                    page=_coerce_int(node.get("pagina") or node.get("page_hint") or node.get("pagina_inicio")),
                )
            yield from walk(node.get("filhos"), path + ["filhos"])
    yield from walk(((final_result.get("orcamento_sintetico") or {}).get("itens_raiz") or []), ["orcamento_sintetico", "itens_raiz"])


def _iter_composition_rows(final_result: Dict[str, Any]) -> Iterable[RowRef]:
    comp = final_result.get("composicoes") if isinstance(final_result.get("composicoes"), dict) else {}
    sources: List[Tuple[List[Any], str, Dict[str, Any]]] = []
    for collection in ("principais", "auxiliares_globais"):
        if isinstance(comp.get(collection), dict):
            sources.append((["composicoes", collection], collection, comp.get(collection) or {}))
        fam = comp.get("sinapi_like") if isinstance(comp.get("sinapi_like"), dict) else {}
        if isinstance(fam.get(collection), dict):
            sources.append((["composicoes", "sinapi_like", collection], f"sinapi_like.{collection}", fam.get(collection) or {}))
    for base, collection, blocks in sources:
        for key, block in (blocks or {}).items():
            if not isinstance(block, dict):
                continue
            principal = block.get("principal") if isinstance(block.get("principal"), dict) else None
            if principal and not is_sicro_bank(principal.get("banco") or principal.get("fonte") or key.split("|")[-1]):
                yield RowRef(
                    path=base + [key, "principal"],
                    row=principal,
                    field="descricao",
                    family="sinapi_like",
                    source=f"composition.{collection}.{key}.principal",
                    codigo=_clean(principal.get("codigo") or key.split("|")[0]),
                    banco=_clean(principal.get("banco") or principal.get("fonte") or key.split("|")[-1]),
                    page=_coerce_int(block.get("pagina_inicio") or principal.get("page_hint")),
                )
            for group in ("composicoes_auxiliares", "insumos"):
                rows = block.get(group)
                if not isinstance(rows, list):
                    continue
                for idx, row in enumerate(rows):
                    if not isinstance(row, dict) or is_sicro_bank(row.get("banco") or row.get("fonte")):
                        continue
                    yield RowRef(
                        path=base + [key, group, idx],
                        row=row,
                        field="descricao",
                        family="sinapi_like",
                        source=f"composition.{collection}.{key}.{group}.{idx}",
                        codigo=_clean(row.get("codigo")),
                        banco=_clean(row.get("banco") or row.get("fonte") or ((principal or {}).get("banco") if isinstance(principal, dict) else "")),
                        page=_coerce_int(row.get("page_hint") or block.get("pagina_inicio")),
                    )


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def _row_refs(final_result: Dict[str, Any]) -> List[RowRef]:
    return list(_iter_budget_rows(final_result)) + list(_iter_composition_rows(final_result))


def _build_evidence_candidates(rows: List[RowRef]) -> Dict[str, EvidenceCandidate]:
    registry: Dict[str, EvidenceCandidate] = {}
    for row in rows:
        if not row.key or not row.current:
            continue
        ok, _ = _candidate_clean_enough(row.current)
        if not ok:
            continue
        q = _candidate_quality(row.current)
        if q <= 0.0:
            continue
        current_key = row.key
        cur = registry.get(current_key)
        if cur is None:
            registry[current_key] = EvidenceCandidate(row.current, current_key)
            registry[current_key].add(row.source, row.path, q)
            continue
        if similarity(cur.descricao, row.current) >= 0.92:
            if len(row.current) > len(cur.descricao) or q > cur.quality:
                cur.descricao = row.current
            cur.add(row.source, row.path, q)
        elif q > cur.quality + 1.0 and not is_confirmed_candidate(cur):
            registry[current_key] = EvidenceCandidate(row.current, current_key)
            registry[current_key].add(row.source, row.path, q)
    return registry


def _get_by_path(root: Dict[str, Any], path: List[Any]) -> Any:
    cur: Any = root
    for part in path:
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            cur = cur[int(part)]
        else:
            return None
    return cur


def _set_by_path(root: Dict[str, Any], path: List[Any], value: Any) -> bool:
    if not path:
        return False
    cur: Any = root
    for part in path[:-1]:
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            cur = cur[int(part)]
        else:
            return False
    last = path[-1]
    if isinstance(cur, dict):
        cur[last] = value
        return True
    if isinstance(cur, list):
        cur[int(last)] = value
        return True
    return False


def _target_from_row(row: RowRef, reason: str) -> Dict[str, Any]:
    return {
        "target_id": f"{'.'.join(map(str, row.path))}::{row.field}",
        "path": list(row.path) + [row.field],
        "field": row.field,
        "family": row.family,
        "table_family": "budget" if row.family == "budget" else "composition",
        "codigo": row.codigo,
        "banco": row.banco,
        "item": row.item,
        "page": row.page,
        "current_value": row.current,
        "issue": reason,
        "source": "selective_field_reparse_executor",
        "neighbor_context": row.neighbor_context,
    }



def _candidate_payload_for_row(row: RowRef, registry: Dict[str, EvidenceCandidate]) -> Dict[str, Any]:
    candidate = registry.get(row.key)
    return {
        "codigo": row.codigo,
        "banco": row.banco,
        "item": row.item,
        "descricao": row.current,
        "confirmed_description": candidate.descricao if candidate and is_confirmed_candidate(candidate) else "",
        "source": row.source,
    }


def _attach_neighbor_contexts(rows: List[RowRef], registry: Dict[str, EvidenceCandidate]) -> None:
    """Attach previous/next budget leaf evidence to budget rows.

    This is the lightweight cross-table ownership check requested for cases such
    as ANP 01: if a candidate contains descriptions already confirmed for the
    item above/below, it is probably not owned by the target row.
    """
    budget_rows = [r for r in rows if r.family == "budget"]
    for idx, row in enumerate(budget_rows):
        ctx: Dict[str, Any] = {}
        if idx > 0:
            ctx["prev"] = _candidate_payload_for_row(budget_rows[idx - 1], registry)
        if idx + 1 < len(budget_rows):
            ctx["next"] = _candidate_payload_for_row(budget_rows[idx + 1], registry)
        row.neighbor_context = ctx

def run_selective_field_reparse_executor(final_result: Dict[str, Any] | None, *, apply: bool = True) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Run evidence-only selective reparse over a final_result-like dict.

    Returns (possibly patched_final_result, report).  The report contains
    surgical targets that the PDF-based recovery stage can process afterwards.
    """
    result = copy.deepcopy(final_result or {})
    rows = _row_refs(result)
    registry = _build_evidence_candidates(rows)
    _attach_neighbor_contexts(rows, registry)
    applied: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    targets: List[Dict[str, Any]] = []
    for row in rows:
        if not row.key:
            continue
        reason = _is_weak_description(row.current)
        candidate = registry.get(row.key)
        if not reason:
            continue
        if candidate is None:
            targets.append(_target_from_row(row, reason))
            continue
        decision = _score_candidate_for_row(row, candidate)
        record = {
            "target_id": f"{'.'.join(map(str, row.path))}::{row.field}",
            "path": list(row.path) + [row.field],
            "field": row.field,
            "family": row.family,
            "codigo": row.codigo,
            "banco": row.banco,
            "before": row.current,
            "candidate": candidate.descricao,
            "reason": reason,
            "score": decision.get("score"),
            "decision": decision.get("decision"),
            "reasons": decision.get("reasons") or [],
            "sources": decision.get("sources") or [],
            "ownership": decision.get("ownership") or {},
        }
        if decision.get("decision") == "accepted":
            if apply and _set_by_path(result, list(row.path) + [row.field], candidate.descricao):
                applied.append({**record, "after": candidate.descricao})
            else:
                rejected.append({**record, "decision": "rejected", "reasons": ["patch_target_not_found"]})
                targets.append(_target_from_row(row, reason))
        else:
            rejected.append(record)
            targets.append(_target_from_row(row, reason))
    report = {
        "version": VERSION,
        "mode": "selective_field_reparse_executor",
        "summary": {
            "rows_seen": len(rows),
            "confirmed_descriptions": sum(1 for c in registry.values() if is_confirmed_candidate(c)),
            "applied": len(applied),
            "rejected": len(rejected),
            "targets": len(targets),
            "budget_targets": sum(1 for t in targets if t.get("family") == "budget"),
            "composition_targets": sum(1 for t in targets if t.get("family") == "sinapi_like"),
        },
        "confirmed_descriptions": {k: v.as_dict() for k, v in registry.items() if is_confirmed_candidate(v)},
        "applied": applied,
        "rejected": rejected[:200],
        "targets": targets[:250],
    }
    return result, report
