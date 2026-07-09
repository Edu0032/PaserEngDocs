from __future__ import annotations

"""Semantic consistency and review-reduction pass (v61.0.57).

This module does not invent values.  It performs conservative, auditable cleanup
and builds diagnostics that help Lovable decide whether a remaining issue is a
real extraction blocker, a likely human/PDF inconsistency, or only an informational
review.
"""

from typing import Any, Dict, Iterable, List, Tuple
import re

from app.parser.numeric_constraint_solver import parse_ptbr_number, format_ptbr_number

VERSION = "v61.0.75-correction-output-contract-and-review-index"

DESCRIPTION_FIELDS = {"descricao", "especificacao"}
COMPONENT_GROUPS = ("composicoes_auxiliares", "insumos", "materiais", "mao_obra", "equipamentos", "auxiliares")
REQUIRED_BUDGET = ("codigo", "fonte", "especificacao", "und", "quant", "custo_unitario_com_bdi", "custo_parcial")
REQUIRED_PRINCIPAL = ("codigo", "banco", "descricao", "und", "quant", "valor_unit", "total")


def _as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def _clean(v: Any) -> str:
    return " ".join(str(v or "").replace("\u00a0", " ").split())


def _norm_bank(v: Any) -> str:
    s = _clean(v).upper().replace("PRÓPRIO", "PROPRIO").replace("PRÓPRIA", "PROPRIO")
    if s == "SICRO3":
        return "SICRO"
    return s


def code_bank_key(code: Any, bank: Any) -> str:
    code_s = _clean(code).upper().replace(" ", "")
    bank_s = _norm_bank(bank)
    return f"{code_s}|{bank_s}" if code_s and bank_s else ""


def _missing(row: Dict[str, Any], fields: Iterable[str]) -> List[str]:
    return [f for f in fields if row.get(f) in (None, "", [], {})]


def _math_triplet(row: Dict[str, Any]) -> Tuple[str, float | None]:
    q = parse_ptbr_number(row.get("quant"))
    unit = parse_ptbr_number(row.get("valor_unit"))
    total = parse_ptbr_number(row.get("total"))
    if q is None or unit is None or total is None:
        return "missing", None
    expected = round(q * unit, 2)
    delta = round(total - expected, 6)
    return ("ok" if abs(delta) <= 0.05 else "mismatch"), delta


def _math_budget(row: Dict[str, Any]) -> Tuple[str, float | None]:
    q = parse_ptbr_number(row.get("quant"))
    unit = parse_ptbr_number(row.get("custo_unitario_com_bdi"))
    total = parse_ptbr_number(row.get("custo_parcial"))
    if q is None or unit is None or total is None:
        return "missing", None
    expected = round(q * unit, 2)
    delta = round(total - expected, 6)
    return ("ok" if abs(delta) <= 0.05 else "mismatch"), delta


def _iter_budget_items(final_result: Dict[str, Any]):
    def walk(nodes: Any, path: List[Any]):
        for idx, node in enumerate(_as_list(nodes)):
            if not isinstance(node, dict):
                continue
            p = path + [idx]
            if node.get("codigo"):
                yield ["orcamento_sintetico", "itens_raiz"] + p, node
            yield from walk(node.get("filhos"), p + ["filhos"])
    yield from walk(_as_dict(final_result.get("orcamento_sintetico")).get("itens_raiz"), [])


def _iter_comp_blocks(final_result: Dict[str, Any], family: str | None = None, collection: str | None = None):
    comp = _as_dict(final_result.get("composicoes"))
    for fam in ("sinapi_like", "sicro"):
        if family and fam != family:
            continue
        fam_obj = _as_dict(comp.get(fam))
        for coll in ("principais", "auxiliares_globais"):
            if collection and coll != collection:
                continue
            for key, block in _as_dict(fam_obj.get(coll)).items():
                if isinstance(block, dict):
                    yield fam, coll, str(key), block
    if family in (None, "sinapi_like"):
        for coll in ("principais", "auxiliares_globais"):
            if collection and coll != collection:
                continue
            for key, block in _as_dict(comp.get(coll)).items():
                if not isinstance(block, dict):
                    continue
                p = _as_dict(block.get("principal"))
                bank = _clean(p.get("banco") or p.get("fonte") or (str(key).split("|",1)[1] if "|" in str(key) else ""))
                fam = "sicro" if "SICRO" in bank.upper() else "sinapi_like"
                if family and fam != family:
                    continue
                yield fam, coll, str(key), block


def _iter_component_rows(block: Dict[str, Any]):
    for group in COMPONENT_GROUPS:
        for idx, row in enumerate(_as_list(block.get(group))):
            if isinstance(row, dict):
                yield group, idx, row


