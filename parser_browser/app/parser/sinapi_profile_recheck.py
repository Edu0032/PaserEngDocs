from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from app.core.schemas import BlocoComposicao, Composicoes, LinhaComposicao, LinhaInsumo
from app.parser.broken_line_recovery import pollution_reason as _shared_pollution_reason

VERSION = 'v61.0.75-correction-output-contract-and-review-index'


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ").strip())


def _norm(value: Any) -> str:
    text = _clean(value).upper()
    repl = str.maketrans({
        "Á":"A","À":"A","Â":"A","Ã":"A","Ä":"A",
        "É":"E","È":"E","Ê":"E","Ë":"E",
        "Í":"I","Ì":"I","Î":"I","Ï":"I",
        "Ó":"O","Ò":"O","Ô":"O","Õ":"O","Ö":"O",
        "Ú":"U","Ù":"U","Û":"U","Ü":"U",
        "Ç":"C",
        "á":"A","à":"A","â":"A","ã":"A","ä":"A",
        "é":"E","è":"E","ê":"E","ë":"E",
        "í":"I","ì":"I","î":"I","ï":"I",
        "ó":"O","ò":"O","ô":"O","õ":"O","ö":"O",
        "ú":"U","ù":"U","û":"U","ü":"U",
        "ç":"C",
    })
    return text.translate(repl)


def _canon_bank(value: Any) -> str:
    text = _norm(value).replace(" ", "")
    if text in {"SICRO", "SICRO2", "SICRO3", "DNIT"}:
        return "SICRO"
    if text in {"PROPRIO", "PRÓPRIO", "ANP"}:
        return "PRÓPRIO"
    if text in {"SINAPI", "CAIXA"}:
        return "SINAPI"
    return text or _clean(value).upper()


def _is_sicro(value: Any) -> bool:
    return _canon_bank(value) == "SICRO"


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(".", "").replace(",", ".")
    try:
        return float(text)
    except Exception:
        return None


def _line_key(line: LinhaComposicao) -> str:
    code = _clean(getattr(line, "codigo", "")).upper().replace(" ", "")
    bank = _canon_bank(getattr(line, "banco", ""))
    return f"{code}|{bank}" if code and bank else ""


def _is_truncated_text(text: Any) -> bool:
    norm = _norm(text)
    if not norm:
        return False
    tail = norm.split()[-1]
    return tail in {"DE", "DA", "DO", "DAS", "DOS", "PARA", "COM", "E", "EM", "A", "O"}


def _text_score(text: Any) -> float:
    raw = _clean(text)
    if not raw:
        return 0.0
    tokens = raw.split()
    score = min(len(raw) / 120.0, 1.0) + min(len(tokens) / 18.0, 1.0)
    if _is_truncated_text(raw):
        score -= 0.5
    if re.search(r"\bAF_\d{2}/\d{4}\b", raw, flags=re.I):
        score += 0.2
    if any(ch in raw for ch in "()/-"):
        score += 0.1
    return round(max(score, 0.0), 4)


def _recheck_rules(config: dict | None) -> Dict[str, Any]:
    rules = (((config or {}).get('recheck_rules') or {}).get('sinapi_like') or {})
    return {
        'min_description_patch_score': float(rules.get('min_description_patch_score') or 8.0),
        'min_improvement_score': float(rules.get('min_improvement_score') or 1.25),
        'pollution_veto_terms': list(rules.get('pollution_veto_terms') or ['Custo Total das Atividades', 'Valor com BDI', 'Valor do BDI', 'MO sem LS', 'Material Material', '=>']),
        'reject_long_numeric_sequences': bool(rules.get('reject_long_numeric_sequences', True)),
        'audit_all_decisions': bool(rules.get('audit_all_decisions', True)),
    }


