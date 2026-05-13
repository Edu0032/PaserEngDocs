from __future__ import annotations

"""Candidate Profile Consensus Engine.

This stage orchestrates the evidence that previous stages already learned:
Docling/PyMuPDF profiles, budget <-> composition descriptions, neighbour
ownership, pollution guards, and conservative current-value preservation.

It is intentionally additive and non-destructive.  A patch is applied only when
multiple profiles agree that a new candidate is safer than the current value.
When in doubt, the engine records the ambiguity and leaves the JSON untouched.
"""

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Tuple

from app.parser.broken_line_recovery import (
    codebank,
    is_truncated_text,
    pollution_reason,
    similarity,
    text_quality_score,
)
from app.parser.code_value_classifier import clean_text, norm_text
from app.parser.description_ownership_resolver import ownership_report
from app.parser.selective_field_reparse_executor import (
    RowRef,
    _attach_neighbor_contexts,
    _build_evidence_candidates,
    _get_by_path,
    _is_weak_description,
    _row_refs,
    _set_by_path,
    is_confirmed_candidate,
)

VERSION = "v61.0.35-candidate-profile-consensus-engine"
DESCRIPTION_FIELDS = {"descricao", "especificacao"}


@dataclass
class ConsensusCandidate:
    value: str
    origin: str
    profiles: List[str] = field(default_factory=list)
    score: float = 0.0
    vetoes: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def normalized(self) -> str:
        return norm_text(self.value)

    def add(self, score: float, reason: str, profile: str | None = None) -> None:
        self.score += score
        if reason:
            self.reasons.append(reason)
        if profile and profile not in self.profiles:
            self.profiles.append(profile)

    def veto(self, reason: str) -> None:
        if reason not in self.vetoes:
            self.vetoes.append(reason)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "origin": self.origin,
            "profiles": self.profiles,
            "score": round(self.score, 4),
            "vetoes": list(self.vetoes),
            "reasons": self.reasons[:12],
            "metadata": self.metadata,
        }


def _clean(value: Any) -> str:
    return clean_text(value)


def _norm(value: Any) -> str:
    return norm_text(value)


def _tokens_with_original(value: Any) -> List[Tuple[str, str]]:
    text = _clean(value)
    # Keep hyphenated codes/words together but ignore standalone separators for
    # ownership subtraction.  This keeps strings such as CM-30 intact.
    originals = re.findall(r"[A-Za-zÀ-ÿ0-9]+(?:[-/][A-Za-zÀ-ÿ0-9]+)*|[%²³]", text)
    return [(tok, _norm(tok)) for tok in originals if _norm(tok)]


def _longest_common_span(current_tokens: List[Tuple[str, str]], neighbor_tokens: List[Tuple[str, str]]) -> Tuple[int, int, int]:
    if not current_tokens or not neighbor_tokens:
        return (-1, -1, 0)
    cur_norm = [n for _, n in current_tokens]
    nei_norm = [n for _, n in neighbor_tokens]
    best = (-1, -1, 0)
    # O(n*m*span) is fine here: lines are short and this runs only on weak fields.
    for i in range(len(cur_norm)):
        for j in range(len(nei_norm)):
            k = 0
            while i + k < len(cur_norm) and j + k < len(nei_norm) and cur_norm[i + k] == nei_norm[j + k]:
                k += 1
            if k > best[2]:
                best = (i, i + k, k)
    return best