def _component_sum(block: Dict[str, Any]) -> Tuple[float | None, int, int, List[Dict[str, Any]]]:
    total = 0.0
    used = 0
    missing = 0
    rows: List[Dict[str, Any]] = []
    for group, idx, row in _iter_component_rows(block):
        val = parse_ptbr_number(row.get("total"))
        rec = {
            "group": group,
            "index": idx,
            "codigo": row.get("codigo"),
            "banco": row.get("banco") or row.get("fonte"),
            "descricao": _clean(row.get("descricao") or row.get("especificacao"))[:160],
            "quant": row.get("quant"),
            "valor_unit": row.get("valor_unit"),
            "total": row.get("total"),
            "numeric_total": val,
        }
        rows.append(rec)
        if val is None:
            missing += 1
        else:
            used += 1
            total += val
    return (round(total, 6), used, missing, rows) if used else (None, used, missing, rows)


def _looks_trailing_noise(text: str) -> bool:
    return bool(re.search(r"(?:\s*=>\s*)+$", text or ""))


def _sanitize_description_text(text: str) -> Tuple[str, str | None]:
    original = str(text or "")
    cleaned = re.sub(r"(?:\s*=>\s*)+$", "", original).strip()
    if cleaned != original.strip():
        return cleaned, "removed_trailing_summary_arrow"
    return original, None


