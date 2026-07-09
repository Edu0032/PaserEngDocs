from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Tuple

from app.normalizer.geometry_extractor import extract_page_geometry, _clean, _norm
from app.parser.broken_line_recovery import pollution_reason, similarity, is_truncated_text
from app.parser.page_line_graph import build_page_line_graph, line_barrier_reason
from app.parser.description_ownership_resolver import (
    ownership_report,
    line_vertical_gap_profile,
    cell_occupancy_ratio,
    looks_complete_by_cell_occupancy,
)
from app.parser.field_patch_validators import candidate_kind, normalize_field_name, validate_patch_candidate
from app.parser.numeric_constraint_solver import math_triplet_status

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _target_family(target: Dict[str, Any] | None) -> str:
    """Return the physical table family to use for one recovery target.

    v61.0.26 keeps extending the local recovery engine to the synthetic budget.  The
    caller marks targets with ``family='budget'``/``table_family='budget'``;
    older callers keep working because composition remains the default.
    """
    target = target or {}
    raw = str(
        target.get("family")
        or target.get("table_family")
        or target.get("kind")
        or target.get("target_family")
        or "composition"
    ).strip().lower()
    if raw in {"budget", "orcamento", "orcamento_sintetico", "synthetic_budget"}:
        return "budget"
    return "composition"


def _description_field_for(target: Dict[str, Any] | None) -> str:
    target = target or {}
    field = str(target.get("field") or "").strip()
    if field:
        return field
    return "especificacao" if _target_family(target) == "budget" else "descricao"


