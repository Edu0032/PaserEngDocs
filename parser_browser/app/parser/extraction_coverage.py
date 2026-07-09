from __future__ import annotations

"""Extraction coverage and SICRO audit helpers (v61.0.57).

This module answers a different question from the normal validators: not only
"are the extracted rows internally valid?", but "did every likely domain row in
PDF evidence end up represented by the JSON, and how should Lovable interpret
anything that did not?"  It is deliberately conservative: it never mutates the
final result and never reclassifies SICRO.  SICRO collection truth remains:
``tem item => principal`` and ``sem item => auxiliar_global``.
"""

from typing import Any, Dict, Iterable, List, Tuple
import re

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def _clean(v: Any) -> str:
    return " ".join(str(v or "").replace("\u00a0", " ").split())


def _norm_bank(v: Any) -> str:
    s = _clean(v).upper()
    s = s.replace("PRÓPRIO", "PROPRIO").replace("PRÓPRIA", "PROPRIO")
    if s in {"SICRO3", "SICRO 3"}:
        return "SICRO"
    return s


def _norm_code(v: Any) -> str:
    # Matching key is internal only; public JSON keeps the original code.
    return re.sub(r"\s+", "", _clean(v).upper())


def code_bank_key(code: Any, bank: Any) -> str:
    c = _norm_code(code)
    b = _norm_bank(bank)
    return f"{c}|{b}" if c and b else ""



def _loose_key(v: str) -> str:
    if "|" not in str(v):
        return str(v)
    code, bank = str(v).split("|", 1)
    return f"{re.sub(r'[^A-Z0-9]', '', code.upper())}|{_norm_bank(bank)}"

def _has_key(index: Dict[str, List[Dict[str, Any]]], key: str) -> bool:
    if key in index:
        return True
    lk = _loose_key(key)
    return any(_loose_key(k) == lk for k in index.keys())


def _iter_budget_items(final_result: Dict[str, Any]) -> Iterable[Tuple[List[Any], Dict[str, Any]]]:
    def walk(nodes: Any, path: List[Any]):
        for idx, node in enumerate(_as_list(nodes)):
            if not isinstance(node, dict):
                continue
            p = path + [idx]
            if node.get("codigo"):
                yield ["orcamento_sintetico", "itens_raiz"] + p, node
            yield from walk(node.get("filhos"), p + ["filhos"])
    yield from walk(_as_dict(final_result.get("orcamento_sintetico")).get("itens_raiz"), [])


def _iter_comp_blocks(final_result: Dict[str, Any]) -> Iterable[Tuple[str, str, str, Dict[str, Any]]]:
    comp = _as_dict(final_result.get("composicoes"))
    # Canonical split introduced by the browser pipeline.
    seen: set[str] = set()
    for fam in ("sinapi_like", "sicro"):
        fam_obj = _as_dict(comp.get(fam))
        for coll in ("principais", "auxiliares_globais"):
            for key, block in _as_dict(fam_obj.get(coll)).items():
                if isinstance(block, dict):
                    seen.add(f"{fam}:{coll}:{key}")
                    yield fam, coll, str(key), block
    # Legacy aliases are still emitted for Lovable convenience. Avoid duplicating
    # keys already present in the canonical split.
    for coll in ("principais", "auxiliares_globais"):
        for key, block in _as_dict(comp.get(coll)).items():
            if not isinstance(block, dict):
                continue
            p = _as_dict(block.get("principal"))
            bank = p.get("banco") or p.get("fonte") or (str(key).split("|", 1)[1] if "|" in str(key) else "")
            fam = "sicro" if "SICRO" in _norm_bank(bank) else "sinapi_like"
            sig = f"{fam}:{coll}:{key}"
            if sig in seen:
                continue
            seen.add(sig)
            yield fam, coll, str(key), block


_COMPONENT_GROUPS = ("composicoes_auxiliares", "insumos", "materiais", "mao_obra", "equipamentos", "auxiliares")


