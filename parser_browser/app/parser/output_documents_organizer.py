from __future__ import annotations

"""Output documents organizer for Lovable (v61.0.57).

This module separates the four public artifacts produced by the parser:

* ``final_result``: clean domain JSON used by the system.
* ``documento_correcao``: rich human-review/correction/audit document.
* ``documento_evidencias``: proof trail explaining how fields were repaired or
  confirmed.
* ``documento_enriquecimento``: system/base_config enrichment suggestions such
  as new units, bank aliases and code patterns observed in the PDF.

The v61.0.48 correction is important: enrichment is not evidence.  Evidence used
for row closure belongs in ``documento_evidencias`` and correction/audit belongs
in ``documento_correcao``.  ``documento_enriquecimento`` must be safe for Lovable
/Admin review and must not automatically mutate base_config.
"""

from typing import Any, Dict, Iterable, List, Tuple
import json
import re
import unicodedata

VERSION = "v61.0.75-correction-output-contract-and-review-index"

MATH_FIELDS = {
    "quant",
    "valor_unit",
    "total",
    "custo_unitario_sem_bdi",
    "custo_unitario_com_bdi",
    "custo_parcial",
    "custo_total",
}
DESCRIPTION_FIELDS = {"descricao", "especificacao"}
UNIT_FIELDS = {"und", "unidade"}

DEFAULT_PARSER_UNITS = {
    "M", "M2", "M²", "M3", "M³", "UN", "UND", "UNID", "H", "KG", "T", "KM", "MES", "MÊS",
    "DIA", "VB", "CJ", "PAR", "L", "LITRO", "T.KM", "TXKM", "M³XKM", "M3XKM", "HA", "PÇ", "PC", "%"
}

BANK_CANON_HINTS = {
    "SINAPI": "SINAPI",
    "SICRO": "SICRO",
    "SICRO3": "SICRO",
    "PROPRIO": "PROPRIO",
    "PRÓPRIO": "PROPRIO",
    "PRÓPRIA": "PROPRIO",
}

_CODE_PATTERNS = [
    ("codigo_sinapi_numerico", re.compile(r"^\d{5,8}$")),
    ("codigo_sinapi_com_barra", re.compile(r"^\d{4,8}/\d{1,4}$")),
    ("codigo_proprio_com_espaco", re.compile(r"^[A-Z]{2,}\s*-?\s*\d+", re.I)),
    ("codigo_proprio_comp_pontuado", re.compile(r"^[A-Z]+(?:\.[A-Z0-9]+)+\.?\d*$", re.I)),
    ("codigo_sicro_numerico", re.compile(r"^\d{7}$")),
    ("codigo_sicro_antigo_espacado", re.compile(r"^\d\s+[A-Z]\s+\d{2}\s+\d{3}\s+\d{2}$", re.I)),
]


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _clean(v: Any) -> str:
    return " ".join(str(v or "").replace("\u00a0", " ").split())


def _norm(v: Any) -> str:
    text = unicodedata.normalize("NFKD", _clean(v))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.upper()


def _norm_unit(v: Any) -> str:
    text = _clean(v).upper().replace(" ", "")
    return text.replace("²", "2").replace("³", "3")


def _compact_step(step: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "order": step.get("order"),
        "step": step.get("step"),
        "status": step.get("status"),
        "effect_count": step.get("effect_count"),
        "purpose": step.get("purpose"),
    }


def _walk(value: Any, path: Tuple[Any, ...] = ()) -> Iterable[Tuple[Tuple[Any, ...], Any]]:
    yield path, value
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, path + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk(v, path + (i,))


_PUBLIC_DOMAIN_ROOTS = {"orcamento_sintetico", "composicoes"}
_INTERNAL_PATH_MARKERS = {
    "meta", "performance", "documento_correcao", "documento_evidencias",
    "documento_enriquecimento", "analise_orcamentaria", "auditoria_final",
    "validacao", "detalhes", "math_status", "math_triage", "docling_assistance",
    "field_evidence_grades", "_calc", "evidence", "evidencia", "raw_context",
}

def _is_public_domain_path(path: Tuple[Any, ...]) -> bool:
    return bool(path) and str(path[0]) in _PUBLIC_DOMAIN_ROOTS and not any(str(p) in _INTERNAL_PATH_MARKERS for p in path)


def _collect_units(final_result: Dict[str, Any], physical_index: Dict[str, Any]) -> Dict[str, Any]:
    observed: Dict[str, Dict[str, Any]] = {}
    suspicious: Dict[str, Dict[str, Any]] = {}

    def add(unit: Any, *, source: str, path: Any = None, example: Dict[str, Any] | None = None):
        raw = _clean(unit)
        if not raw:
            return
        compact = _norm_unit(raw)
        # Avoid obvious false unit candidates from terms like CM-30, 20X20, DN 100 etc.
        if re.search(r"\d{2,}", compact) or "-" in compact:
            suspicious.setdefault(raw, {"value": raw, "reason": "contains_long_number_or_hyphen", "examples": []})["examples"].append(example or {"source": source, "path": path})
            return
        rec = observed.setdefault(compact, {"value": raw, "normalized": compact, "seen_count": 0, "sources": set(), "examples": []})
        rec["seen_count"] += 1
        rec["sources"].add(source)
        if len(rec["examples"]) < 8:
            rec["examples"].append(example or {"source": source, "path": path})

    for path, value in _walk(final_result):
        if path and _is_public_domain_path(path) and str(path[-1]) in UNIT_FIELDS:
            parent = None
            try:
                obj = final_result
                for p in path[:-1]:
                    obj = obj[p]
                parent = obj if isinstance(obj, dict) else None
            except Exception:
                parent = None
            add(value, source="final_result", path=".".join(map(str, path)), example={
                "source": "final_result",
                "path": ".".join(map(str, path)),
                "codigo": _as_dict(parent).get("codigo"),
                "banco": _as_dict(parent).get("banco") or _as_dict(parent).get("fonte"),
                "item": _as_dict(parent).get("item"),
            })

    for key, bucket in _as_dict(physical_index.get("keys")).items():
        for occ in _as_list(_as_dict(bucket).get("occurrences")):
            fields = _as_dict(occ.get("fields_detected"))
            if fields.get("und"):
                add(fields.get("und"), source="physical_evidence_index", example={
                    "source": "physical_evidence_index",
                    "codigo_banco": key,
                    "page": occ.get("page"),
                    "document_section": occ.get("document_section"),
                    "source_zone": occ.get("source_zone"),
                })

    known = []
    new_candidates = []
    for rec in observed.values():
        rec["sources"] = sorted(rec["sources"])
        if rec["normalized"] in {_norm_unit(u) for u in DEFAULT_PARSER_UNITS}:
            rec["base_config_status"] = "parser_supported_but_review_if_missing_from_user_base_config"
            known.append(rec)
        else:
            rec["base_config_status"] = "new_unit_candidate"
            rec["suggested_action"] = "review_and_add_to_base_config_units_if_valid"
            new_candidates.append(rec)
    return {
        "known_or_parser_supported_units": sorted(known, key=lambda x: (-x["seen_count"], x["normalized"])),
        "new_unit_candidates": sorted(new_candidates, key=lambda x: (-x["seen_count"], x["normalized"])),
        "suspicious_unit_candidates": list(suspicious.values())[:80],
    }