def _subtract_neighbor_fragments(current: Any, neighbor_context: Dict[str, Any] | None) -> Dict[str, Any]:
    """Return a candidate obtained by removing text owned by neighbours.

    This implements the ANP-01 class of fixes: if the current text is a long
    polluted concatenation containing fragments from the previous and next rows,
    remove the fragments that are strongly explained by those neighbours and
    keep the remaining target-owned text.
    """
    cur_text = _clean(current)
    cur_tokens = _tokens_with_original(cur_text)
    if not cur_tokens:
        return {"accepted": False, "reason": "empty_current"}
    remove = [False] * len(cur_tokens)
    matches: List[Dict[str, Any]] = []
    ctx = neighbor_context or {}
    neighbor_objs: List[Tuple[str, Dict[str, Any]]] = []
    for role in ("prev", "previous", "above", "next", "below"):
        obj = ctx.get(role)
        if isinstance(obj, dict):
            neighbor_objs.append(("prev" if role in {"prev", "previous", "above"} else "next", obj))
    for role, obj in neighbor_objs:
        desc = _clean(obj.get("confirmed_description") or obj.get("descricao") or obj.get("especificacao") or "")
        if not desc:
            continue
        ntoks = _tokens_with_original(desc)
        start, end, length = _longest_common_span(cur_tokens, ntoks)
        # A fragment with 4+ tokens is strong enough.  A shorter fragment is only
        # removed when it is at the boundary and contains an AF anchor or starts
        # with an orphan dash in the original current string.
        boundary = start in {0, 1} or end >= len(cur_tokens) - 1
        normalized_span = " ".join(tok for _, tok in cur_tokens[start:end]) if start >= 0 else ""
        strong_short = boundary and length >= 3 and ("AF_" in _norm(desc) or "AF_" in _norm(cur_text))
        if length >= 4 or strong_short:
            for i in range(max(0, start), min(len(remove), end)):
                remove[i] = True
            matches.append({
                "role": role,
                "codigo": obj.get("codigo") or "",
                "banco": obj.get("banco") or "",
                "item": obj.get("item") or "",
                "length": length,
                "span": [start, end],
                "text": normalized_span,
            })
    if not any(remove):
        return {"accepted": False, "reason": "no_neighbor_fragment_match"}
    remaining = [orig for idx, (orig, _) in enumerate(cur_tokens) if not remove[idx]]
    candidate = " ".join(remaining).strip(" -–—;:,.\n\t")
    candidate = re.sub(r"\s+", " ", candidate).strip()
    if not candidate:
        return {"accepted": False, "reason": "empty_after_subtraction", "matches": matches}
    if len(candidate) >= len(cur_text) - 5:
        return {"accepted": False, "reason": "subtraction_did_not_shorten", "matches": matches, "candidate": candidate}
    if pollution_reason(candidate) or candidate.startswith("-") or _norm(candidate).count("AF_") >= 2:
        return {"accepted": False, "reason": "candidate_still_polluted", "matches": matches, "candidate": candidate}
    return {"accepted": True, "candidate": candidate, "matches": matches, "reason": "neighbor_fragment_subtraction"}


def _candidate_is_clean(value: Any) -> Tuple[bool, str]:
    text = _clean(value)
    if not text:
        return False, "empty"
    if text.lstrip().startswith("-"):
        return False, "leading_orphan_fragment"
    if "=>" in text:
        return False, "summary_marker_arrow"
    if _norm(text).count("AF_") >= 2:
        return False, "multiple_service_anchors"
    reason = pollution_reason(text)
    if reason:
        return False, reason
    return True, ""


def _make_candidate(value: Any, origin: str, profile: str, *, metadata: Dict[str, Any] | None = None) -> ConsensusCandidate | None:
    text = _clean(value)
    if not text:
        return None
    c = ConsensusCandidate(text, origin=origin, profiles=[profile], metadata=metadata or {})
    ok, reason = _candidate_is_clean(text)
    if not ok:
        c.veto(reason)
    return c


def _dedupe_candidates(cands: Iterable[ConsensusCandidate | None]) -> List[ConsensusCandidate]:
    by_norm: Dict[str, ConsensusCandidate] = {}
    for cand in cands:
        if cand is None or not cand.value:
            continue
        key = cand.normalized
        if key in by_norm:
            existing = by_norm[key]
            existing.score += cand.score
            for p in cand.profiles:
                if p not in existing.profiles:
                    existing.profiles.append(p)
            existing.reasons.extend(cand.reasons)
            for v in cand.vetoes:
                existing.veto(v)
            existing.metadata.update(cand.metadata)
        else:
            by_norm[key] = cand
    return list(by_norm.values())