def _iter_component_rows(block: Dict[str, Any]) -> Iterable[Tuple[str, int, Dict[str, Any]]]:
    for group in _COMPONENT_GROUPS:
        for idx, row in enumerate(_as_list(block.get(group))):
            if isinstance(row, dict):
                yield group, idx, row


def _physical_index(final_result: Dict[str, Any], closure_report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    perf = _as_dict(_as_dict(final_result.get("meta")).get("performance"))
    from_closure = _as_dict(_as_dict(closure_report or {}).get("physical_evidence_index"))
    from_perf = _as_dict(perf.get("physical_evidence_index"))
    # Some closure reports keep only a compact physical-index summary.  Coverage
    # needs the full `keys` map, so prefer the full performance artifact when
    # the compact report has no occurrences.
    if from_closure.get("keys"):
        return from_closure
    if from_perf.get("keys"):
        return from_perf
    return from_closure or from_perf


def _json_indexes(final_result: Dict[str, Any]) -> Dict[str, Any]:
    budget_keys: Dict[str, List[Dict[str, Any]]] = {}
    budget_sicro: Dict[str, List[Dict[str, Any]]] = {}
    for path, row in _iter_budget_items(final_result):
        k = code_bank_key(row.get("codigo"), row.get("fonte") or row.get("banco"))
        if not k:
            continue
        rec = {"item": row.get("item"), "path": ".".join(map(str, path)), "codigo": row.get("codigo"), "banco": row.get("fonte") or row.get("banco")}
        budget_keys.setdefault(k, []).append(rec)
        if "SICRO" in _norm_bank(row.get("fonte") or row.get("banco")):
            budget_sicro.setdefault(k, []).append(rec)

    principal_keys: Dict[str, List[Dict[str, Any]]] = {}
    component_keys: Dict[str, List[Dict[str, Any]]] = {}
    sicro_main: Dict[str, List[Dict[str, Any]]] = {}
    sicro_aux: Dict[str, List[Dict[str, Any]]] = {}
    all_comp_keys: Dict[str, List[Dict[str, Any]]] = {}
    for fam, coll, key, block in _iter_comp_blocks(final_result):
        p = _as_dict(block.get("principal"))
        pk = code_bank_key(p.get("codigo") or (key.split("|",1)[0] if "|" in key else key), p.get("banco") or p.get("fonte") or (key.split("|",1)[1] if "|" in key else ""))
        rec = {"family": fam, "collection": coll, "key": key, "item": block.get("item") or p.get("item"), "codigo": p.get("codigo"), "banco": p.get("banco") or p.get("fonte")}
        if pk:
            all_comp_keys.setdefault(pk, []).append(rec)
            if coll == "principais":
                principal_keys.setdefault(pk, []).append(rec)
            if fam == "sicro" and coll == "principais":
                sicro_main.setdefault(pk, []).append(rec)
            if fam == "sicro" and coll == "auxiliares_globais":
                sicro_aux.setdefault(pk, []).append(rec)
        for group, idx, row in _iter_component_rows(block):
            rk = code_bank_key(row.get("codigo"), row.get("banco") or row.get("fonte"))
            if rk:
                component_keys.setdefault(rk, []).append({"family": fam, "parent_key": key, "group": group, "index": idx, "codigo": row.get("codigo"), "banco": row.get("banco") or row.get("fonte")})
                all_comp_keys.setdefault(rk, []).append({"family": fam, "parent_key": key, "group": group, "index": idx, "codigo": row.get("codigo"), "banco": row.get("banco") or row.get("fonte")})
    return {
        "budget_keys": budget_keys,
        "budget_sicro_keys": budget_sicro,
        "composition_principal_keys": principal_keys,
        "composition_component_keys": component_keys,
        "all_composition_keys": all_comp_keys,
        "sicro_main_keys": sicro_main,
        "sicro_auxiliary_keys": sicro_aux,
    }


def _occurrences_from_physical_index(index: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    for key, bucket in _as_dict(index.get("keys")).items():
        for occ in _as_list(_as_dict(bucket).get("occurrences")):
            if isinstance(occ, dict):
                yield str(key), occ


def build_extraction_coverage_report(final_result: Dict[str, Any] | None, closure_report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    final = final_result if isinstance(final_result, dict) else {}
    coverage: Dict[str, Any] = {"version": VERSION, "document_type": "extraction_coverage_report"}
    idx = _json_indexes(final)
    physical = _physical_index(final, closure_report)

    budget_item_count = sum(len(v) for v in idx["budget_keys"].values())
    comp_principal_count = sum(len(v) for v in idx["composition_principal_keys"].values())
    comp_component_count = sum(len(v) for v in idx["composition_component_keys"].values())

    budget_occ = mapped_budget = 0
    comp_occ = mapped_comp = 0
    raw_occ = 0
    unmapped: List[Dict[str, Any]] = []
    mapped_examples: List[Dict[str, Any]] = []
    for key, occ in _occurrences_from_physical_index(physical):
        section = str(occ.get("document_section") or "unknown")
        source_zone = str(occ.get("source_zone") or "")
        normalized_key = key
        if "|" in normalized_key:
            c, b = normalized_key.split("|", 1)
            normalized_key = code_bank_key(c, b)
        in_budget = _has_key(idx["budget_keys"], normalized_key)
        in_comp = _has_key(idx["all_composition_keys"], normalized_key)
        rec = {
            "codigo_banco": key,
            "normalized_key": normalized_key,
            "page": occ.get("page"),
            "document_section": section,
            "source_zone": source_zone,
            "raw_line_text": _clean(occ.get("line_text") or occ.get("raw_text"))[:260],
            "fields_detected": {k: v for k, v in _as_dict(occ.get("fields_detected")).items() if v not in (None, "")},
        }
        if section == "orcamento_sintetico":
            budget_occ += 1
            if in_budget:
                mapped_budget += 1
                if len(mapped_examples) < 20:
                    mapped_examples.append({**rec, "mapped_to": "budget"})
            else:
                unmapped.append({**rec, "family": "budget", "reason": "physical_budget_candidate_not_found_in_json"})
        elif section in {"composicoes_analiticas", "declared_range_unknown_layout"} or "composition" in source_zone:
            comp_occ += 1
            if in_comp:
                mapped_comp += 1
                if len(mapped_examples) < 20:
                    mapped_examples.append({**rec, "mapped_to": "composition"})
            else:
                unmapped.append({**rec, "family": "composition", "reason": "physical_composition_candidate_not_found_in_json"})
        else:
            raw_occ += 1
            # Raw sections are auxiliary evidence.  They are not automatically
            # extraction failures, but they can help Lovable review unusual rows.
            if not (in_budget or in_comp) and len(unmapped) < 200:
                unmapped.append({**rec, "family": "raw_auxiliary_context", "reason": "raw_occurrence_not_expected_to_map_unless_needed"})

    sicro_budget = idx["budget_sicro_keys"]
    sicro_main = idx["sicro_main_keys"]
    sicro_aux = idx["sicro_auxiliary_keys"]
    sicro_main_with_item = []
    sicro_main_without_reference = []
    for key, recs in sicro_main.items():
        for rec in recs:
            has_item = bool(_clean(rec.get("item")))
            ref = _has_key(sicro_budget, key)
            row = {**rec, "codigo_banco": key, "referenced_by_budget": ref, "has_item": has_item}
            if has_item:
                sicro_main_with_item.append(row)
            if has_item and not ref:
                sicro_main_without_reference.append({**row, "review_type": "sicro_principal_with_item_not_referenced_by_budget", "severity": "aviso", "action": "Lovable deve decidir se é composição extra, erro humano de referência ou anexo complementar; não reclassificar automaticamente."})
    budget_sicro_missing_comp = []
    for key, recs in sicro_budget.items():
        if not _has_key(sicro_main, key):
            for rec in recs:
                budget_sicro_missing_comp.append({**rec, "codigo_banco": key, "review_type": "budget_sicro_item_without_sicro_composition", "severity": "revisao", "action": "procurar composição SICRO correspondente ou confirmar lançamento direto/ausente no anexo"})

    def rate(mapped: int, total: int) -> float | None:
        return round(mapped / total, 6) if total else None

    coverage.update({
        "summary": {
            "budget_json_leaf_items": budget_item_count,
            "composition_principals": comp_principal_count,
            "composition_component_rows": comp_component_count,
            "physical_budget_occurrences": budget_occ,
            "physical_budget_mapped_occurrences": mapped_budget,
            "physical_composition_occurrences": comp_occ,
            "physical_composition_mapped_occurrences": mapped_comp,
            "raw_auxiliary_occurrences": raw_occ,
            "unmapped_candidate_count": len(unmapped),
            "budget_physical_mapping_rate": rate(mapped_budget, budget_occ),
            "composition_physical_mapping_rate": rate(mapped_comp, comp_occ),
        },
        "budget": {
            "json_leaf_items": budget_item_count,
            "physical_candidate_occurrences": budget_occ,
            "mapped_physical_occurrences": mapped_budget,
            "coverage_rate": rate(mapped_budget, budget_occ),
            "status": "ok" if not budget_occ or mapped_budget == budget_occ else "needs_review",
        },
        "sinapi_like_compositions": {
            "json_principals": len([1 for recs in idx["composition_principal_keys"].values() for r in recs if r.get("family") == "sinapi_like"]),
            "json_component_rows": len([1 for recs in idx["composition_component_keys"].values() for r in recs if r.get("family") == "sinapi_like"]),
            "physical_candidate_occurrences": comp_occ,
            "mapped_physical_occurrences": mapped_comp,
            "coverage_rate": rate(mapped_comp, comp_occ),
            "status": "ok" if not comp_occ or mapped_comp >= max(0, comp_occ - 3) else "needs_review",
        },
        "sicro": {
            "budget_sicro_items": sum(len(v) for v in sicro_budget.values()),
            "sicro_main_with_item": len(sicro_main_with_item),
            "sicro_auxiliaries_without_item": sum(len(v) for v in sicro_aux.values()),
            "referenced_by_budget": sum(1 for recs in sicro_main.values() for r in recs if _has_key(sicro_budget, code_bank_key(r.get("codigo"), r.get("banco")))),
            "main_with_item_not_referenced_by_budget": len(sicro_main_without_reference),
            "budget_sicro_items_without_sicro_composition": len(budget_sicro_missing_comp),
            "rule": "tem item próprio => principal; sem item próprio => auxiliar_global; ausência de referência no sintético é revisão Lovable, não reclassificação automática",
            "reviews": (sicro_main_without_reference + budget_sicro_missing_comp)[:160],
            "status": "ok" if not budget_sicro_missing_comp else "ok_with_review",
        },
        "unmapped_physical_candidates": unmapped[:200],
        "mapped_examples": mapped_examples,
        "family_breakdown": {
            "orcamento": {"json_rows": budget_item_count, "physical_candidates": budget_occ, "mapped": mapped_budget, "unmapped": max(0, budget_occ - mapped_budget)},
            "sinapi_like_composicoes": {"json_principals": len([1 for recs in idx["composition_principal_keys"].values() for r in recs if r.get("family") == "sinapi_like"]), "json_component_rows": len([1 for recs in idx["composition_component_keys"].values() for r in recs if r.get("family") == "sinapi_like"]), "physical_candidates": comp_occ, "mapped": mapped_comp, "unmapped": max(0, comp_occ - mapped_comp)},
            "sicro": {"budget_items": sum(len(v) for v in sicro_budget.values()), "main_with_item": len(sicro_main_with_item), "auxiliaries_without_item": sum(len(v) for v in sicro_aux.values()), "reviews": len(sicro_main_without_reference) + len(budget_sicro_missing_comp)},
            "raw_auxiliary_context": {"physical_occurrences": raw_occ, "policy": "evidência auxiliar; não conta como falha de cobertura se não mapear"},
        },
        "ignored_or_non_blocking_policy": {
            "raw_auxiliary_context": "não é erro de extração por padrão",
            "sicro_principal_with_item_not_referenced_by_budget": "não reclassificar; Lovable revisa como possível erro humano/referência ausente",
            "budget_sicro_item_without_sicro_composition": "revisão recomendada; pode indicar anexo ausente ou extração incompleta",
            "headers_footers_and_titles": "devem ser ignorados quando identificados como ruído estrutural",
        },
        "interpretation_policy": {
            "primary_goal": "extrair fielmente o que está no PDF e separar falha de extração de erro humano/documental",
            "unmapped_inside_declared_ranges": "revisar; pode indicar linha perdida, ruído de cabeçalho/rodapé ou layout não classificado",
            "unmapped_outside_ranges": "evidência auxiliar bruta; não é erro por si só",
            "sicro_policy": "não duplicar motor SICRO; usar saída sicro_only para coverage/auditoria",
        },
    })
    return coverage


def build_base_config_layering_report(final_result: Dict[str, Any] | None = None, options: Dict[str, Any] | None = None) -> Dict[str, Any]:
    opts = options if isinstance(options, dict) else {}
    final = final_result if isinstance(final_result, dict) else {}
    metadata = _as_dict(_as_dict(final.get("meta")).get("input_metadata"))
    return {
        "version": VERSION,
        "document_type": "base_config_layering_report",
        "simple_rule": "ZIP traz o base_config padrão somente leitura; Lovable envia overlay do administrador e, opcionalmente, overlay do usuário; o parser faz merge em memória em cada execução.",
        "merge_order": [
            "1_embedded_base_config_do_zip_default",
            "2_admin_base_config_overlay_persistido_na_plataforma_sobrescreve_o_default",
            "3_user_base_config_overlay_persistido_por_usuario_ou_projeto_sobrescreve_admin_apenas_em_secoes_permitidas",
        ],
        "practical_model": {
            "admin_can_send_full_copy_or_patch": True,
            "full_copy_behavior": "se o admin salvar uma cópia completa do base_config com adições, ela funciona como overlay profundo sobre o ZIP; valores iguais permanecem iguais e adições entram.",
            "user_overlay_behavior": "deve ser pequeno e focado: bancos personalizados, aliases locais, unidades aceitas pelo usuário/projeto; não deve mexer em runtime/API/políticas críticas.",
            "zip_is_not_mutated": True,
        },
        "payload_boundary": {
            "payload": "somente dados variáveis do documento: nome, páginas, ranges, headers observados, samples e contexto documental",
            "runtime_options": "endpoint/cache/timeout ficam fora do payload e são opções de execução da UI/worker",
            "admin_config_overlay": "configuração persistida da plataforma/admin",
            "user_config_overlay": "configuração persistida por usuário/projeto",
        },
        "current_run_metadata": {
            "config_fragments_loaded": _as_list(_as_dict(metadata.get("base_config") or {}).get("fragments_loaded")) or _as_list(_as_dict(_as_dict(final.get("meta")).get("performance")).get("base_config_fragments_loaded")),
            "user_overlay_present": bool(opts.get("user_base_config") or opts.get("user_base_config_overlay")),
            "admin_overlay_present": bool(opts.get("admin_base_config") or opts.get("admin_base_config_overlay")),
        },
        "conflict_policy": {
            "order": "user_project_overlay vence admin_overlay; admin_overlay vence zip_default",
            "conflicts_are_not_fatal": True,
            "lovable_should_show_conflict_if_same_key_differs": True,
            "recommendation": "manter overlays pequenos; admin pode enviar cópia completa, mas usuário deve enviar apenas diferenças do projeto"
        },
        "effective_config_model": {
            "base_config_default": "vem dentro do ZIP e é somente leitura",
            "admin_config": "persistido pela plataforma; pode ser cópia completa ou patch",
            "user_config": "persistido por usuário/projeto; deve ser overlay pequeno",
            "effective_config": "resultado do merge em memória para uma execução",
        },
    }
