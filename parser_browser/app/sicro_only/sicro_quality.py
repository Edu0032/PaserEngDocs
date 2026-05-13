from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Tuple

from .sicro_engine import SicroEngine, parse_decimal


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _field_confidence(engine: SicroEngine, section: str, field: str, value: Any, row: Dict[str, Any], row_valid: Dict[str, Any]) -> Dict[str, Any]:
    reasons: List[str] = []
    score = 0.0
    evidence = row.get("_evidence") or {}
    field_evidence = (row.get("_field_evidence") or {}).get(field) if isinstance(row.get("_field_evidence"), dict) else None
    if evidence:
        score += 0.22
        reasons.append("há evidência geométrica/bbox da linha")
    if field_evidence:
        score += 0.13
        reasons.append("há evidência geométrica/bbox específica do campo")
    if field in {"banco"} and engine.is_bank(value):
        score += 0.25
        reasons.append("token pertence ao conjunto oficial SICRO/SICRO2/SICRO3")
    if field in {"codigo", "insumo"} and engine.classify_code(value):
        score += 0.25
        reasons.append(f"token segue padrão de código: {engine.classify_code(value)}")
    if field in {"unidade"} and engine.is_unit(value, section):
        score += 0.20
        reasons.append("unidade curta e válida para a seção")
    if field in {"quantidade", "preco_unitario", "custo_horario", "salario_hora", "custo_unitario", "custo_total"} and parse_decimal(value) is not None:
        score += 0.22
        reasons.append("valor numérico pt-BR parseável")
    if section in {"A", "B"} and field == "preco_unitario":
        score -= 0.40
        reasons.append("A/B não devem possuir preço unitário")
    if section in {"C", "D", "E"} and field == "preco_unitario" and value:
        score += 0.15
        reasons.append("C/D/E exigem preço unitário")
    if row_valid.get("ok", True):
        score += 0.25
        reasons.append("a validação matemática da linha fechou")
        if section == "principal" and field in {"custo_unitario", "custo_total", "quantidade"}:
            score += 0.13
            reasons.append("a fórmula principal quantidade × custo_unitario = custo_total confirmou o campo")
        if section in {"C", "D", "E", "F"} and field in {"preco_unitario", "custo_horario", "quantidade"}:
            score += 0.08
            reasons.append("campo monetário foi confirmado pela fórmula da seção")
    else:
        score -= 0.25
        reasons.append("a validação matemática da linha falhou")
    if row.get("document_consistency") and row["document_consistency"].get("numeric_ok") is True and field in {"custo_unitario", "custo_total", "quantidade", "unidade"}:
        score += 0.10
        reasons.append("referência do orçamento sintético confirmou numericamente")
    if row.get("_recovery"):
        score -= 0.05
        reasons.append("campo participou de uma recuperação automática conservadora")
    return {"score": round(_clamp(score), 3), "reasons": reasons}


def annotate_confidence(result: Dict[str, Any], engine: SicroEngine | None = None) -> Dict[str, Any]:
    """Annotate every principal/row with confidence scores.

    The public values are preserved; confidence metadata lives under
    `_confidence` so integration can strip it from the final JSON if needed.
    """
    engine = engine or SicroEngine()
    out = deepcopy(result)
    totals: List[float] = []
    for comp_key, comp in (out.get("composicoes") or {}).items():
        principal = comp.get("principal") or {}
        pconf: Dict[str, Any] = {}
        pvalid = principal.get("validacao") or {}
        for field in ["codigo", "banco", "unidade", "quantidade", "custo_unitario", "custo_total"]:
            if field in principal:
                conf = _field_confidence(engine, "principal", field, principal.get(field), principal, pvalid)
                pconf[field] = conf
                totals.append(conf["score"])
        if pconf:
            principal["_confidence"] = pconf
        for sec, section in (comp.get("secoes") or {}).items():
            for row in section.get("linhas") or []:
                row_valid = row.get("validacao") or {}
                rconf: Dict[str, Any] = {}
                for field in ["codigo", "insumo", "banco", "unidade", "quantidade", "preco_unitario", "custo_horario", "salario_hora"]:
                    if field in row:
                        conf = _field_confidence(engine, sec, field, row.get(field), row, row_valid)
                        rconf[field] = conf
                        totals.append(conf["score"])
                if rconf:
                    row["_confidence"] = rconf
    avg = round(sum(totals) / len(totals), 3) if totals else 0.0
    out.setdefault("metadata", {})["confidence_avg"] = avg
    out.setdefault("metadata", {})["confidence_min"] = round(min(totals), 3) if totals else 0.0
    return out


def score_extraction_result(result: Dict[str, Any], contract_issues: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Score an extraction candidate for the multi-engine selector."""
    comps = result.get("composicoes") or {}
    issue_count = int(result.get("metadata", {}).get("total_issues", len(result.get("issues") or [])))
    contract_count = len(list(contract_issues))
    row_count = 0
    section_count = 0
    evidence_missing = 0
    math_failures = 0
    for comp in comps.values():
        for sec, section in (comp.get("secoes") or {}).items():
            rows = section.get("linhas") or []
            if rows:
                section_count += 1
            for row in rows:
                row_count += 1
                if not row.get("_evidence"):
                    evidence_missing += 1
                if row.get("validacao") and not row["validacao"].get("ok", True):
                    math_failures += 1
    confidence = float(result.get("metadata", {}).get("confidence_avg", 0.0) or 0.0)
    score = (
        len(comps) * 200
        + row_count * 8
        + section_count * 12
        + confidence * 50
        - issue_count * 300
        - contract_count * 500
        - evidence_missing * 30
        - math_failures * 120
    )
    return {
        "score": round(score, 3),
        "composition_count": len(comps),
        "row_count": row_count,
        "section_count": section_count,
        "math_issues": issue_count,
        "contract_issues": contract_count,
        "evidence_missing": evidence_missing,
        "confidence_avg": confidence,
    }