def _collect_banks_and_codes(final_result: Dict[str, Any], physical_index: Dict[str, Any]) -> Dict[str, Any]:
    banks: Dict[str, Dict[str, Any]] = {}
    codes: Dict[str, Dict[str, Any]] = {}

    def add_bank(raw: Any, source: str, example: Dict[str, Any] | None = None):
        text = _clean(raw)
        if not text:
            return
        norm = _norm(text)
        rec = banks.setdefault(norm, {"raw_examples": set(), "normalized": BANK_CANON_HINTS.get(norm, norm), "seen_count": 0, "sources": set(), "examples": []})
        rec["raw_examples"].add(text)
        rec["seen_count"] += 1
        rec["sources"].add(source)
        if len(rec["examples"]) < 8:
            rec["examples"].append(example or {"source": source})

    def classify_code(code: str) -> str:
        for name, rx in _CODE_PATTERNS:
            if rx.fullmatch(_clean(code)):
                return name
        return "codigo_outro_observado"

    def add_code(raw: Any, bank: Any, source: str, example: Dict[str, Any] | None = None):
        text = _clean(raw)
        if not text:
            return
        pat = classify_code(text)
        rec = codes.setdefault(pat, {"pattern_type": pat, "examples": [], "seen_count": 0, "sources": set(), "suggested_action": "review_pattern"})
        rec["seen_count"] += 1
        rec["sources"].add(source)
        if len(rec["examples"]) < 12:
            rec["examples"].append({"codigo": text, "banco": _clean(bank), **(example or {})})

    for path, value in _walk(final_result):
        if not _is_public_domain_path(path) or not isinstance(value, dict):
            continue
        code = value.get("codigo")
        bank = value.get("banco") or value.get("fonte")
        if code:
            add_code(code, bank, "final_result", {"path": ".".join(map(str, path)), "item": value.get("item")})
        if bank:
            add_bank(bank, "final_result", {"path": ".".join(map(str, path)), "codigo": code, "item": value.get("item")})

    for key, bucket in _as_dict(physical_index.get("keys")).items():
        for occ in _as_list(_as_dict(bucket).get("occurrences")):
            code, bank = (key.split("|", 1) + [""])[:2]
            add_code(code, bank, "physical_evidence_index", {"page": occ.get("page"), "document_section": occ.get("document_section")})
            add_bank(bank, "physical_evidence_index", {"page": occ.get("page"), "codigo": code, "document_section": occ.get("document_section")})

    bank_aliases = []
    for raw_norm, rec in banks.items():
        bank_aliases.append({
            "raw_examples": sorted(rec["raw_examples"]),
            "normalized": rec["normalized"],
            "seen_count": rec["seen_count"],
            "sources": sorted(rec["sources"]),
            "confidence": 0.99 if rec["normalized"] in {"SINAPI", "SICRO", "PROPRIO"} else 0.75,
            "suggested_action": "review_and_add_alias_if_missing_from_base_config",
            "examples": rec["examples"],
        })
    code_patterns = []
    for rec in codes.values():
        rec = dict(rec)
        rec["sources"] = sorted(rec["sources"])
        code_patterns.append(rec)
    return {
        "bank_aliases_detected": sorted(bank_aliases, key=lambda x: (-x["seen_count"], x["normalized"])),
        "code_patterns_detected": sorted(code_patterns, key=lambda x: (-x["seen_count"], x["pattern_type"])),
    }


def _math_summary(closure_report: Dict[str, Any]) -> Dict[str, Any]:
    rows = _as_list(closure_report.get("rows"))
    checked = ok = mismatch = missing = 0
    examples: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        math_status = _as_dict(row.get("math_status"))
        status = math_status.get("status")
        if not status or status == "not_applicable":
            continue
        checked += 1
        if math_status.get("ok") is True:
            ok += 1
        elif status == "missing_values":
            missing += 1
        else:
            mismatch += 1
        if len(examples) < 80 and math_status.get("ok") is not True:
            examples.append({
                "row_id": row.get("row_id"),
                "codigo": row.get("codigo"),
                "banco": row.get("banco"),
                "family": row.get("family"),
                "math_status": math_status,
                "missing_fields": row.get("missing_fields") or [],
            })
    return {"checked": checked, "ok": ok, "missing_values": missing, "mismatch": mismatch, "problem_examples": examples}


def _classify_unresolved(row: Dict[str, Any]) -> Dict[str, Any]:
    missing = [str(f) for f in _as_list(row.get("missing_fields"))]
    math_status = _as_dict(row.get("math_status"))
    categories: List[str] = []
    if missing:
        categories.append("campo_vazio")
    if any(f in MATH_FIELDS for f in missing):
        categories.append("campo_matematico_vazio")
    if math_status and math_status.get("ok") is not True and math_status.get("status") not in {None, "not_applicable"}:
        categories.append("matematica_nao_fecha" if math_status.get("status") != "missing_values" else "matematica_incompleta")
    if any(f in DESCRIPTION_FIELDS for f in missing):
        categories.append("descricao_ausente_ou_truncada")
    if any(f in UNIT_FIELDS for f in missing):
        categories.append("unidade_ausente")
    if not categories:
        categories.append("evidencia_insuficiente")
    action = "revisar linha e evidências associadas"
    if "campo_matematico_vazio" in categories or "matematica_nao_fecha" in categories:
        action = "procurar valores matemáticos na linha física, arredores, composição relacionada e orçamento; validar por fórmula antes de aplicar"
    elif "unidade_ausente" in categories:
        action = "verificar unidade na linha, composição/orçamento correlato e documento_enriquecimento.unit_candidates"
    elif "descricao_ausente_ou_truncada" in categories:
        action = "verificar continuação de descrição e se houve contaminação por cabeçalho/linha vizinha"
    return {
        "row_id": row.get("row_id"),
        "codigo": row.get("codigo"),
        "banco": row.get("banco"),
        "item": row.get("item"),
        "family": row.get("family"),
        "closure_status": row.get("closure_status") or row.get("row_status") or row.get("status"),
        "missing_fields": missing,
        "math_status": math_status,
        "categories": categories,
        "suggested_action": action,
        "human_error_note": "pode ser falha do PDF/orçamento original, ausência de composição auxiliar/global ou erro de extração; confirmar com evidências antes de corrigir",
    }