def _as_float(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def _canonical(col: Dict[str, Any] | None) -> str:
    if not isinstance(col, dict):
        return ""
    return str(col.get("canonical") or col.get("canonical_name") or "").strip()


def _all_columns(table: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    table = dict(table or {})
    cols = [c for c in list(table.get("columns") or []) + list(table.get("ignored_columns") or []) if isinstance(c, dict)]
    def key(c: Dict[str, Any]) -> Tuple[int, float]:
        x0 = _as_float(c.get("x0"))
        return (0 if x0 is not None else 1, x0 if x0 is not None else 999999.0)
    return sorted(cols, key=key)


def _find_column(table: Dict[str, Any] | None, canonical: str) -> Dict[str, Any] | None:
    for c in _all_columns(table):
        if _canonical(c) == canonical:
            return c
    return None


def _table_from_document_profile(payload: Dict[str, Any], family: str) -> Dict[str, Any]:
    profile = payload.get("document_learning_profile") or payload.get("document_profile") or {}
    if not isinstance(profile, dict):
        return {}
    profile_key = "budget_profile" if family == "budget" else "sinapi_like_profile"
    bands = ((profile.get(profile_key) or {}).get("column_bands") or {}) if isinstance(profile.get(profile_key), dict) else {}
    if not isinstance(bands, dict) or not bands:
        return {}
    columns = []
    for canonical, info in bands.items():
        if not isinstance(info, dict):
            continue
        x0 = info.get("x0_median", info.get("x0"))
        x1 = info.get("x1_median", info.get("x1"))
        if x0 is None and x1 is None:
            continue
        columns.append({"canonical": canonical, "x0": x0, "x1": x1, "geometry_source": "document_learning_profile"})
    return {"columns": columns, "source": "document_learning_profile"} if columns else {}


def _table_for_family(payload: Dict[str, Any], family: str = "composition") -> Dict[str, Any]:
    maps = payload.get("column_maps") or payload.get("tables") or {}
    if isinstance(maps, dict) and isinstance(maps.get(family), dict):
        return maps.get(family) or {}
    st = payload.get("structured_tables") or payload.get("docling_clean_payload") or {}
    if isinstance(st, dict) and isinstance((st.get("tables") or {}).get(family), dict):
        return (st.get("tables") or {}).get(family) or {}
    if isinstance(st, dict) and isinstance(st.get(family), dict):
        return st.get(family) or {}
    prof = _table_from_document_profile(payload, family)
    if prof:
        return prof
    return {}


def _column_band(table: Dict[str, Any], canonical: str, *, fallback: Tuple[float | None, float | None] = (None, None)) -> Tuple[float | None, float | None]:
    cols = _all_columns(table)
    col = _find_column(table, canonical)
    if not col:
        return fallback
    x0 = _as_float(col.get("x0"))
    x1 = _as_float(col.get("x1"))
    # The reliable end of a text column is often the x0 of the next physical column,
    # which can be an ignored structural column such as tipo. This respects each
    # document's observed column order instead of assuming fixed neighbors.
    if x0 is not None:
        after = []
        for c in cols:
            cx0 = _as_float(c.get("x0"))
            if cx0 is not None and cx0 > x0 + 0.5:
                after.append(cx0)
        if after:
            x1 = min(after)
    return x0 if x0 is not None else fallback[0], x1 if x1 is not None else fallback[1]


def _tokens(value: Any) -> List[str]:
    return [t for t in _norm(value).split() if t]


def _contains_token_sequence(container: Any, part: Any) -> bool:
    c = _tokens(container); p = _tokens(part)
    if not c or not p or len(p) > len(c):
        return False
    for i in range(0, len(c) - len(p) + 1):
        if c[i:i + len(p)] == p:
            return True
    return False


def _candidate_is_valid_description(value: Any) -> bool:
    text = _clean(value)
    if not text or len(text) < 3:
        return False
    if pollution_reason(text):
        return False
    if re.fullmatch(r"[\d\s.,%/\-]+", text):
        return False
    return True



def _line_has_financial_values(line: Dict[str, Any]) -> bool:
    text = str((line or {}).get("text") or "")
    # Two or more pt-BR numeric/money tokens in a continuation line usually mean
    # we crossed into a real row with quantity/unit prices/totals.  Do not use it
    # as a description fragment.
    nums = re.findall(r"(?<![A-Z0-9])\d{1,3}(?:\.\d{3})*,\d{2,7}(?![A-Z0-9])", text, flags=re.I)
    return len(nums) >= 2

def _line_has_sequence(line: Dict[str, Any], text: Any) -> bool:
    target = _tokens(text)
    if not target:
        return False
    words = [_norm(w.get("text")) for w in list(line.get("words") or [])]
    if len(target) <= len(words):
        for i in range(0, len(words) - len(target) + 1):
            if words[i:i + len(target)] == target:
                return True
    return " ".join(target) in str(line.get("norm_text") or "")


def _match_bbox(line: Dict[str, Any], text: Any) -> Dict[str, Any] | None:
    target = _tokens(text)
    if not target:
        return None
    words = list(line.get("words") or [])
    norm_words = [_norm(w.get("text")) for w in words]
    if len(target) <= len(norm_words):
        for i in range(0, len(norm_words) - len(target) + 1):
            if norm_words[i:i + len(target)] == target:
                matched = words[i:i + len(target)]
                return {
                    "text": " ".join(str(w.get("text") or "") for w in matched),
                    "x0": round(min(float(w.get("x0", 0)) for w in matched), 3),
                    "y0": round(min(float(w.get("y0", 0)) for w in matched), 3),
                    "x1": round(max(float(w.get("x1", 0)) for w in matched), 3),
                    "y1": round(max(float(w.get("y1", 0)) for w in matched), 3),
                }
    return None


def _find_target_line(lines: List[Dict[str, Any]], codigo: str, banco: str = "") -> Tuple[int, Dict[str, Any] | None]:
    best: Tuple[int, int, Dict[str, Any] | None] = (-1, -1, None)
    for idx, line in enumerate(lines):
        score = 0
        if _line_has_sequence(line, codigo):
            score += 5
        if banco and _line_has_sequence(line, banco):
            score += 3
        text = _norm(line.get("text"))
        if any(mark in text for mark in ["COMPOSICAO", "INSUMO", "AUXILIAR"]):
            score += 1
        if score > best[0]:
            best = (score, idx, line)
    if best[0] >= 5:
        return best[1], best[2]
    return -1, None


def _text_in_band(line: Dict[str, Any], x0: float | None, x1: float | None) -> str:
    words = []
    for w in list(line.get("words") or []):
        wx0 = _as_float(w.get("x0")); wx1 = _as_float(w.get("x1"))
        if wx0 is None or wx1 is None:
            continue
        center = (wx0 + wx1) / 2.0
        if x0 is not None and center < x0 - 1.0:
            continue
        if x1 is not None and center > x1 + 1.0:
            continue
        words.append(str(w.get("text") or ""))
    return _clean(" ".join(words))


_START_MARKERS = {"COMPOSICAO", "COMPOSIÇÃO", "INSUMO", "AUXILIAR"}

def _looks_like_new_row(line: Dict[str, Any], table: Dict[str, Any], *, family: str = "composition") -> bool:
    text = _norm(line.get("text"))
    if not text:
        return False
    first = text.split()[0] if text.split() else ""
    if first in {_norm(x) for x in _START_MARKERS}:
        return True
    if family == "budget":
        # Budget rows usually start with an item hierarchy.  This is a generic
        # structural signal, not a document-specific hardcode.
        if re.match(r"^\d+(?:\.\d+)*\s+", text):
            return True
    # Generic code+bank style at the beginning or left/control band suggests a new row.
    banco_words = {"SINAPI", "SICRO", "SICRO3", "PROPRIO", "PRÓPRIO", "ANP"}
    toks = text.split()
    if len(toks) >= 2 and any(t in banco_words for t in toks[:4]) and re.search(r"\d", " ".join(toks[:3])):
        return True
    return False


def _collect_downward_continuations(lines: List[Dict[str, Any]], start_idx: int, table: Dict[str, Any], desc_x0: float | None, desc_x1: float | None, *, max_lines: int = 3, family: str = "composition", gap_profile: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    fragments: List[Dict[str, Any]] = []
    last_y = _as_float((lines[start_idx] or {}).get("y1")) if 0 <= start_idx < len(lines) else None
    for nxt in range(start_idx + 1, min(len(lines), start_idx + 1 + max_lines)):
        line = lines[nxt]
        y0 = _as_float(line.get("y0"))
        max_gap = float((gap_profile or {}).get("continuation_max_gap") or 18)
        if last_y is not None and y0 is not None and y0 - last_y > max_gap:
            break
        barrier = line_barrier_reason(line, family=family) or ("financial_values_boundary" if _line_has_financial_values(line) else "")
        if barrier:
            break
        fragment = _text_in_band(line, desc_x0, desc_x1)
        if not _candidate_is_valid_description(fragment):
            if fragment and re.fullmatch(r"[\d\s.,%]+", fragment):
                break
            continue
        fragments.append({"text": fragment, "line_index": nxt, "direction": "down", "line_text": line.get("text", "")})
        last_y = _as_float(line.get("y1")) or last_y
    return fragments


def _collect_upward_continuations(lines: List[Dict[str, Any]], start_idx: int, table: Dict[str, Any], desc_x0: float | None, desc_x1: float | None, *, max_lines: int = 2, family: str = "composition", gap_profile: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    fragments: List[Dict[str, Any]] = []
    base_y0 = _as_float((lines[start_idx] or {}).get("y0")) if 0 <= start_idx < len(lines) else None
    last_top = base_y0
    for prev in range(start_idx - 1, max(-1, start_idx - 1 - max_lines), -1):
        line = lines[prev]
        y1 = _as_float(line.get("y1"))
        max_gap = float((gap_profile or {}).get("continuation_max_gap") or 18)
        if last_top is not None and y1 is not None and last_top - y1 > max_gap:
            break
        barrier = line_barrier_reason(line, family=family) or ("financial_values_boundary" if _line_has_financial_values(line) else "")
        if barrier:
            break
        fragment = _text_in_band(line, desc_x0, desc_x1)
        if not _candidate_is_valid_description(fragment):
            continue
        fragments.append({"text": fragment, "line_index": prev, "direction": "up", "line_text": line.get("text", "")})
        last_top = _as_float(line.get("y0")) or last_top
    return list(reversed(fragments))


def _append_continuations(lines: List[Dict[str, Any]], start_idx: int, base_text: str, table: Dict[str, Any], desc_x0: float | None, desc_x1: float | None, *, max_lines: int = 3, family: str = "composition") -> str:
    parts = [_clean(base_text)] if _clean(base_text) else []
    for frag in _collect_downward_continuations(lines, start_idx, table, desc_x0, desc_x1, max_lines=max_lines, family=family):
        parts.append(frag["text"])
    return _clean(" ".join(parts))


def _build_recovery_candidates(lines: List[Dict[str, Any]], line_idx: int, base_text: str, table: Dict[str, Any], desc_x0: float | None, desc_x1: float | None, *, family: str = "composition", gap_profile: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    base = _clean(base_text)
    up = _collect_upward_continuations(lines, line_idx, table, desc_x0, desc_x1, family=family, gap_profile=gap_profile)
    down = _collect_downward_continuations(lines, line_idx, table, desc_x0, desc_x1, family=family, gap_profile=gap_profile)
    candidates: List[Dict[str, Any]] = []
    if base:
        candidates.append({"value": base, "strategy": "target_line_only", "fragments": []})
    if down:
        candidates.append({"value": _clean(" ".join([base] + [f["text"] for f in down if f.get("text")])) , "strategy": "target_plus_downward_fragments", "fragments": down})
    if up:
        candidates.append({"value": _clean(" ".join([f["text"] for f in up if f.get("text")] + [base])), "strategy": "upward_fragments_plus_target", "fragments": up})
    if up and down:
        candidates.append({"value": _clean(" ".join([f["text"] for f in up if f.get("text")] + [base] + [f["text"] for f in down if f.get("text")])) , "strategy": "upward_target_downward_fragments", "fragments": up + down})
    # Deduplicate while preserving order.
    out=[]; seen=set()
    for c in candidates:
        value = _clean(c.get("value"))
        if not value or value in seen or not _candidate_is_valid_description(value):
            continue
        seen.add(value); out.append(c)
    return out


def _registry_entry_for(payload: Dict[str, Any], codigo: str, banco: str) -> Dict[str, Any]:
    registry = payload.get("description_registry") or payload.get("confirmed_descriptions") or {}
    if not isinstance(registry, dict):
        return {}
    keys = []
    c = str(codigo or "").strip().upper().replace(" ", "")
    b = str(banco or "").strip().upper().replace(" ", "")
    if c and b:
        keys.extend([f"{c}|{b}", f"{c}|SINAPI" if b in {"CAIXA"} else f"{c}|{b}"])
    if c:
        keys.append(c)
    for k in keys:
        ent = registry.get(k)
        if isinstance(ent, dict):
            return ent
        if isinstance(ent, str):
            return {"descricao": ent, "confirmed": True, "source": "registry_string"}
    return {}


def _registry_confirms_current(target: Dict[str, Any], registry_entry: Dict[str, Any]) -> bool:
    current = _clean(target.get("current_value") or "")
    reg_desc = _clean(registry_entry.get("descricao") or registry_entry.get("description") or "")
    if not current or not reg_desc:
        return False
    confirmed = bool(registry_entry.get("confirmed") or registry_entry.get("locked_negative_evidence"))
    return confirmed and similarity(current, reg_desc) >= 0.94


def _candidate_fragment_count(candidate: Dict[str, Any]) -> int:
    return len(candidate.get("fragments") or [])


def _candidate_is_longer_risky(current: str, value: str) -> bool:
    current = _clean(current); value = _clean(value)
    if not current or not value:
        return False
    if len(value) <= len(current) + 18:
        return False
    if _norm(value).startswith(_norm(current)) and is_truncated_text(current):
        return False
    return len(value) > max(len(current) * 1.55, len(current) + 35)


def _score_recovery_candidate(target: Dict[str, Any], candidate: Dict[str, Any], registry_entry: Dict[str, Any]) -> float:
    value = _clean(candidate.get("value"))
    current = _clean(target.get("current_value") or "")
    if not value or pollution_reason(value):
        return 0.0
    owner = ownership_report(value, current_value=current, target_confirmed=(registry_entry.get("descricao") or registry_entry.get("description") or ""), neighbor_context=target.get("neighbor_context") or {})
    if owner.get("has_neighbor_hit"):
        # Candidate contains text owned by the previous/next item; keep only if
        # no other hypothesis exists, and even then confidence must be too low
        # to auto-apply.
        return 0.0
    score = 0.56
    score += max(-0.45, min(0.18, float(owner.get("score_delta") or 0.0) / 8.0))
    toks = _tokens(value)
    sim_current = similarity(current, value) if current else 0.0
    if len(toks) >= 3: score += 0.04
    if len(toks) >= 6: score += 0.03
    if _candidate_is_longer_risky(current, value):
        score -= 0.34
    if _registry_confirms_current(target, registry_entry) and candidate.get("strategy") != "target_line_only":
        score -= 0.50
    issue_l = str(target.get("issue") or target.get("target_issue") or "").lower()
    if candidate.get("strategy") == "target_line_only":
        score += 0.18
        if is_truncated_text(current) or "broken" in issue_l:
            score -= 0.24
    if current and _norm(value).startswith(_norm(current)): score += 0.10
    elif current and _contains_token_sequence(value, current): score += 0.06
    # Fragments are useful only when the target is actually weak. Penalize
    # long candidates that reduce similarity to the already extracted text.
    if looks_complete_by_cell_occupancy(current, target.get("_recovery_current_occupancy")) and candidate.get("strategy") != "target_line_only":
        score -= 0.42
    if candidate.get("strategy") in {"target_plus_downward_fragments", "upward_fragments_plus_target", "upward_target_downward_fragments"}:
        if is_truncated_text(current) or not current:
            score += 0.20
        else:
            score -= 0.12
        if current and sim_current < 0.72:
            score -= 0.26
        if current and not is_truncated_text(current) and sim_current < 0.90:
            score -= 0.22
    if candidate.get("strategy") == "upward_target_downward_fragments":
        score -= 0.34
    if candidate.get("strategy") in {"upward_fragments_plus_target"}:
        score += 0.42 if "broken" in issue_l else -0.02
        if current and sim_current >= 0.78 and not _candidate_is_longer_risky(current, value):
            score += 0.12
    reg_desc = _clean(registry_entry.get("descricao") or registry_entry.get("description") or "")
    if reg_desc:
        sim = similarity(value, reg_desc)
        if sim >= 0.94:
            score += 0.18
        elif current and similarity(current, reg_desc) >= 0.94 and sim < 0.80:
            # confirmed description says current is already complete; candidate is a wrong fragment attachment.
            score -= 0.35
        elif sim >= 0.82:
            score += 0.08
    return round(max(0.0, min(score, 0.99)), 3)


def _score_hypotheses(target: Dict[str, Any], candidates: List[Dict[str, Any]], registry_entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    scored=[]
    for cand in candidates:
        confidence = _score_recovery_candidate(target, cand, registry_entry)
        scored.append({
            **cand,
            "confidence": confidence,
            "hypothesis": cand.get("strategy") or "unknown",
            "current_similarity": round(similarity(target.get("current_value") or "", cand.get("value") or ""), 4),
            "uses_confirmed_registry": bool(registry_entry and cand.get("strategy") == "confirmed_description_registry"),
        })
    scored.sort(key=lambda c: (float(c.get("confidence") or 0), float(c.get("current_similarity") or 0), -_candidate_fragment_count(c), -len(_clean(c.get("value")))), reverse=True)
    return scored


def _choose_best_candidate(target: Dict[str, Any], candidates: List[Dict[str, Any]], registry_entry: Dict[str, Any]) -> Dict[str, Any] | None:
    scored = _score_hypotheses(target, candidates, registry_entry)
    if not scored:
        return None
    current = _clean(target.get("current_value") or "")
    if looks_complete_by_cell_occupancy(current, target.get("_recovery_current_occupancy")):
        for cand in scored:
            if cand.get("hypothesis") == "target_line_only":
                best = dict(cand)
                best["hypotheses"] = [
                    {"hypothesis": c.get("hypothesis"), "value": c.get("value"), "confidence": c.get("confidence"), "current_similarity": c.get("current_similarity")}
                    for c in scored[:8]
                ]
                best["safety_lock"] = "description_cell_occupancy_indicates_complete_short_text"
                return best
    # Safety first: when the current/target-line extraction is already identical
    # or near-identical, never prefer a longer fragment hypothesis. This prevents
    # pulling text from the previous/next budget item, e.g. ABC 01 in the real PDF.
    issue_l = str(target.get("issue") or target.get("target_issue") or "").lower()
    # V30 still supports true upward broken-line recovery: when the caller has
    # explicitly marked a row as broken and a clean upward-only hypothesis exists,
    # it may beat target_line_only. Mixed up+down hypotheses remain strongly
    # penalized to avoid crossing neighboring items.
    if current and "broken" in issue_l and not _registry_confirms_current(target, registry_entry):
        upward = [c for c in scored if c.get("hypothesis") == "upward_fragments_plus_target" and float(c.get("confidence") or 0) >= 0.78 and float(c.get("current_similarity") or 0) >= 0.70]
        if upward:
            best = dict(upward[0])
            best["hypotheses"] = [
                {"hypothesis": c.get("hypothesis"), "value": c.get("value"), "confidence": c.get("confidence"), "current_similarity": c.get("current_similarity")}
                for c in scored[:8]
            ]
            return best

    # V30 safety: target_line_only is the least destructive hypothesis. If it
    # already matches the current value and the current text is not clearly
    # truncated, never choose a longer candidate, even when the target was marked
    # as a possible broken line by earlier heuristics, unless the upward-only
    # exception above selected a clean prefix fragment.
    if current and not is_truncated_text(current):
        for cand in scored:
            if cand.get("hypothesis") == "target_line_only" and similarity(current, cand.get("value") or "") >= 0.97:
                best = dict(cand)
                best["hypotheses"] = [
                    {"hypothesis": c.get("hypothesis"), "value": c.get("value"), "confidence": c.get("confidence"), "current_similarity": c.get("current_similarity")}
                    for c in scored[:8]
                ]
                best["safety_lock"] = "target_line_already_matches_current"
                return best
    if _registry_confirms_current(target, registry_entry):
        for cand in scored:
            if cand.get("hypothesis") == "target_line_only":
                best = dict(cand)
                best["hypotheses"] = [
                    {"hypothesis": c.get("hypothesis"), "value": c.get("value"), "confidence": c.get("confidence"), "current_similarity": c.get("current_similarity")}
                    for c in scored[:8]
                ]
                best["safety_lock"] = "confirmed_registry_matches_current"
                return best
    best = dict(scored[0])
    best["hypotheses"] = [
        {"hypothesis": c.get("hypothesis"), "value": c.get("value"), "confidence": c.get("confidence"), "current_similarity": c.get("current_similarity")}
        for c in scored[:6]
    ]
    return best


def _looks_truncated(current: str, recovered: str) -> bool:
    cur = _clean(current)
    rec = _clean(recovered)
    if not cur:
        return bool(rec)
    if len(rec) > len(cur) + 8 and _norm(rec).startswith(_norm(cur)):
        return True
    tail = (_norm(cur).split() or [""])[-1]
    return tail in {"DE", "DA", "DO", "DAS", "DOS", "PARA", "COM", "E", "EM", "A", "O"} and len(rec) > len(cur)


def _confidence_for(target: Dict[str, Any], recovered: str, line: Dict[str, Any] | None, codigo_bbox: Dict[str, Any] | None, banco_bbox: Dict[str, Any] | None) -> float:
    if not recovered or not line or not codigo_bbox:
        return 0.0
    score = 0.62
    if banco_bbox:
        score += 0.16
    if _norm(target.get("current_value")) and _norm(recovered).startswith(_norm(target.get("current_value"))):
        score += 0.10
    if len(_tokens(recovered)) >= 3:
        score += 0.08
    if len(_tokens(recovered)) >= 6:
        score += 0.04
    return round(min(score, 0.98), 3)



def _canonical_for_target_field(field: str, family: str) -> str:
    f = normalize_field_name(field)
    if f == "especificacao":
        return "especificacao" if family == "budget" else "descricao"
    if f == "descricao":
        return "descricao" if family != "budget" else "especificacao"
    aliases = {
        "custo_unitario_com_bdi": "custo_unitario_com_bdi",
        "custo_unitario_sem_bdi": "custo_unitario_sem_bdi",
        "custo_parcial": "custo_parcial",
        "custo_total": "custo_total",
        "valor_unit": "valor_unit",
        "total": "total",
        "quant": "quant",
        "und": "und",
    }
    return aliases.get(f, f)


def _band_for_target_field(table: Dict[str, Any], field: str, family: str, line: Dict[str, Any] | None = None) -> Tuple[float | None, float | None, str]:
    canonical = _canonical_for_target_field(field, family)
    x0, x1 = _column_band(table, canonical)
    if x0 is None and canonical == "especificacao":
        x0, x1 = _column_band(table, "descricao")
    if x0 is None and canonical == "descricao":
        x0, x1 = _column_band(table, "especificacao")
    return x0, x1, canonical


def _tokens_in_band(line: Dict[str, Any], x0: float | None, x1: float | None) -> List[Dict[str, Any]]:
    out = []
    for w in list((line or {}).get("words") or []):
        wx0 = _as_float(w.get("x0")); wx1 = _as_float(w.get("x1"))
        if wx0 is None or wx1 is None:
            continue
        center = (wx0 + wx1) / 2.0
        if x0 is not None and center < x0 - 1.5:
            continue
        if x1 is not None and center > x1 + 1.5:
            continue
        out.append(w)
    return out


def _field_candidates_from_line(line: Dict[str, Any], field: str, x0: float | None, x1: float | None, *, context: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    kind = candidate_kind(field)
    words = _tokens_in_band(line, x0, x1)
    texts = [_clean(w.get("text")) for w in words if _clean(w.get("text"))]
    joined = _clean(" ".join(texts))
    raw_candidates: List[str] = []
    if kind == "unit":
        raw_candidates.extend(texts)
        if joined:
            raw_candidates.append(joined)
    elif kind in {"quantity", "money"}:
        for token in texts:
            raw_candidates.extend(re.findall(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+(?:,\d+)?", token))
        if joined:
            raw_candidates.extend(re.findall(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+(?:,\d+)?", joined))
    else:
        if joined:
            raw_candidates.append(joined)
    out=[]; seen=set()
    for raw in raw_candidates:
        validation = validate_patch_candidate(field, raw, {}, context or {})
        if not validation.get("ok"):
            continue
        value = _clean(validation.get("normalized", raw))
        if not value or value in seen:
            continue
        seen.add(value)
        out.append({"value": value, "validation": validation, "source_text": joined, "tokens": texts})
    return out


def _math_supports_candidate(target: Dict[str, Any], field: str, value: str) -> Dict[str, Any]:
    row = dict(target.get("row_snapshot") or {})
    if not row:
        return {"status": "not_available"}
    f = normalize_field_name(field)
    row[f] = value
    family = str(target.get("family") or target.get("table_family") or "").lower()
    if family in {"budget", "orcamento", "orcamento_sintetico"}:
        return math_triplet_status(row, quantity_field="quant", unit_field="custo_unitario_com_bdi", total_field="custo_parcial")
    return math_triplet_status(row, quantity_field="quant", unit_field="valor_unit", total_field="total")


def _recover_non_description_field(target: Dict[str, Any], line: Dict[str, Any], table: Dict[str, Any], family: str, *, context: Dict[str, Any] | None = None) -> Dict[str, Any] | None:
    field = normalize_field_name(target.get("field") or "")
    if candidate_kind(field) == "description":
        return None
    x0, x1, canonical = _band_for_target_field(table, field, family, line)
    candidates = _field_candidates_from_line(line, field, x0, x1, context=context)
    if not candidates:
        return None
    scored = []
    for cand in candidates:
        score = 0.76
        if x0 is not None:
            score += 0.08
        math_status = _math_supports_candidate(target, field, cand["value"])
        if math_status.get("ok") is True:
            score += 0.12
        elif math_status.get("status") == "missing_values":
            score += 0.02
        elif math_status.get("ok") is False:
            score -= 0.12
        scored.append({**cand, "confidence": round(max(0.0, min(score, 0.98)), 3), "math_status": math_status, "column_band": {"canonical": canonical, "x0": x0, "x1": x1}})
    scored.sort(key=lambda c: float(c.get("confidence") or 0), reverse=True)
    return scored[0]


def recover_fields(pdf_bytes: bytes, payload: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    payload = dict(payload or {})
    page_map_raw = {str(k): int(v) for k, v in dict(payload.get("page_map") or payload.get("targeted_recovery_pdf", {}).get("page_map") or {}).items()}
    original_to_local = {int(v): int(k) for k, v in page_map_raw.items()}
    targets = [t for t in list(payload.get("targets") or []) if isinstance(t, dict)]
    table_cache: Dict[str, Dict[str, Any]] = {}
    geometry_started = time.perf_counter()
    pages = extract_page_geometry(pdf_bytes)
    geometry_ms = round((time.perf_counter() - geometry_started) * 1000, 3)
    patches: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []

    for target in targets:
        original_page = int(target.get("page") or target.get("pagina") or 0)
        local_page = original_to_local.get(original_page) or int(target.get("local_page") or 0)
        page_geometry = pages.get(local_page)
        if not page_geometry:
            unresolved.append({**target, "reason": "target_page_not_in_minipdf", "original_page": original_page, "local_page": local_page})
            continue
        lines = list(page_geometry.get("lines") or [])
        codigo = str(target.get("codigo") or "").strip()
        banco = str(target.get("banco") or target.get("fonte") or "").strip()
        family = _target_family(target)
        page_line_graph = build_page_line_graph(lines, family=family)
        gap_profile = line_vertical_gap_profile(lines)
        table = table_cache.setdefault(family, _table_for_family(payload, family))
        desc_x0, desc_x1 = _column_band(table, "descricao")
        if family == "budget" and desc_x0 is None:
            # Some Docling/budget schemas use especificacao as the canonical name.
            desc_x0, desc_x1 = _column_band(table, "especificacao")
        line_idx, line = _find_target_line(lines, codigo, banco)
        if line is None:
            unresolved.append({**target, "reason": "target_line_not_found", "local_page": local_page})
            continue
        codigo_bbox = _match_bbox(line, codigo)
        banco_bbox = _match_bbox(line, banco) if banco else None
        target_field = normalize_field_name(target.get("field") or _description_field_for(target))
        if candidate_kind(target_field) != "description":
            best_value = _recover_non_description_field(target, line, table, family, context=payload)
            if best_value and float(best_value.get("confidence") or 0.0) >= float(payload.get("apply_confidence_min") or 0.85):
                patches.append({
                    "target_id": target.get("target_id"),
                    "path": target.get("path") or [],
                    "collection": target.get("collection"),
                    "comp_key": target.get("comp_key") or target.get("key"),
                    "row_group": target.get("row_group"),
                    "row_index": target.get("row_index"),
                    "field": target_field,
                    "value": best_value.get("value"),
                    "previous_value": _clean(target.get("current_value") or ""),
                    "confidence": round(float(best_value.get("confidence") or 0.0), 3),
                    "applied_by_default": True,
                    "source": "deep_area_sweep_executor",
                    "page": original_page,
                    "local_page": local_page,
                    "codigo": codigo,
                    "banco": banco,
                    "target_issue": str(target.get("issue") or target.get("reason") or "line_certainty_unclosed_field"),
                    "evidence": {
                        "line_text": line.get("text", ""),
                        "codigo_bbox": codigo_bbox,
                        "banco_bbox": banco_bbox,
                        "target_family": family,
                        "candidate_strategy": "target_line_column_band",
                        "column_band": best_value.get("column_band"),
                        "source_text": best_value.get("source_text"),
                        "tokens": best_value.get("tokens"),
                        "validation": best_value.get("validation"),
                        "math_status": best_value.get("math_status"),
                    },
                })
            else:
                unresolved.append({**target, "reason": "non_description_candidate_not_found_or_low_confidence", "candidate": best_value, "local_page": local_page})
            continue
        # Dynamic fallback: if the schema band is absent, capture after banco/code until next schema boundary.
        fx0 = desc_x0
        fx1 = desc_x1
        if fx0 is None:
            fx0 = (_as_float((banco_bbox or {}).get("x1")) or _as_float((codigo_bbox or {}).get("x1")) or _as_float(line.get("x0")))
        base_text = _text_in_band(line, fx0, fx1)
        current_value = _clean(target.get("current_value") or "")
        issue = str(target.get("issue") or "").lower()
        registry_entry = _registry_entry_for(payload, codigo, banco)
        target = dict(target)
        base_bbox = _match_bbox(line, base_text)
        target["_recovery_current_occupancy"] = cell_occupancy_ratio(base_bbox, fx0, fx1)
        candidates = _build_recovery_candidates(lines, line_idx, base_text, table, fx0, fx1, family=family, gap_profile=gap_profile)
        reg_desc = _clean(registry_entry.get("descricao") or registry_entry.get("description") or "")
        # If registry has a confirmed longer description for this code, include it
        # as a candidate, but the scoring still verifies it against current text.
        if reg_desc and (not current_value or _contains_token_sequence(reg_desc, current_value) or is_truncated_text(current_value)):
            candidates.append({"value": reg_desc, "strategy": "confirmed_description_registry", "fragments": [], "registry": {k: v for k, v in registry_entry.items() if k != "descricao"}})
        best = _choose_best_candidate(target, candidates, registry_entry)
        text = _clean((best or {}).get("value"))
        confidence = float((best or {}).get("confidence") or 0.0)
        if text and current_value and _norm(text) == _norm(current_value):
            unresolved.append({**target, "reason": "no_op_same_value", "confidence": round(confidence, 3), "candidate_value": text, "candidate_strategy": (best or {}).get("strategy"), "local_page": local_page})
            continue
        # Keep the legacy bbox-based confidence as a floor for simple downward cases.
        legacy_conf = _confidence_for(target, text, line, codigo_bbox, banco_bbox) if text else 0.0
        confidence = max(confidence, legacy_conf if (best or {}).get("strategy") in {"target_line_only", "target_plus_downward_fragments"} else confidence)
        candidate_similarity = similarity(current_value, text) if current_value and text else 0.0
        current_complete_lock = bool(current_value and not is_truncated_text(current_value) and candidate_similarity >= 0.97)
        confirmed_current_lock = _registry_confirms_current(target, registry_entry)
        candidate_is_registry = (best or {}).get("strategy") == "confirmed_description_registry"
        strict_truncation_gain = _looks_truncated(current_value, text) and candidate_similarity >= 0.78
        registry_gain = bool(candidate_is_registry and text and (not current_value or similarity(text, registry_entry.get("descricao") or registry_entry.get("description") or "") >= 0.94))
        safe_broken_gain = bool(("broken" in issue) and is_truncated_text(current_value) and candidate_similarity >= 0.86)
        safe_upward_broken_gain = bool(("broken" in issue) and (best or {}).get("strategy") == "upward_fragments_plus_target" and candidate_similarity >= 0.70)
        should_patch = bool(text) and not current_complete_lock and not confirmed_current_lock and (
            not current_value
            or "trunc" in issue and (strict_truncation_gain or registry_gain)
            or safe_broken_gain
            or safe_upward_broken_gain
            or registry_gain and len(text) > len(current_value) + 3
        )
        if should_patch and confidence >= float(payload.get("apply_confidence_min") or 0.85):
            patches.append({
                "target_id": target.get("target_id"),
                "path": target.get("path") or [],
                "collection": target.get("collection"),
                "comp_key": target.get("comp_key") or target.get("key"),
                "row_group": target.get("row_group"),
                "row_index": target.get("row_index"),
                "field": _description_field_for(target),
                "value": text,
                "previous_value": current_value,
                "confidence": round(confidence, 3),
                "applied_by_default": True,
                "source": "normalizer_targeted_recovery",
                "page": original_page,
                "local_page": local_page,
                "codigo": codigo,
                "banco": banco,
                "target_issue": issue,
                "evidence": {
                    "line_text": line.get("text", ""),
                    "codigo_bbox": codigo_bbox,
                    "banco_bbox": banco_bbox,
                    "descricao_band": {"x0": fx0, "x1": fx1},
                    "recovered_text": text,
                    "target_family": family,
                    "candidate_strategy": (best or {}).get("strategy"),
                    "fragments": (best or {}).get("fragments") or [],
                    "hypotheses": (best or {}).get("hypotheses") or [],
                    "registry_used": bool(registry_entry),
                    "column_order_used": [_canonical(c) for c in _all_columns(table)],
                    "page_line_graph_summary": {"line_count": page_line_graph.get("line_count"), "barrier_count": page_line_graph.get("barrier_count"), "floating_fragment_count": page_line_graph.get("floating_fragment_count")},
                    "vertical_gap_profile": gap_profile,
                    "current_cell_occupancy": target.get("_recovery_current_occupancy"),
                    "ownership": ownership_report(text, current_value=current_value, target_confirmed=(registry_entry.get("descricao") or registry_entry.get("description") or ""), neighbor_context=target.get("neighbor_context") or {}),
                    "safety_lock": (best or {}).get("safety_lock"),
                },
            })
        else:
            unresolved.append({**target, "reason": "low_confidence_or_no_improvement", "confidence": round(confidence, 3), "candidate_value": text, "candidate_strategy": (best or {}).get("strategy"), "safety_lock": (best or {}).get("safety_lock"), "hypotheses": (best or {}).get("hypotheses") or [], "page_line_graph_summary": {"line_count": page_line_graph.get("line_count"), "barrier_count": page_line_graph.get("barrier_count"), "floating_fragment_count": page_line_graph.get("floating_fragment_count")}, "local_page": local_page})

    return {
        "version": VERSION,
        "status": "ok",
        "mode": "targeted_recovery",
        "patches": patches,
        "unresolved": unresolved,
        "summary": {"targets": len(targets), "patches": len(patches), "unresolved": len(unresolved)},
        "metadata": {"performance_trace": {"normalizer_recovery_geometry_ms": geometry_ms, "normalizer_recovery_total_ms": round((time.perf_counter() - started) * 1000, 3), "page_count": len(pages)}}
    }