def _pollution_reason(text: Any, rules: Dict[str, Any] | None = None) -> str:
    # v61.0.24: delegate the core veto logic to the shared recovery engine.
    # The previous regex had control characters and failed to catch generic
    # repeated labels such as "Insumo Insumo".
    shared = _shared_pollution_reason(text)
    if shared:
        return shared
    raw = _clean(text)
    if not raw:
        return 'empty_candidate'
    norm = _norm(raw)
    rules = rules or _recheck_rules(None)
    for term in rules.get('pollution_veto_terms') or []:
        if _norm(term) in norm:
            return f'pollution_term:{term}'
    if rules.get('reject_long_numeric_sequences'):
        nums = re.findall(r'(?<![A-Z0-9])\d{1,3}(?:\.\d{3})*,\d{2,7}(?![A-Z0-9])', raw)
        if len(nums) >= 4:
            return 'long_numeric_sequence'
    return ''


def _description_patch_score(current: str, candidate: str, registry_score: float) -> float:
    cur_score = _text_score(current)
    cand_score = _text_score(candidate)
    improvement = max(0.0, cand_score - cur_score)
    prefix_bonus = 1.0 if current and _norm(candidate).startswith(_norm(current)) else 0.0
    trunc_bonus = 1.0 if _is_truncated_text(current) else 0.0
    length_bonus = min(max(len(candidate) - len(current), 0) / 45.0, 2.0)
    return round((float(registry_score or cand_score) * 4.0) + improvement * 3.0 + prefix_bonus + trunc_bonus + length_bonus, 4)