def _collect_candidates(row: RowRef, registry: Dict[str, Any]) -> List[ConsensusCandidate]:
    current = row.current
    candidates: List[ConsensusCandidate | None] = []
    cur = _make_candidate(current, "current_value", "conservative_current")
    if cur:
        cur.add(1.15, "current_value_is_baseline", "conservative_current")
        candidates.append(cur)
    evidence = registry.get(row.key)
    if evidence is not None:
        ev = _make_candidate(evidence.descricao, "evidence_graph", "cross_table_registry", metadata={"occurrences": evidence.occurrences, "sources": evidence.sources[:8]})
        if ev:
            ev.add(1.25 + min(evidence.occurrences, 4) * 0.35, "candidate_from_description_registry", "cross_table_registry")
            if is_confirmed_candidate(evidence):
                ev.add(1.35, "candidate_confirmed_by_registry", "evidence_graph")
            candidates.append(ev)
    subtraction = _subtract_neighbor_fragments(current, row.neighbor_context)
    if subtraction.get("accepted"):
        sub = _make_candidate(subtraction.get("candidate"), "neighbor_subtraction", "description_ownership")
        if sub:
            sub.add(2.25, "candidate_removes_neighbor_owned_fragments", "description_ownership")
            sub.metadata["subtraction"] = subtraction
            candidates.append(sub)
    # When the current is polluted but contains the registry candidate, provide a
    # clean reverse-repair candidate even when neighbour subtraction did not fire.
    if evidence is not None and current and evidence.descricao and _norm(evidence.descricao) in _norm(current):
        rev = _make_candidate(evidence.descricao, "reverse_repair_registry", "cross_table_registry")
        if rev:
            rev.add(2.0, "clean_registry_candidate_inside_current", "reverse_repair")
            candidates.append(rev)
    return _dedupe_candidates(candidates)


def _score_consensus_candidate(row: RowRef, candidate: ConsensusCandidate, all_candidates: List[ConsensusCandidate], registry: Dict[str, Any]) -> ConsensusCandidate:
    current = row.current
    value = candidate.value
    weak_reason = _is_weak_description(current)
    ok, clean_reason = _candidate_is_clean(value)
    if not ok:
        candidate.veto(clean_reason)
    own = ownership_report(value, current_value=current, target_confirmed=value, neighbor_context=row.neighbor_context)
    candidate.metadata["ownership"] = own
    if own.get("has_neighbor_hit"):
        candidate.veto("candidate_contains_neighbor_description")
    candidate.score += text_quality_score(value)
    candidate.reasons.append("text_quality_score")
    if weak_reason:
        candidate.add(0.85, f"current_is_weak:{weak_reason}", "weak_field_detector")
    else:
        candidate.add(0.65, "current_not_weak_keep_baseline_bias", "weak_field_detector") if candidate.origin == "current_value" else candidate.add(-1.25, "current_not_weak_candidate_penalty", "weak_field_detector")
    sim = similarity(current, value) if current else 0.0
    candidate.metadata["similarity_to_current"] = round(sim, 4)
    if candidate.origin != "current_value":
        if current and sim >= 0.985:
            candidate.veto("no_op_candidate")
        if current and len(value) > max(len(current) * 1.7, len(current) + 65) and not is_truncated_text(current):
            candidate.veto("candidate_too_long_without_truncation")
        if current and len(value) < len(current) - 20:
            # Shorter replacements are allowed only when current is provably polluted.
            if not (weak_reason and (current.lstrip().startswith("-") or "polluted" in weak_reason or "=>" in current or _norm(current).count("AF_") >= 2)):
                candidate.veto("shorter_candidate_without_polluted_current")
            else:
                candidate.add(1.1, "shorter_clean_candidate_repairs_polluted_current", "reverse_repair")
        if current and sim < 0.45 and not (_norm(value) in _norm(current) or _norm(current) in _norm(value)):
            candidate.veto("low_similarity_to_current")
    if candidate.origin == "current_value":
        # Current value wins by default unless weak/polluted and another clean
        # candidate accumulates much stronger evidence.
        if not weak_reason:
            candidate.add(2.0, "current_clean_and_stable", "conservative_current")
        else:
            candidate.add(-0.6, "current_weak_penalty", "weak_field_detector")
    if len(candidate.profiles) >= 2:
        candidate.add(0.6, "multi_profile_support", "consensus")
    if len(candidate.profiles) >= 3:
        candidate.add(0.5, "three_or_more_profiles_support", "consensus")
    # Candidate should not lose to another candidate with identical value but
    # fewer profiles; dedupe normally prevents that, but keep a safety guard.
    candidate.score = round(candidate.score, 4)
    return candidate