def apply_semantic_consistency_pass(final_result: Dict[str, Any] | None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    result = final_result if isinstance(final_result, dict) else {}
    repairs: List[Dict[str, Any]] = []

    def visit(obj: Any, path: List[Any]) -> None:
        if isinstance(obj, dict):
            for key, value in list(obj.items()):
                if key in DESCRIPTION_FIELDS and isinstance(value, str) and _looks_trailing_noise(value):
                    cleaned, reason = _sanitize_description_text(value)
                    if reason and cleaned:
                        obj[key] = cleaned
                        repairs.append({
                            "path": path + [key],
                            "field": key,
                            "previous_value": value,
                            "value": cleaned,
                            "reason": reason,
                            "policy": "remove marcador de resumo/ruído sem alterar conteúdo técnico extraído",
                        })
                else:
                    visit(value, path + [key])
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                visit(item, path + [i])

    for root in ("orcamento_sintetico", "composicoes"):
        if root in result:
            visit(result[root], [root])

    report = {
        "version": VERSION,
        "status": "ok",
        "description_repairs": repairs,
        "summary": {"description_repairs": len(repairs)},
        "human_error_policy": "incoerência matemática ou referência ausente no PDF deve ser auditada; este passo só remove ruído textual seguro e não inventa valores",
    }
    if repairs:
        doc = result.setdefault("documento_correcao", {})
        if isinstance(doc, dict):
            doc["semantic_consistency_pass"] = report
            for r in repairs[:120]:
                doc.setdefault("warnings", []).append({"tipo": "semantic_description_noise_removed", **r})
    result.setdefault("meta", {}).setdefault("performance", {})["semantic_consistency_pass"] = report
    return result, report


def build_component_mismatch_diagnostics(final_result: Dict[str, Any] | None, limit: int = 120) -> Dict[str, Any]:
    result = final_result if isinstance(final_result, dict) else {}
    diagnostics: List[Dict[str, Any]] = []
    ok = mismatch = missing = 0
    for fam, coll, key, block in _iter_comp_blocks(result, "sinapi_like", "principais"):
        p = _as_dict(block.get("principal"))
        p_total = parse_ptbr_number(p.get("total"))
        comp_sum, used, missing_totals, rows = _component_sum(block)
        if comp_sum is None or p_total is None or missing_totals:
            missing += 1
            if len(diagnostics) < limit:
                diagnostics.append({
                    "codigo_banco": key,
                    "item": block.get("item"),
                    "status": "not_validatable_missing_component_or_principal_total",
                    "principal_total": p.get("total"),
                    "component_sum": format_ptbr_number(comp_sum) if comp_sum is not None else None,
                    "component_rows_used": used,
                    "missing_component_totals": missing_totals,
                    "candidate_lines_to_review": [r for r in rows if r.get("numeric_total") is None][:12],
                    "conclusion": "não é possível afirmar erro humano antes de recuperar/conferir totais faltantes dos componentes",
                })
            continue
        delta = round(p_total - comp_sum, 6)
        tol = max(0.05, abs(p_total) * 0.001)
        if abs(delta) <= tol:
            ok += 1
            continue
        mismatch += 1
        # Candidate search: if adding/removing one extracted component would close the sum,
        # surface it as a likely duplicate/omission candidate instead of a vague mismatch.
        candidates: List[Dict[str, Any]] = []
        for r in rows:
            val = r.get("numeric_total")
            if val is None:
                continue
            without = round(comp_sum - val, 6)
            if abs(p_total - without) <= tol:
                candidates.append({**r, "candidate_reason": "remover_ou_nao_somar_esta_linha_fecha_a_composicao"})
            needed = round(p_total - comp_sum, 2)
            if abs(val - needed) <= tol:
                candidates.append({**r, "candidate_reason": "esta_linha_tem_valor_igual_ao_delta_e_pode_estar_duplicada_ou_omitida"})
        diagnostics.append({
            "codigo_banco": key,
            "item": block.get("item"),
            "status": "math_mismatch_possible_extraction_or_pdf_human_error",
            "principal_total": p.get("total"),
            "component_sum": format_ptbr_number(comp_sum),
            "delta": format_ptbr_number(delta),
            "tolerance": format_ptbr_number(tol),
            "component_rows_used": used,
            "missing_component_totals": missing_totals,
            "candidate_lines_to_review": candidates[:12],
            "all_component_count": len(rows),
            "conclusion": "se nenhuma linha candidata justificar o delta e todos os componentes foram extraídos corretamente, tratar como erro humano do PDF/orçamento original",
        })
    return {
        "version": VERSION,
        "status": "ok" if not mismatch else "needs_review",
        "summary": {"ok": ok, "mismatch": mismatch, "not_validatable": missing, "diagnostic_count": len(diagnostics)},
        "diagnostics": diagnostics,
        "policy": "o parser procura linhas candidatas que expliquem a divergência; se não houver candidato e os valores estiverem fiéis ao PDF, a divergência é classificada para revisão humana",
    }


def build_entity_confidence_report(final_result: Dict[str, Any] | None, limit_examples: int = 240) -> Dict[str, Any]:
    result = final_result if isinstance(final_result, dict) else {}
    entities: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {"high": 0, "medium": 0, "review": 0}

    for path, item in _iter_budget_items(result):
        missing = _missing(item, REQUIRED_BUDGET)
        math_status, delta = _math_budget(item)
        high = not missing and math_status == "ok"
        level = "high" if high else ("review" if missing or math_status == "mismatch" else "medium")
        counts[level] += 1
        if len(entities) < limit_examples or level != "high":
            entities.append({
                "entity_type": "budget_item",
                "entity_key": code_bank_key(item.get("codigo"), item.get("fonte") or item.get("banco")),
                "item": item.get("item"),
                "confidence_level": level,
                "confidence": 0.99 if level == "high" else (0.78 if level == "medium" else 0.45),
                "closure_status": "closed_math_ok" if high else "needs_review",
                "reasons": [
                    "campos obrigatórios preenchidos" if not missing else f"campos faltantes: {', '.join(missing)}",
                    "quantidade × custo com BDI = custo parcial" if math_status == "ok" else f"math_status={math_status}",
                ],
                "math_delta": delta,
            })

    component_diag = build_component_mismatch_diagnostics(result, limit=limit_examples)
    diag_by_key = {d.get("codigo_banco"): d for d in _as_list(component_diag.get("diagnostics")) if isinstance(d, dict)}
    for fam, coll, key, block in _iter_comp_blocks(result, "sinapi_like", "principais"):
        p = _as_dict(block.get("principal"))
        missing = _missing(p, REQUIRED_PRINCIPAL)
        triplet, delta = _math_triplet(p)
        diag = diag_by_key.get(key)
        component_status = "ok" if not diag else diag.get("status")
        high = not missing and triplet == "ok" and not diag
        medium = not missing and triplet == "ok" and diag and diag.get("status", "").startswith("not_validatable")
        level = "high" if high else ("medium" if medium else "review")
        counts[level] += 1
        entities.append({
            "entity_type": "composition_principal",
            "entity_key": key,
            "item": block.get("item"),
            "confidence_level": level,
            "confidence": 0.98 if level == "high" else (0.76 if level == "medium" else 0.42),
            "closure_status": "closed_by_component_sum_and_triplet" if high else "needs_review_or_component_diagnostic",
            "reasons": [
                "principal completa" if not missing else f"campos faltantes: {', '.join(missing)}",
                "quant × valor_unit = total" if triplet == "ok" else f"triplet={triplet}",
                "soma de componentes fecha" if not diag else f"component_status={component_status}",
            ],
            "math_delta": delta,
            "component_diagnostic": diag,
        })

    for fam, coll, key, block in _iter_comp_blocks(result, "sicro", None):
        p = _as_dict(block.get("principal"))
        has_item = bool(_clean(block.get("item") or p.get("item")))
        level = "high" if (coll == "principais" and has_item) or (coll == "auxiliares_globais" and not has_item) else "review"
        counts[level] += 1
        entities.append({
            "entity_type": f"sicro_{coll}",
            "entity_key": key,
            "item": block.get("item") or p.get("item"),
            "confidence_level": level,
            "confidence": 0.94 if level == "high" else 0.5,
            "closure_status": "sicro_collection_rule_ok" if level == "high" else "sicro_reference_review",
            "reasons": ["tem item => principal; sem item => auxiliar global", "motor SICRO separado é autoritativo"],
        })

    return {
        "version": VERSION,
        "document_type": "entity_confidence_report",
        "summary": counts,
        "entities": entities[:limit_examples],
        "policy": "confiança por entidade ajuda o Lovable a exibir seguro/aviso/revisão sem transformar diagnóstico em erro falso",
    }