def _dedupe_dicts(items: Iterable[Dict[str, Any]], keys: Tuple[str, ...]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        sig = tuple(_clean(item.get(k)) for k in keys)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(item)
    return out


def _build_evidence_document(final_result: Dict[str, Any], closure_report: Dict[str, Any], pipeline: Dict[str, Any]) -> Dict[str, Any]:
    physical = _as_dict(closure_report.get("physical_evidence_index")) or _as_dict(_as_dict(_as_dict(final_result.get("meta")).get("performance")).get("physical_evidence_index"))
    document_idx = _as_dict(closure_report.get("document_evidence_index"))
    cascade = _as_dict(closure_report.get("local_line_cascade_repair"))
    puzzle = _as_dict(closure_report.get("budget_puzzle_resolver"))
    chain = _as_dict(_as_dict(puzzle.get("budget_reconstruction_graph")).get("summary"))
    repairs = _as_list(closure_report.get("repairs"))
    comp_cascade = _as_dict(closure_report.get("composition_principal_cascade_repair"))
    evidence_repairs = [r for r in repairs if isinstance(r, dict) and r.get("reason") in {
        "local_line_neighborhood_cascade_repair",
        "math_expected_value_found_near_same_codigo_banco",
        "field_consensus_resolution",
        "extracted_evidence_cross_resolution",
        "budget_puzzle_entity_resolution",
    }]
    semantic = _as_dict(_as_dict(_as_dict(final_result.get("meta")).get("performance")).get("semantic_consistency_pass"))
    try:
        from app.parser.semantic_consistency import build_component_mismatch_diagnostics
        component_diag = build_component_mismatch_diagnostics(final_result)
    except Exception as _diag_exc:
        component_diag = {"status": "error", "error": str(_diag_exc)}
    try:
        from app.parser.extraction_coverage import build_extraction_coverage_report
        coverage_report = build_extraction_coverage_report(final_result, closure_report)
    except Exception as _cov_exc:
        coverage_report = {"status": "error", "error": str(_cov_exc), "version": VERSION}
    return {
        "version": VERSION,
        "document_type": "documento_evidencias",
        "purpose": "provar como o parser confirmou, corrigiu ou rejeitou valores do JSON final; não é base_config e não deve ser usado para enriquecer regras globais",
        "source_of_truth_policy": {
            "primary": ["orcamento_sintetico", "composicoes_analiticas", "physical_pdf_evidence", "validacao_matematica"],
            "optional_auxiliary_sections": ["memoria_calculo", "curva_abc", "cronograma", "bdi", "textos_brutos"],
            "rule": "seções auxiliares ajudam como evidência, mas não são obrigatórias e não sobrescrevem campos financeiros sem validação matemática e evidência primária",
        },
        "pipeline_execution_order": [_compact_step(s) for s in _as_list(pipeline.get("execution_order"))],
        "evidence_indexes": {
            "document_evidence_index": {k: document_idx.get(k) for k in ("status", "key_count", "occurrence_count", "evidence_value_count", "mode")},
            "physical_evidence_index": {k: physical.get(k) for k in ("status", "key_count", "occurrence_count", "source_zone_counts", "document_section_counts", "evidence_policy_counts")},
        },
        "cascade_repairs": {
            "candidate_count": cascade.get("candidate_count", 0),
            "rejected_count": cascade.get("rejected_count", 0),
            "math_expected_searches": cascade.get("math_expected_searches", 0),
            "applied_repairs": evidence_repairs[:160],
            "rejected_examples": _as_list(cascade.get("rejected"))[:120],
        },
        "composition_principal_cascade_repair": _as_dict(closure_report.get("composition_principal_cascade_repair")),
        "semantic_consistency_pass": semantic,
        "component_mismatch_diagnostics": component_diag,
        "extraction_coverage_report": coverage_report,
        "math_field_summary": _math_summary(closure_report),
        "chain_summary": {
            "chains": chain.get("chains"),
            "missing_global_auxiliaries": chain.get("missing_global_auxiliaries"),
            "composition_cost_mismatches": _as_dict(_as_dict(puzzle.get("composition_cost_reconciliation")).get("summary")).get("mismatches"),
            "budget_hierarchy_mismatches": _as_dict(_as_dict(puzzle.get("budget_hierarchy_reconciliation")).get("summary")).get("mismatches"),
        },
    }



def _confidence_group_enrichment(units: Dict[str, Any], bank_code: Dict[str, Any]) -> Dict[str, Any]:
    high_units = []
    review_units = []
    for u in _as_list(units.get("new_unit_candidates")):
        if not isinstance(u, dict):
            continue
        rec = {**u, "confidence_level": "alta_confiança" if int(u.get("seen_count") or 0) >= 2 else "precisa_revisao"}
        (high_units if rec["confidence_level"] == "alta_confiança" else review_units).append(rec)
    aliases_high = []
    aliases_review = []
    for a in _as_list(bank_code.get("bank_aliases_detected")):
        if not isinstance(a, dict):
            continue
        conf = float(a.get("confidence") or 0)
        rec = {**a, "confidence_level": "alta_confiança" if conf >= 0.95 else "precisa_revisao"}
        (aliases_high if rec["confidence_level"] == "alta_confiança" else aliases_review).append(rec)
    return {
        "unidades": {
            "alta_confianca": high_units,
            "para_revisao": review_units,
            "rejeitadas_como_ruido": _as_list(units.get("suspicious_unit_candidates")),
        },
        "aliases_banco": {
            "alta_confianca": aliases_high,
            "para_revisao": aliases_review,
        },
        "padroes_codigo": {
            "para_revisao": _as_list(bank_code.get("code_patterns_detected")),
        },
        "policy": "sugestões de alta confiança ainda dependem de aprovação do admin/usuário antes de entrar no base_config",
    }

def _build_enrichment_document(final_result: Dict[str, Any], closure_report: Dict[str, Any]) -> Dict[str, Any]:
    physical = _as_dict(closure_report.get("physical_evidence_index")) or _as_dict(_as_dict(_as_dict(final_result.get("meta")).get("performance")).get("physical_evidence_index"))
    units = _collect_units(final_result, physical)
    bank_code = _collect_banks_and_codes(final_result, physical)
    page_sections = _as_list(physical.get("page_sections"))
    section_titles = []
    for rec in page_sections:
        if not isinstance(rec, dict):
            continue
        hint = _clean(rec.get("raw_title_hint"))
        if hint:
            section_titles.append({"page": rec.get("page"), "section": rec.get("section"), "title_hint": hint})
    return {
        "version": VERSION,
        "document_type": "documento_enriquecimento",
        "purpose": "sugerir ao Lovable/Admin novas informações gerais observadas no PDF para enriquecer base_config ou cadastros; não é documento de correção e não deve aplicar mudanças automaticamente",
        "approval_policy": {
            "auto_apply_to_base_config": False,
            "requires_admin_review": True,
            "safe_usage": "mostrar sugestões de unidades, aliases de banco/fonte, padrões de código e templates observados para aprovação humana",
        },
        "unit_candidates": units,
        **bank_code,
        "sugestoes_por_confianca": _confidence_group_enrichment(units, bank_code),
        "section_templates_detected": {
            "document_section_counts": physical.get("document_section_counts") or {},
            "title_hints": _dedupe_dicts(section_titles, ("section", "title_hint"))[:80],
            "note": "seções auxiliares são opcionais; estes títulos ajudam a reconhecer layouts futuros, mas não devem virar hardcode obrigatório",
        },
        "noise_or_false_positive_guards": {
            "unit_false_positive_examples": units.get("suspicious_unit_candidates", [])[:40],
            "rule": "candidatos suspeitos como unidades dentro de códigos/descritivos devem ser revisados, não adicionados automaticamente",
        },
    }



def _targeted_recovery_human_summary(doc: Dict[str, Any]) -> Dict[str, Any]:
    tr = _as_dict(doc.get("targeted_recovery"))
    unresolved = _as_list(tr.get("unresolved"))
    patches = _as_list(tr.get("patches"))
    ignored_reasons = {"no_op_same_value", "same_value", "target_line_not_found_after_current_ok"}
    actionable = []
    ignored = 0
    for item in unresolved:
        if not isinstance(item, dict):
            continue
        reason = _clean(item.get("reason"))
        issue = _clean(item.get("issue"))
        current = _clean(item.get("current_value"))
        candidate = _clean(item.get("candidate_value"))
        # no_op_same_value is useful as developer diagnostics, but it should not
        # become a Lovable/user-facing pendency.
        if reason in ignored_reasons or (candidate and current and _norm(candidate) == _norm(current)):
            ignored += 1
            continue
        # v53: reduce noisy Lovable reviews.  If recovery did not find a better
        # physical line and the current description is already informative, keep
        # it out of the human queue.  Trailing => pollution is handled by the
        # semantic consistency pass, so it should not remain as a manual error.
        if item.get("field") in {"descricao", "especificacao"}:
            issue_l = issue.lower()
            if "pollution_term:=>" in issue_l:
                ignored += 1
                continue
            if not candidate and reason == "target_line_not_found" and len(current) >= 45 and "polluted" not in issue_l:
                ignored += 1
                continue
        if "low_confidence" in reason and current and not ("missing" in issue.lower() or "trunc" in issue.lower()):
            ignored += 1
            continue
        severity = "aviso"
        if item.get("field") in MATH_FIELDS or "missing" in issue.lower():
            severity = "revisao"
        if "polluted" in issue.lower() and candidate:
            severity = "revisao"
        actionable.append({
            "target_id": item.get("target_id"),
            "field": item.get("field"),
            "issue": item.get("issue"),
            "reason": reason,
            "codigo": item.get("codigo"),
            "banco": item.get("banco"),
            "page": item.get("page"),
            "current_value": current[:180],
            "candidate_value": candidate[:180],
            "severity": severity,
            "impacto": {
                "bloqueia_json": False,
                "afeta_matematica": item.get("field") in MATH_FIELDS,
                "afeta_campo_publico": True,
            },
            "suggested_action": "revisar se o campo estiver realmente truncado/poluído; se os campos matemáticos e a cadeia fecham, tratar como aviso visual",
        })
    return {
        "attempted": bool(tr.get("attempted")),
        "target_count": tr.get("target_count"),
        "patch_count": len(patches),
        "actionable_unresolved_count": len(actionable),
        "diagnostic_unresolved_ignored_count": ignored,
        "actionable_unresolved_examples": actionable[:80],
        "policy": "no_op_same_value e diagnósticos sem ganho real não entram como pendência humana",
    }


def _build_reference_review_items(final_result: Dict[str, Any], closure_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    # Budget reconstruction warnings: item in budget without analytic composition
    # is not necessarily parser failure; it can be material/direct item or human
    # omission.  Lovable should see it as organized review.
    doc = _as_dict(final_result.get("documento_correcao"))
    for w in _as_list(doc.get("warnings")):
        if not isinstance(w, dict):
            continue
        tipo = _clean(w.get("tipo") or w.get("code"))
        if tipo in {"item_sem_composicao_analitica", "composition_without_budget_reference", "sicro_sem_referencia_no_sintetico"} or "sem_referencia" in tipo:
            items.append({
                "type": "referencia_orcamento_composicao",
                "severity": "aviso",
                "codigo": w.get("codigo"),
                "banco": w.get("banco") or w.get("fonte"),
                "item": w.get("item"),
                "source": tipo,
                "message": w.get("mensagem") or w.get("message") or "Referência entre orçamento sintético e composição deve ser revisada.",
                "impacto": {"bloqueia_json": False, "afeta_matematica": False, "afeta_campo_publico": False},
                "suggested_action": "Lovable deve confirmar se é lançamento direto, composição ausente no anexo ou erro humano de referência; não bloquear exportação quando a linha do orçamento está completa e matemática fecha.",
            })
    puzzle = _as_dict(closure_report.get("budget_puzzle_resolver"))
    hierarchy = _as_dict(puzzle.get("budget_hierarchy_reconciliation"))
    hierarchy_mismatches = _as_list(hierarchy.get("mismatches"))
    if not hierarchy_mismatches and int(_as_dict(hierarchy.get("summary")).get("mismatch") or 0):
        raw_samples = _as_list(hierarchy.get("sample_rows"))
        bad_samples = [r for r in raw_samples if isinstance(r, dict) and str(r.get("status") or "").lower() not in {"ok"}][:8]
        hierarchy_mismatches = [{"item": None, "summary": hierarchy.get("summary"), "sample_rows": bad_samples}]
    for m in hierarchy_mismatches:
        if isinstance(m, dict):
            items.append({
                "type": "budget_hierarchy_mismatch",
                "severity": "review",
                "item": m.get("item"),
                "message": "Subtotal/meta não fecha pela soma dos filhos ou foi extraído em nível errado.",
                "evidence": {"parent_total": m.get("parent_total"), "child_sum": m.get("child_sum"), "delta": m.get("delta"), "summary": m.get("summary"), "sample_rows": m.get("sample_rows")},
                "suggested_action": "Lovable deve conferir se o total pertence ao nível correto, se há item filho ausente ou se o PDF contém erro humano.",
            })
    conflict_report = _as_dict(puzzle.get("entity_chain_conflict_resolver"))
    for c in _as_list(conflict_report.get("conflicts")):
        if isinstance(c, dict) and c.get("severity") in {"strong", "error"}:
            items.append({
                "type": "entity_chain_conflict",
                "severity": "review",
                "codigo_banco": c.get("key"),
                "field": c.get("field"),
                "message": c.get("reason"),
                "evidence": {"budget_value": c.get("budget_value"), "composition_value": c.get("composition_value")},
                "suggested_action": "conferir divergência entre orçamento sintético e composição analítica.",
            })
    comp_cascade = _as_dict(closure_report.get("composition_principal_cascade_repair"))
    for b in _as_list(comp_cascade.get("blocked")):
        if isinstance(b, dict):
            items.append({
                "type": "composition_cascade_blocked",
                "severity": "review",
                "codigo": b.get("codigo"),
                "banco": b.get("banco"),
                "item": b.get("item"),
                "message": b.get("reason"),
                "evidence": {"component_sum": b.get("component_sum"), "budget_custo_unitario_sem_bdi": b.get("budget_custo_unitario_sem_bdi")},
                "suggested_action": "conferir soma dos componentes e valor sem BDI do orçamento; não copiar quantidade entre contextos.",
            })
    return _dedupe_dicts(items, ("type", "codigo", "banco", "item", "message"))[:160]


def _queue_severity(item: Dict[str, Any]) -> str:
    raw = _clean(item.get("severity")).lower()
    if raw in {"critical", "blocker", "bloqueante", "error"}:
        return "bloqueante"
    if raw in {"warning", "warn", "aviso"}:
        return "aviso"
    cats = {str(c) for c in _as_list(item.get("categories"))}
    if "matematica_nao_fecha" in cats or "campo_matematico_vazio" in cats:
        return "bloqueante"
    if "campo_vazio" in cats:
        return "revisao"
    if str(item.get("type") or "").startswith("auxiliar"):
        return "aviso"
    return "revisao"


def _organize_human_queue(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    buckets = {"bloqueantes": [], "revisoes_recomendadas": [], "avisos": []}
    seen = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        sev = _queue_severity(item)
        item["severity"] = sev
        sig = json.dumps({k: item.get(k) for k in ("row_id", "type", "codigo", "banco", "item", "field", "message", "reason")}, ensure_ascii=False, sort_keys=True, default=str)
        if sig in seen:
            continue
        seen.add(sig)
        if sev == "bloqueante":
            buckets["bloqueantes"].append(item)
        elif sev == "aviso":
            buckets["avisos"].append(item)
        else:
            buckets["revisoes_recomendadas"].append(item)
    queue = buckets["bloqueantes"] + buckets["revisoes_recomendadas"] + buckets["avisos"]
    return {**buckets, "queue": queue, "summary": {"bloqueantes": len(buckets["bloqueantes"]), "revisoes_recomendadas": len(buckets["revisoes_recomendadas"]), "avisos": len(buckets["avisos"]), "total": len(queue)}}


def _build_lovable_decision_panel(final_result: Dict[str, Any], evidence_doc: Dict[str, Any], human_buckets: Dict[str, Any], accuracy_report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    acc = _as_dict(accuracy_report)
    acc_summary = _as_dict(acc.get("summary"))
    coverage = _as_dict(evidence_doc.get("extraction_coverage_report"))
    qgate = _as_dict(_as_dict(final_result.get("auditoria_final")).get("quality_gate"))
    math_summary = _as_dict(evidence_doc.get("math_field_summary"))
    review_summary = _as_dict(human_buckets.get("summary"))
    blocking = int(review_summary.get("bloqueantes") or 0)
    status = "ok" if not blocking and (qgate.get("ok") is not False) else "needs_review"
    status_uso = "utilizavel" if status == "ok" or blocking == 0 else "precisa_revisao"
    return {
        "version": VERSION,
        "schema_version": "outputs.v1",
        "status": status,
        "status_uso": status_uso,
        "qualidade_final": {
            "quality_gate_ok": qgate.get("ok"),
            "bloqueantes": blocking,
            "revisoes_recomendadas": review_summary.get("revisoes_recomendadas", 0),
            "avisos": review_summary.get("avisos", 0),
            "math_checked": math_summary.get("checked"),
            "math_ok": math_summary.get("ok"),
            "math_missing_values": math_summary.get("missing_values"),
            "math_mismatch": math_summary.get("mismatch"),
        },
        "orcamento": {
            "math_ok_rate": acc_summary.get("budget_math_ok_rate"),
            "required_field_rate": acc_summary.get("budget_required_field_rate"),
            "coverage_rate": _as_dict(coverage.get("budget")).get("coverage_rate"),
        },
        "composicoes": {
            "required_field_rate": acc_summary.get("composition_principal_required_field_rate"),
            "triplet_ok_rate": acc_summary.get("composition_principal_triplet_ok_rate"),
            "component_sum_ok_rate": acc_summary.get("composition_component_sum_ok_rate"),
            "coverage_rate": _as_dict(coverage.get("sinapi_like_compositions")).get("coverage_rate"),
        },
        "sicro": {
            "budget_sicro_items": _as_dict(coverage.get("sicro")).get("budget_sicro_items"),
            "referenced_by_budget": _as_dict(coverage.get("sicro")).get("referenced_by_budget"),
            "reviews": len(_as_list(_as_dict(coverage.get("sicro")).get("reviews"))),
            "status": _as_dict(coverage.get("sicro")).get("status"),
        },
        "leitura_para_lovable": {
            "usar_final_result": status_uso == "utilizavel",
            "mostrar_fila_revisao": bool(review_summary.get("total") or review_summary.get("revisoes_recomendadas") or review_summary.get("avisos")),
            "prioridade_ui": "bloqueantes_primeiro_depois_revisoes_e_avisos",
            "baixar_outputs": ["final_result", "correction_document", "evidence_document", "enrichment_document", "analytics_document"],
            "mensagem": "Resultado utilizável; revisar avisos/revisões não bloqueantes" if status_uso == "utilizavel" else "Resultado precisa revisão antes de confirmação final",
        },
        "accuracy_report_summary": acc_summary,
    }


def _enrich_correction_document(final_result: Dict[str, Any], closure_report: Dict[str, Any], evidence_doc: Dict[str, Any]) -> Dict[str, Any]:
    doc = final_result.setdefault("documento_correcao", {})
    if not isinstance(doc, dict):
        final_result["documento_correcao"] = doc = {}
    rows = [r for r in _as_list(closure_report.get("rows")) if isinstance(r, dict)]
    unresolved_rows = [r for r in rows if str(r.get("closure_status") or r.get("row_status") or r.get("status") or "").lower() in {"unresolved", "needs_review"} or r.get("missing_fields")]
    review_queue = [_classify_unresolved(r) for r in unresolved_rows]
    math_summary = evidence_doc.get("math_field_summary") or _math_summary(closure_report)
    repairs = _as_list(closure_report.get("repairs"))
    comp_cascade = _as_dict(closure_report.get("composition_principal_cascade_repair"))
    rejected = []
    cascade = _as_dict(closure_report.get("local_line_cascade_repair"))
    rejected.extend(_as_list(cascade.get("rejected")))
    rejected.extend(_as_list(closure_report.get("rejected_candidates")))
    targeted_summary = _targeted_recovery_human_summary(doc)
    reference_review_items = _build_reference_review_items(final_result, closure_report)
    comp_diag_items = []
    for d in _as_list(_as_dict(evidence_doc.get("component_mismatch_diagnostics")).get("diagnostics")):
        if not isinstance(d, dict):
            continue
        status = str(d.get("status") or "")
        sev = "revisao" if "mismatch" in status else "aviso"
        comp_diag_items.append({
            "type": "composition_component_sum_diagnostic",
            "severity": sev,
            "codigo_banco": d.get("codigo_banco"),
            "item": d.get("item"),
            "message": d.get("conclusion"),
            "evidence": {k: d.get(k) for k in ("status", "principal_total", "component_sum", "delta", "candidate_lines_to_review", "missing_component_totals")},
            "impacto": {"bloqueia_json": sev == "revisao", "afeta_matematica": True, "afeta_campo_publico": False},
            "suggested_action": "conferir linhas candidatas; se todos os valores foram extraídos fielmente e a soma continua divergente, classificar como erro humano do PDF",
        })
    coverage_items = []
    coverage = _as_dict(evidence_doc.get("extraction_coverage_report"))
    for u in _as_list(coverage.get("unmapped_physical_candidates")):
        if not isinstance(u, dict):
            continue
        reason = _clean(u.get("reason"))
        family = _clean(u.get("family"))
        # Raw auxiliary context is useful for evidence but too noisy as a review item.
        if family == "raw_auxiliary_context":
            continue
        severity = "revisao" if family in {"budget", "composition", "sicro"} else "aviso"
        coverage_items.append({
            "type": "linha_fisica_nao_mapeada",
            "severity": severity,
            "codigo_banco": u.get("codigo_banco"),
            "page": u.get("page"),
            "document_section": u.get("document_section"),
            "message": "Linha física candidata encontrada pelo índice de cobertura não foi claramente mapeada no JSON final.",
            "evidence": {"raw_line_text": u.get("raw_line_text"), "fields_detected": u.get("fields_detected"), "reason": reason},
            "suggested_action": "Conferir se é ruído de cabeçalho/rodapé, linha auxiliar fora do escopo ou falha de extração. Não alterar automaticamente sem evidência de pertencimento.",
        })
    for r in _as_list(_as_dict(coverage.get("sicro")).get("reviews")):
        if isinstance(r, dict):
            coverage_items.append({
                "type": r.get("review_type") or "sicro_coverage_review",
                "severity": r.get("severity") or "aviso",
                "codigo_banco": r.get("codigo_banco"),
                "codigo": r.get("codigo"),
                "banco": r.get("banco"),
                "item": r.get("item"),
                "message": "Auditoria de cobertura SICRO/referência ao orçamento.",
                "impacto": {"bloqueia_json": False, "afeta_matematica": False, "afeta_campo_publico": False},
                "suggested_action": r.get("action") or "Lovable deve revisar referência SICRO sem reclassificar automaticamente.",
            })

    raw_human_queue = review_queue[:200] + reference_review_items[:120] + comp_diag_items[:120] + coverage_items[:160] + targeted_summary.get("actionable_unresolved_examples", [])[:80]
    human_buckets = _organize_human_queue(raw_human_queue)
    human_queue = human_buckets["queue"]
    doc["auditoria_humana"] = {
        "version": VERSION,
        "purpose": "orientar correção humana quando houver erro do PDF, campo ausente, conflito de fonte, matemática divergente ou evidência insuficiente",
        "summary": {
            "rows_evaluated": len(rows),
            "review_queue_count": len(human_queue),
            "bloqueantes": human_buckets["summary"].get("bloqueantes", 0),
            "revisoes_recomendadas": human_buckets["summary"].get("revisoes_recomendadas", 0),
            "avisos": human_buckets["summary"].get("avisos", 0),
            "strict_unresolved_rows": len(review_queue),
            "reference_review_items": len(reference_review_items),
            "coverage_review_items": len(coverage_items),
            "targeted_recovery_actionable_unresolved": targeted_summary.get("actionable_unresolved_count"),
            "targeted_recovery_diagnostic_ignored": targeted_summary.get("diagnostic_unresolved_ignored_count"),
            "math_checked": math_summary.get("checked"),
            "math_ok": math_summary.get("ok"),
            "math_missing_values": math_summary.get("missing_values"),
            "math_mismatch": math_summary.get("mismatch"),
            "applied_repairs": len(repairs),
            "composition_principal_cascade_repairs": _as_dict(comp_cascade.get("summary")).get("repairs", 0),
            "composition_principal_cascade_fields_repaired": _as_dict(comp_cascade.get("summary")).get("fields_repaired", 0),
            "rejected_candidates": len(rejected),
        },
        "queue": human_queue[:300],
        "bloqueantes": human_buckets["bloqueantes"][:120],
        "revisoes_recomendadas": human_buckets["revisoes_recomendadas"][:160],
        "avisos": human_buckets["avisos"][:160],
        "categories_count": _category_counts(review_queue),
        "reference_review_items": reference_review_items,
        "targeted_recovery_human_summary": targeted_summary,
        "human_error_policy": {
            "principle": "erros humanos no PDF devem virar pendências ricas e acionáveis, não crash e não correção inventada",
            "examples": [
                "auxiliar referenciada sem auxiliar global",
                "quantidade incompatível entre memória de cálculo e orçamento",
                "subtotal de meta que não fecha pela soma dos filhos",
                "preço/total ausente na linha física",
                "descrição truncada por quebra visual do PDF",
            ],
        },
    }
    resumo = doc.setdefault("resumo", {})
    if isinstance(resumo, dict):
        blocking_errors = 0
        if int(math_summary.get("mismatch") or 0) or int(math_summary.get("missing_values") or 0):
            blocking_errors += 1
        blocking_errors += int(human_buckets["summary"].get("bloqueantes") or 0)
        # Human-review-only items are not blocking extraction errors. They are
        # surfaced separately so Lovable can guide the user without making a good
        # extraction look failed.
        resumo["total_registros_com_erro"] = blocking_errors
        resumo["total_pendencias_revisao"] = len(human_queue)
        resumo["total_pendencias_bloqueantes"] = int(human_buckets["summary"].get("bloqueantes") or 0)
        resumo["total_revisoes_recomendadas"] = int(human_buckets["summary"].get("revisoes_recomendadas") or 0)
        resumo["total_avisos"] = int(human_buckets["summary"].get("avisos") or 0)
        resumo["total_diagnosticos_targeted_recovery_ignorados"] = int(targeted_summary.get("diagnostic_unresolved_ignored_count") or 0)

    doc["evidencias_resumo"] = {
        "documento_evidencias_path": "documento_evidencias",
        "physical_index": evidence_doc.get("evidence_indexes", {}).get("physical_evidence_index", {}),
        "cascade_repairs": {k: evidence_doc.get("cascade_repairs", {}).get(k) for k in ("candidate_count", "rejected_count", "math_expected_searches")},
        "composition_principal_cascade_repair": evidence_doc.get("composition_principal_cascade_repair", {}),
        "extraction_coverage_report": {
            "summary": _as_dict(evidence_doc.get("extraction_coverage_report")).get("summary", {}),
            "sicro": _as_dict(evidence_doc.get("extraction_coverage_report")).get("sicro", {}),
        },
    }
    # Keep v45 consolidated buckets but dedupe to avoid Lovable noise.
    doc["reparos_aplicados_consolidados"] = _dedupe_dicts(repairs, ("row_id", "field", "value", "reason"))[:240]
    doc["candidatos_rejeitados_consolidados"] = _dedupe_dicts([x for x in rejected if isinstance(x, dict)], ("row_id", "field", "value", "reason"))[:240]
    doc["manual_consumo_lovable_resumo"] = {
        "version": VERSION,
        "final_result": "JSON principal: orçamento, composições, validação e análises consolidadas",
        "documento_correcao": "pendências, reparos aplicados, candidatos rejeitados, suspeitas de erro humano e evidências suficientes para resolver problemas",
        "documento_evidencias": "provas usadas para confirmar/corrigir campos, incluindo índices, cascata local, matemática e cadeias",
        "documento_enriquecimento": "sugestões de novas unidades, aliases, padrões de código e templates para revisão no admin/base_config",
        "coverage": "analise_orcamentaria.extraction_coverage_report mostra linhas mapeadas/não mapeadas, inclusive SICRO",
    }
    return doc


def _category_counts(queue: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in queue:
        for cat in _as_list(item.get("categories")):
            counts[str(cat)] = counts.get(str(cat), 0) + 1
    return counts


def _normalize_public_version_markers(value: Any) -> None:
    """Keep final outputs from exposing stale monorepo contract versions.

    Some intermediate artifacts arrive from pre-v52 browser stages and keep their
    own `version` fields.  That confused Lovable/users into thinking an older
    pipeline was still active.  Native SICRO engine versions are intentionally
    preserved; only general parser/document-output version fields are normalized.
    """
    old_prefixes = ("v61.0.49-", "v61.0.50-", "v61.0.51-", "v61.0.52-", "v61.0.53-", "v61.0.54-")
    if isinstance(value, dict):
        for k, v in list(value.items()):
            if str(k) in {"sicro_native_version", "native_version"}:
                continue
            if str(k) in {"version", "versao", "contract_version", "metric_version", "bridge_version"} and isinstance(v, str) and v.startswith(old_prefixes):
                value[k] = VERSION
            else:
                _normalize_public_version_markers(v)
    elif isinstance(value, list):
        for item in value:
            _normalize_public_version_markers(item)


def organize_lovable_output_documents(final_result: Dict[str, Any], closure_report: Dict[str, Any]) -> Dict[str, Any]:
    final_result = final_result if isinstance(final_result, dict) else {}
    closure_report = closure_report if isinstance(closure_report, dict) else {}
    try:
        from app.parser.semantic_consistency import apply_semantic_consistency_pass
        final_result, semantic_report = apply_semantic_consistency_pass(final_result)
        final_result.setdefault("meta", {}).setdefault("performance", {})["semantic_consistency_organizer"] = semantic_report
    except Exception as _sem_exc:
        final_result.setdefault("documento_correcao", {}).setdefault("warnings", []).append({"tipo": "semantic_consistency_failed", "message": str(_sem_exc)})
    doc = final_result.setdefault("documento_correcao", {})
    if not isinstance(doc, dict):
        final_result["documento_correcao"] = doc = {}

    pipeline = _as_dict(doc.get("auditoria_consolidada") or closure_report.get("pipeline_consolidation"))
    summary = _as_dict(closure_report.get("summary")) or _as_dict(pipeline.get("summary"))

    evidence_doc = _build_evidence_document(final_result, closure_report, pipeline)
    enrichment_doc = _build_enrichment_document(final_result, closure_report)
    final_result["documento_evidencias"] = evidence_doc
    final_result["documento_enriquecimento"] = enrichment_doc
    _enrich_correction_document(final_result, closure_report, evidence_doc)
    try:
        from app.parser.output_accuracy_report import build_output_accuracy_report
        accuracy_report = build_output_accuracy_report(final_result, closure_report)
    except Exception as exc:
        accuracy_report = {"version": VERSION, "status": "error", "error": {"message": str(exc), "type": exc.__class__.__name__}}
    try:
        from app.parser.output_contract_validator import validate_output_contract
        contract_validation = validate_output_contract(final_result)
    except Exception as exc:
        contract_validation = {"version": VERSION, "ok": False, "issues": [{"code": "contract_validator_failed", "message": str(exc)}]}
    try:
        from app.parser.semantic_consistency import build_entity_confidence_report
        entity_confidence = build_entity_confidence_report(final_result)
    except Exception as exc:
        entity_confidence = {"version": VERSION, "status": "error", "error": {"message": str(exc)}}
    try:
        from app.parser.extraction_coverage import build_extraction_coverage_report, build_base_config_layering_report
        coverage_report = build_extraction_coverage_report(final_result, closure_report)
        base_config_layering = build_base_config_layering_report(final_result)
    except Exception as exc:
        coverage_report = {"version": VERSION, "status": "error", "error": {"message": str(exc), "type": exc.__class__.__name__}}
        base_config_layering = {"version": VERSION, "status": "error", "error": {"message": str(exc), "type": exc.__class__.__name__}}
    # Keep the evidence document in sync with the final coverage report built
    # after correction/auditoria enrichment.
    if isinstance(final_result.get("documento_evidencias"), dict):
        final_result["documento_evidencias"]["extraction_coverage_report"] = coverage_report
    final_result.setdefault("analise_orcamentaria", {})["accuracy_report"] = accuracy_report
    final_result.setdefault("analise_orcamentaria", {})["entity_confidence_report"] = entity_confidence
    final_result.setdefault("analise_orcamentaria", {})["extraction_coverage_report"] = coverage_report
    final_result.setdefault("analise_orcamentaria", {})["base_config_layering"] = base_config_layering
    final_result.setdefault("analise_orcamentaria", {})["output_contract_validation"] = contract_validation
    final_result.setdefault("documento_correcao", {})["painel_lovable"] = _build_lovable_decision_panel(final_result, evidence_doc, _organize_human_queue(_as_list(_as_dict(final_result.get("documento_correcao")).get("auditoria_humana", {}).get("queue"))), accuracy_report)

    analysis = final_result.setdefault("analise_orcamentaria", {})
    if isinstance(analysis, dict):
        analysis["outputs_contract"] = {
            "version": VERSION,
            "final_result_path": "root",
            "correction_document_path": "documento_correcao",
            "evidence_document_path": "documento_evidencias",
            "enrichment_document_path": "documento_enriquecimento",
            "core_sections": {
                "orcamento_sintetico": "itens_raiz com metas/submetas/itens folha",
                "composicoes.sinapi_like": "principais e auxiliares_globais SINAPI-like, com auxiliares/insumos internos nas principais",
                "composicoes.sicro": "principais e auxiliares_globais vindas do motor SICRO autoritativo",
            },
            "document_roles": {
                "final_result": "dados limpos para popular o sistema",
                "documento_correcao": "fila de revisão, problemas, rejeições, erros humanos suspeitos e ações sugeridas",
                "documento_evidencias": "provas e rastreabilidade de decisões/correções",
                "documento_enriquecimento": "sugestões para enriquecer base_config/admin após aprovação",
            },
            "summary": {
                "rows_evaluated": summary.get("total_rows"),
                "closed_100": summary.get("closed_100"),
                "closed_by_strong_consensus": summary.get("closed_by_strong_consensus"),
                "closed_with_warning": summary.get("closed_with_warning"),
                "unresolved": summary.get("unresolved"),
                "accuracy_status": accuracy_report.get("status"),
                "output_contract_ok": contract_validation.get("ok"),
                "entity_confidence_summary": _as_dict(entity_confidence.get("summary")),
                "coverage_summary": _as_dict(coverage_report.get("summary")),
            },
        }
        analysis["core_extraction_accuracy"] = {
            "version": VERSION,
            "focus": "campos_matematicos_e_fechamento_em_cascata_composicoes_para_orcamento",
            "math_field_summary": evidence_doc["math_field_summary"],
            "cascade_repairs": {k: evidence_doc["cascade_repairs"].get(k) for k in ("candidate_count", "rejected_count", "math_expected_searches")},
        }
        _human_summary = _as_dict(_as_dict(final_result.get("documento_correcao")).get("auditoria_humana", {}).get("summary")) if isinstance(_as_dict(final_result.get("documento_correcao")).get("auditoria_humana"), dict) else {}
        analysis["output_quality_summary"] = {
            "has_documento_correcao": isinstance(final_result.get("documento_correcao"), dict),
            "has_documento_evidencias": isinstance(final_result.get("documento_evidencias"), dict),
            "has_documento_enriquecimento": isinstance(final_result.get("documento_enriquecimento"), dict),
            "review_queue_count": _human_summary.get("review_queue_count", 0),
            "bloqueantes": _human_summary.get("bloqueantes", 0),
            "revisoes_recomendadas": _human_summary.get("revisoes_recomendadas", 0),
            "avisos": _human_summary.get("avisos", 0),
            "new_unit_candidate_count": len(_as_list(enrichment_doc.get("unit_candidates", {}).get("new_unit_candidates"))),
            "bank_alias_candidate_count": len(_as_list(enrichment_doc.get("bank_aliases_detected"))),
            "quality_gate_ok": _as_dict(_as_dict(final_result.get("auditoria_final")).get("quality_gate")).get("ok"),
            "accuracy_status": accuracy_report.get("status"),
            "output_contract_ok": contract_validation.get("ok"),
            "entity_confidence_summary": _as_dict(entity_confidence.get("summary")),
            "coverage_summary": _as_dict(coverage_report.get("summary")),
            "sicro_coverage_summary": _as_dict(coverage_report.get("sicro")),
        }
    try:
        from app.parser.output_schema_stability import normalize_output_schema_documents
        normalize_output_schema_documents(final_result)
    except Exception as _schema_exc:
        final_result.setdefault("documento_correcao", {}).setdefault("warnings", []).append({"tipo": "output_schema_stability_failed", "message": str(_schema_exc)})
    _normalize_public_version_markers(final_result)
    return final_result