def _structured_table_bands(context: dict | None) -> Dict[str, Dict[str, Any]]:
    """Collect Docling/Normalizer column bands by canonical name.

    This is intentionally tolerant to several payload shapes used across v60/v61.
    The result is audit/profile data and evidence for re-checking, not a hard
    override.  PyMuPDF recovery still validates line evidence before applying
    patches.
    """
    ctx = dict(context or {})
    structured = ctx.get("normalizer_clean_payload") or ctx.get("structured_tables") or ctx.get("docling_clean_payload") or {}
    candidates: List[Dict[str, Any]] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if isinstance(obj.get("columns"), list):
                candidates.extend([c for c in obj.get("columns") or [] if isinstance(c, dict)])
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(structured)
    out: Dict[str, Dict[str, Any]] = {}
    for col in candidates:
        canonical = str(col.get("canonical") or col.get("canonical_name") or col.get("name") or "").strip()
        if not canonical:
            continue
        try:
            x0 = float(col.get("x0")) if col.get("x0") is not None else None
            x1 = float(col.get("x1")) if col.get("x1") is not None else None
        except Exception:
            x0, x1 = None, None
        bucket = out.setdefault(canonical, {"canonical": canonical, "observations": 0, "x0_values": [], "x1_values": [], "sources": []})
        bucket["observations"] += 1
        if x0 is not None:
            bucket["x0_values"].append(x0)
        if x1 is not None:
            bucket["x1_values"].append(x1)
        src = col.get("source") or col.get("family") or "docling_or_normalizer"
        if src not in bucket["sources"]:
            bucket["sources"].append(src)
    for info in out.values():
        xs0 = sorted(info.pop("x0_values") or [])
        xs1 = sorted(info.pop("x1_values") or [])
        if xs0:
            info["x0_median"] = round(xs0[len(xs0)//2], 3)
        if xs1:
            info["x1_median"] = round(xs1[len(xs1)//2], 3)
    return out


def _all_blocks(comp: Composicoes) -> Iterable[Tuple[str, str, BlocoComposicao]]:
    for key, block in (comp.principais or {}).items():
        yield "principais", key, block
    for key, block in (comp.auxiliares_globais or {}).items():
        yield "auxiliares_globais", key, block


def _all_lines(block: BlocoComposicao) -> Iterable[Tuple[str, int | None, LinhaComposicao]]:
    if getattr(block, "principal", None) is not None:
        yield "principal", None, block.principal
    for idx, row in enumerate(block.composicoes_auxiliares or []):
        yield "composicoes_auxiliares", idx, row
    for idx, row in enumerate(block.insumos or []):
        yield "insumos", idx, row


def _registry_add(registry: Dict[str, Dict[str, Any]], line: LinhaComposicao, *, source: str, rules: Dict[str, Any] | None = None) -> None:
    if _is_sicro(getattr(line, "banco", "")):
        return
    key = _line_key(line)
    desc = _clean(getattr(line, "descricao", ""))
    if not key or not desc:
        return
    veto = _pollution_reason(desc, rules)
    if veto:
        return
    score = _text_score(desc)
    current = registry.get(key)
    if current is None or score > float(current.get("score") or 0):
        registry[key] = {
            "descricao": desc,
            "score": score,
            "source": source,
            "codigo": _clean(getattr(line, "codigo", "")),
            "banco": _canon_bank(getattr(line, "banco", "")),
        }


def _maybe_repair_line_description(line: LinhaComposicao, registry: Dict[str, Dict[str, Any]], *, rules: Dict[str, Any] | None = None) -> dict | None:
    rules = rules or _recheck_rules(None)
    if _is_sicro(getattr(line, "banco", "")):
        return None
    key = _line_key(line)
    if not key or key not in registry:
        return None
    current = _clean(getattr(line, "descricao", ""))
    best = _clean(registry[key].get("descricao"))
    decision = {
        "codebank": key,
        "field": "descricao",
        "before": current,
        "candidate": best,
        "source": registry[key].get("source"),
        "decision": "rejected",
        "reasons": [],
        "score": 0.0,
    }
    if not best:
        decision["reasons"].append("empty_candidate")
        return decision if rules.get('audit_all_decisions') else None
    veto = _pollution_reason(best, rules)
    if veto:
        decision["reasons"].append(veto)
        return decision if rules.get('audit_all_decisions') else None
    if current and not _is_truncated_text(current) and len(current) >= len(best) - 5:
        decision["reasons"].append("current_description_is_already_complete")
        return decision if rules.get('audit_all_decisions') else None
    if current and not _norm(best).startswith(_norm(current)) and _text_score(best) < _text_score(current) + float(rules.get('min_improvement_score') or 1.25):
        decision["reasons"].append("candidate_not_prefix_and_insufficient_improvement")
        return decision if rules.get('audit_all_decisions') else None
    score = _description_patch_score(current, best, float(registry[key].get("score") or 0))
    decision["score"] = score
    if score < float(rules.get('min_description_patch_score') or 8.0):
        decision["reasons"].append("score_below_threshold")
        return decision if rules.get('audit_all_decisions') else None
    before = current
    line.descricao = best
    decision.update({
        "after": best,
        "decision": "applied",
        "reason": "missing_or_truncated_description_repaired_from_document_registry_with_gates",
        "reasons": ["same_codebank", "pollution_veto_passed", "score_passed"],
    })
    return decision


def _try_math_repair_line(line: LinhaComposicao) -> dict | None:
    if _is_sicro(getattr(line, "banco", "")):
        return None
    q = _as_float(getattr(line, "quant", None))
    vu = _as_float(getattr(line, "valor_unit", None))
    total = _as_float(getattr(line, "total", None))
    if q is None or q == 0:
        return None
    # Fill missing total when quantity and unit are reliable.
    if total is None and vu is not None:
        computed = round(q * vu, 6)
        line.total = computed
        return {"field": "total", "action": "filled_from_quant_x_valor_unit", "computed": computed}
    if vu is None and total is not None:
        computed = round(total / q, 6)
        line.valor_unit = computed
        return {"field": "valor_unit", "action": "filled_from_total_div_quant", "computed": computed}
    if vu is None or total is None:
        return None
    delta = abs(q * vu - total)
    tolerance = max(0.05, abs(total) * 0.005)
    if delta <= tolerance:
        return None
    # Conservative swap repair: sometimes valor_unit and total are inverted.
    swapped_delta = abs(q * total - vu)
    swapped_tolerance = max(0.05, abs(vu) * 0.005)
    if swapped_delta < delta and swapped_delta <= swapped_tolerance:
        before = {"valor_unit": line.valor_unit, "total": line.total}
        line.valor_unit, line.total = line.total, line.valor_unit
        return {"field": "valor_unit,total", "action": "swapped_by_math_hypothesis", "before": before, "after": {"valor_unit": line.valor_unit, "total": line.total}}
    return None


def apply_sinapi_profile_recheck(comp: Composicoes, *, context: dict | None = None, config: dict | None = None) -> Dict[str, Any]:
    """Second-pass profile and re-check for SINAPI-like/PRÓPRIO compositions.

    The goal is not to replace Docling.  Docling/Normalizer provides structural
    hypotheses; this pass learns the document's observed code/description and
    column profile, then applies only conservative repairs that can be justified
    by repeated evidence or arithmetic.
    """
    rules = _recheck_rules(config)
    registry: Dict[str, Dict[str, Any]] = {}
    metrics = {
        "blocks_scanned": 0,
        "rows_scanned": 0,
        "non_sicro_rows": 0,
        "sicro_rows_skipped": 0,
        "description_registry_entries": 0,
        "description_repairs_applied": 0,
        "description_repairs_rejected": 0,
        "math_repairs_applied": 0,
    }
    repairs: List[Dict[str, Any]] = []
    rejected_repairs: List[Dict[str, Any]] = []

    for collection, key, block in _all_blocks(comp):
        metrics["blocks_scanned"] += 1
        for group, idx, line in _all_lines(block):
            metrics["rows_scanned"] += 1
            if _is_sicro(getattr(line, "banco", "")):
                metrics["sicro_rows_skipped"] += 1
                continue
            metrics["non_sicro_rows"] += 1
            _registry_add(registry, line, source=f"{collection}.{key}.{group}{'' if idx is None else '.' + str(idx)}", rules=rules)

    metrics["description_registry_entries"] = len(registry)

    for collection, key, block in _all_blocks(comp):
        block_repairs: List[Dict[str, Any]] = []
        if _is_sicro(getattr(block.principal, "banco", "")):
            continue
        for group, idx, line in _all_lines(block):
            desc_repair = _maybe_repair_line_description(line, registry, rules=rules)
            if desc_repair:
                desc_repair.update({"collection": collection, "block": key, "row_group": group, "row_index": idx})
                if desc_repair.get("decision") == "applied":
                    repairs.append(desc_repair); block_repairs.append(desc_repair)
                    metrics["description_repairs_applied"] += 1
                else:
                    rejected_repairs.append(desc_repair)
                    metrics["description_repairs_rejected"] += 1
            math_repair = _try_math_repair_line(line)
            if math_repair:
                math_repair.update({"collection": collection, "block": key, "row_group": group, "row_index": idx, "codigo": getattr(line, "codigo", ""), "banco": getattr(line, "banco", "")})
                repairs.append(math_repair); block_repairs.append(math_repair)
                metrics["math_repairs_applied"] += 1
        if block_repairs:
            detalhes = dict(getattr(block, "detalhes", {}) or {})
            detalhes.setdefault("sinapi_profile_recheck", {})
            detalhes["sinapi_profile_recheck"].update({"version": VERSION, "repairs": block_repairs, "status": "applied"})
            block.detalhes = detalhes

    column_bands = _structured_table_bands(context or {})
    profile = {
        "version": VERSION,
        "enabled": True,
        "strategy": "docling_column_map_plus_pymupdf_learned_registry",
        "column_bands": column_bands,
        "description_registry_size": len(registry),
        "metrics": metrics,
        "rules": rules,
        "repairs": repairs[:100],
        "rejected_repairs": rejected_repairs[:100],
        "registry_preview": list(registry.values())[:20],
    }
    return profile