def _choose_candidate(row: RowRef, candidates: List[ConsensusCandidate], registry: Dict[str, Any]) -> Dict[str, Any]:
    scored = [_score_consensus_candidate(row, c, candidates, registry) for c in candidates]
    accepted_pool = [c for c in scored if not c.vetoes]
    if not accepted_pool:
        return {"decision": "no_safe_candidate", "candidates": [c.as_dict() for c in scored]}
    accepted_pool.sort(key=lambda c: c.score, reverse=True)
    best = accepted_pool[0]
    current = next((c for c in scored if c.origin == "current_value"), None)
    second = accepted_pool[1] if len(accepted_pool) > 1 else None
    current_norm = _norm(row.current)
    if _norm(best.value) == current_norm:
        return {"decision": "keep_current", "best": best.as_dict(), "candidates": [c.as_dict() for c in scored]}
    # A vetoed current value is not allowed to block a clean candidate.
    current_score = (current.score if (current and not current.vetoes) else 0.0)
    margin = best.score - current_score
    # Stronger margin required to replace a clean current value; smaller margin
    # accepted when the current value is explicitly polluted/weak.
    weak_reason = _is_weak_description(row.current)
    required_margin = 1.15 if weak_reason else 2.2
    if margin < required_margin:
        return {"decision": "ambiguous_margin", "best": best.as_dict(), "current_score": round(current_score, 4), "required_margin": required_margin, "candidates": [c.as_dict() for c in scored]}
    if second and best.score - second.score < 0.45 and _norm(second.value) != current_norm:
        return {"decision": "ambiguous_competing_candidates", "best": best.as_dict(), "second": second.as_dict(), "candidates": [c.as_dict() for c in scored]}
    return {"decision": "apply", "best": best.as_dict(), "current_score": round(current_score, 4), "margin": round(margin, 4), "candidates": [c.as_dict() for c in scored]}


def _field_path(row: RowRef) -> List[Any]:
    return list(row.path) + [row.field]


def run_candidate_profile_consensus_engine(final_result: Dict[str, Any] | None, *, apply: bool = True) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    result = copy.deepcopy(final_result or {})
    rows = _row_refs(result)
    registry = _build_evidence_candidates(rows)
    _attach_neighbor_contexts(rows, registry)
    applied: List[Dict[str, Any]] = []
    kept: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    reviewed = 0
    for row in rows:
        if not row.key:
            continue
        current_issue = _is_weak_description(row.current)
        # Run on weak/polluted fields and on fields for which neighbour context
        # can produce a reverse repair.  Clean current fields are still scored
        # but generally keep_current; this gives the debug overlay a coherent
        # reason without making the stage aggressive.
        candidates = _collect_candidates(row, registry)
        if len(candidates) <= 1 and not current_issue:
            continue
        reviewed += 1
        decision = _choose_candidate(row, candidates, registry)
        base_record = {
            "target_id": f"{'.'.join(map(str, row.path))}::{row.field}",
            "path": _field_path(row),
            "field": row.field,
            "family": row.family,
            "codigo": row.codigo,
            "banco": row.banco,
            "item": row.item,
            "before": row.current,
            "decision": decision.get("decision"),
            "current_issue": current_issue,
            "best": decision.get("best"),
            "candidates": decision.get("candidates", [])[:12],
        }
        if decision.get("decision") == "apply":
            new_value = ((decision.get("best") or {}).get("value") or "").strip()
            if new_value and _norm(new_value) != _norm(row.current):
                if apply and _set_by_path(result, _field_path(row), new_value):
                    applied.append({**base_record, "after": new_value})
                else:
                    rejected.append({**base_record, "decision": "patch_target_not_found"})
            else:
                kept.append({**base_record, "decision": "keep_current_noop"})
        elif decision.get("decision") == "keep_current":
            kept.append(base_record)
        else:
            rejected.append(base_record)
    summary = {
        "rows_seen": len(rows),
        "rows_reviewed": reviewed,
        "confirmed_descriptions": sum(1 for c in registry.values() if is_confirmed_candidate(c)),
        "applied": len(applied),
        "kept": len(kept),
        "rejected_or_ambiguous": len(rejected),
    }
    report = {
        "version": VERSION,
        "mode": "candidate_profile_consensus_engine",
        "summary": summary,
        "applied": applied,
        "kept": kept[:120],
        "rejected_or_ambiguous": rejected[:200],
        "confirmed_descriptions": {k: v.as_dict() for k, v in registry.items() if is_confirmed_candidate(v)},
    }
    return result, report
