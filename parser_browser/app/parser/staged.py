from __future__ import annotations

from typing import Any, Dict, List, Tuple
from contextlib import nullcontext

from app.core.pdf_session import PdfDocumentSession
from app.core.schemas import Composicoes, OrcamentoSintetico, ParseResponse, Validacao
from app.parser.budget import (
    _build_validation_resumo,
    _collect_item_refs,
    _is_probably_insumo_codigo,
    _parse_orcamento_sintetico,
    _push_message,
    _msg_invalid_budget_range,
    _msg_invalid_comp_range,
    _msg_item_without_analytic,
    _msg_budget_interval_expanded,
    _msg_comp_summary,
    _expand_orcamento_pages_if_needed,
    _ingest_external_messages,
    _resolve_budget_text_engine,
)
from app.core.pdf_text import extract_pages_text
from app.core.correction_report import build_correction_document
from app.parser.composition_repair import apply_docling_assistive_math_repair
from app.parser.correction_decision_report import augment_correction_with_repair_summary
from app.parser.table_semantics import summarize_session_tables
from app.parser.multi_validator import augment_compositions_with_multi_validation, augment_budget_with_multi_validation
from app.parser.budget_composition_reconcile import reconcile_budget_against_compositions
from app.parser.budget_math_validator import validate_budget_math
from app.parser.document_learning_layer import build_document_learning_profile
from app.parser.selective_reparse import build_weak_field_reparse_targets
from app.parser.selective_field_reparse_executor import run_selective_field_reparse_executor
from app.parser.candidate_profile_consensus_engine import run_candidate_profile_consensus_engine
from app.parser.line_certainty_closure import run_line_certainty_closure_engine
from app.parser.evidence_graph import build_evidence_graph, apply_evidence_graph_recheck
from app.parser.compositions import (
    parse_compositions_document,
    sanitize_composicoes_for_output,
    reapply_orcamento_relations,
)
from app.parser.sicro_native_bridge import run_sicro_native_for_compositions, merge_sicro_native_into_composicoes
from app.parser.sinapi_profile_recheck import apply_sinapi_profile_recheck
from app.parser.broken_line_recovery import (
    build_description_registry,
    apply_registry_recheck_to_budget,
    apply_registry_recheck_to_compositions,
)


def parse_budget_stage(
    pdf_bytes: bytes,
    ranges: Dict[str, Tuple[int, int]],
    config: dict,
    context: dict | None = None,
    pdf_session: PdfDocumentSession | None = None,
) -> Dict[str, Any]:
    context = context or {}
    avisos: List[str] = []
    erros: List[str] = []
    divergencias: List[dict] = []
    ocorrencias: List[dict] = []

    o_ini, o_fim = ranges.get("orcamento", (0, 0))
    table_meta: Dict[str, Any] = {"enabled": False, "applied_changes": []}
    session_cm = nullcontext(pdf_session) if pdf_session is not None else PdfDocumentSession(pdf_bytes)
    with session_cm as session:
        if context.get("structured_tables"):
            session.set_structured_tables(context.get("structured_tables"))
        if o_ini and o_fim and o_ini >= 1 and o_fim >= o_ini:
            budget_text_engine = _resolve_budget_text_engine(config)
            pages_text = extract_pages_text(pdf_bytes, o_ini, o_fim, pdf_session=session, engine=budget_text_engine)
            pages_text, o_fim_processado, expanded_orc = _expand_orcamento_pages_if_needed(
                pdf_bytes, o_ini, o_fim, pages_text, pdf_session=session, text_engine=budget_text_engine
            )
            orc, a, e, d, ocs = _parse_orcamento_sintetico(pages_text, config=config, context=context)
            table_meta = augment_budget_with_multi_validation(
                orc,
                pdf_session=session,
                page_range=(o_ini, o_fim_processado),
                context=context,
            )
            if table_meta.get("applied_changes"):
                ocorrencias.append({
                    "codigo": "orcamento_tabela_estrutural_aplicada",
                    "severidade": "info",
                    "categoria": "orcamento",
                    "mensagem": f"Ajustes estruturais por tabela aplicados no orçamento. Quantidade={len(table_meta.get('applied_changes') or [])}.",
                    "etapa": "orcamento",
                    "pagina_inicio": o_ini,
                    "pagina_fim": o_fim_processado,
                    "evidencia": {"quantidade": len(table_meta.get('applied_changes') or []), "exemplos": (table_meta.get('applied_changes') or [])[:10]},
                })
            avisos.extend(a)
            erros.extend(e)
            divergencias.extend(d)
            ocorrencias.extend(ocs)
            if expanded_orc:
                _push_message(
                    avisos,
                    erros,
                    ocorrencias,
                    codigo="orcamento_intervalo_expandido",
                    severidade="info",
                    categoria="orcamento",
                    mensagem=_msg_budget_interval_expanded(o_fim_processado),
                    etapa="orcamento",
                    pagina_inicio=o_ini,
                    pagina_fim=o_fim_processado,
                )
        else:
            orc = OrcamentoSintetico(itens_raiz=[], itens_plano=[])
            _push_message(
                avisos,
                erros,
                ocorrencias,
                codigo="orcamento_intervalo_invalido",
                severidade="aviso",
                categoria="orcamento",
                mensagem=_msg_invalid_budget_range(),
                etapa="orcamento",
                pagina_inicio=o_ini or None,
                pagina_fim=o_fim or None,
            )

    item_refs_list = _collect_item_refs(orc.itens_raiz)
    placeholders = [r for r in item_refs_list if str(r.get("codigo", "")).strip().upper() == "COMPOSICAO"]
    if placeholders:
        exemplos = ", ".join([f"item {r.get('item')}" for r in placeholders[:10]])
        _push_message(
            avisos,
            erros,
            ocorrencias,
            codigo="orcamento_codigo_placeholder",
            severidade="aviso",
            categoria="orcamento",
            mensagem=(
                f"Itens com código de composição ausente ou quebrado detectados no orçamento. Quantidade={len(placeholders)}. Exemplos: {exemplos}"
            ),
            etapa="orcamento",
            evidencia={"exemplos": exemplos, "quantidade": len(placeholders)},
        )
        item_refs_list = [r for r in item_refs_list if r not in placeholders]

    insumos_no_orc = []
    def _walk_nodes(nodes):
        for n in nodes or []:
            yield n
            filhos = getattr(n, "filhos", None) if not isinstance(n, dict) else n.get("filhos")
            yield from _walk_nodes(filhos or [])

    for n in _walk_nodes(orc.itens_raiz):
        tipo = (getattr(n, "tipo", None) if not isinstance(n, dict) else n.get("tipo")) or ""
        if str(tipo).lower() != "item":
            continue
        codigo = (getattr(n, "codigo", None) if not isinstance(n, dict) else n.get("codigo")) or ""
        fonte = (getattr(n, "fonte", None) if not isinstance(n, dict) else n.get("fonte")) or ""
        item = (getattr(n, "item", None) if not isinstance(n, dict) else n.get("item")) or ""
        if _is_probably_insumo_codigo(str(codigo), str(fonte)):
            insumos_no_orc.append(f"{codigo}|{fonte} (item {item})")

    for rid in sorted(set(insumos_no_orc)):
        item = ""
        if " (item " in rid:
            item = rid.split(" (item ", 1)[1].rstrip(")")
        _push_message(
            avisos,
            erros,
            ocorrencias,
            codigo="item_sem_composicao_analitica",
            severidade="aviso",
            categoria="orcamento",
            mensagem=_msg_item_without_analytic(item=item or "?", ref_id=rid.split(" (item ")[0]),
            etapa="orcamento",
            item=item,
            ref_id=rid.split(" (item ")[0],
            causa="Item do orçamento parece ser insumo direto ou está sem tabela analítica correspondente no anexo.",
            sugestao="Conferir se o item foi lançado diretamente no orçamento ou se a composição analítica ficou ausente no PDF.",
        )

    return {
        "orcamento_sintetico": orc.model_dump(exclude_none=True, exclude_unset=True),
        "item_refs": item_refs_list,
        "table_structure": table_meta,
        "avisos": avisos,
        "erros": erros,
        "divergencias": divergencias,
        "ocorrencias": ocorrencias,
    }


def parse_compositions_stage(
    pdf_bytes: bytes,
    ranges: Dict[str, Tuple[int, int]],
    config: dict,
    context: dict | None = None,
    pdf_session: PdfDocumentSession | None = None,
) -> Dict[str, Any]:
    context = context or {}
    avisos: List[str] = []
    erros: List[str] = []
    c_ini, c_fim = ranges.get("composicoes", (0, 0))
    comp = Composicoes(principais={}, auxiliares_globais={}, aliases_auxiliares={})

    ocorrencias: List[dict] = []
    if not (c_ini and c_fim and c_ini >= 1 and c_fim >= c_ini):
        _push_message(
            avisos,
            erros,
            ocorrencias,
            codigo="composicoes_intervalo_invalido",
            severidade="aviso",
            categoria="composicoes",
            mensagem=_msg_invalid_comp_range(),
            etapa="composicoes",
            pagina_inicio=c_ini or None,
            pagina_fim=c_fim or None,
        )
        return {
            "composicoes": comp.model_dump(exclude_none=True, exclude_unset=True),
            "avisos": avisos,
            "erros": erros,
            "ocorrencias": ocorrencias,
            "itens_faltando": [],
            "composicoes_nao_associadas_diretamente": [],
            "associacoes_por_indicio": [],
        }

    table_semantics = {"enabled": False, "tables": []}
    session_cm = nullcontext(pdf_session) if pdf_session is not None else PdfDocumentSession(pdf_bytes)
    with session_cm as full_pdf_session:
        if context.get("structured_tables"):
            full_pdf_session.set_structured_tables(context.get("structured_tables"))
        profile = dict((context or {}).get("document_profile") or {})
        parser_options = dict((config or {}).get("parser_options") or {})
        has_docling_structures = bool((context or {}).get("structured_tables"))
        if has_docling_structures and parser_options.get("skip_full_table_semantics_when_docling", True):
            table_semantics = {
                "enabled": True,
                "source": "docling_seed_schema",
                "skipped_full_scan": True,
                "reason": "v60_docling_column_map_uses_seed_geometry",
                "page_range": {"start": c_ini, "end": c_fim},
                "tables": [],
            }
        else:
            table_semantics = summarize_session_tables(full_pdf_session, page_range=(c_ini, c_fim), profile=profile, family="composition")
        comp, comp_avisos, comp_erros, _, _, _ = parse_compositions_document(
            pdf_bytes=pdf_bytes,
            start_1based=c_ini,
            end_1based=c_fim,
            config=config,
            item_refs=[],
            context=context,
            pdf_session=full_pdf_session,
        )
        # v61.0.14: SICRO final engine v61.0.20 is the official source for SICRO blocks.
        # It replaces legacy SICRO extraction before validation and correction-document generation.
        sicro_native = {"enabled": False, "reason": "disabled"}
        try:
            sicro_native_payload = run_sicro_native_for_compositions(pdf_bytes, c_ini, c_fim)
            comp, sicro_native = merge_sicro_native_into_composicoes(comp, sicro_native_payload)
            if sicro_native.get("ok"):
                avisos.append(
                    f"[sicro-native] version={sicro_native.get('version')}; total={sicro_native.get('native_total_composicoes')}; "
                    f"replaced={len(sicro_native.get('replaced') or [])}; aux={len(sicro_native.get('created_auxiliares') or [])}; "
                    f"text_warnings={sicro_native.get('text_warnings')}"
                )
            else:
                erros.append(f"[sicro-native] falha: {sicro_native.get('errors')}")
        except Exception as exc:
            sicro_native = {"enabled": True, "ok": False, "errors": [{"code": "sicro_native_unhandled", "message": str(exc), "type": exc.__class__.__name__}]}
            erros.append(f"[sicro-native] erro inesperado: {exc}")
        if has_docling_structures and parser_options.get("skip_full_multi_validator_when_docling", True):
            multi_validation = {
                "enabled": False,
                "mode": "skipped",
                "reason": "v60_docling_column_map_active",
                "pages": {"inicio": c_ini, "fim": c_fim},
            }
            for _collection in (comp.principais or {}, comp.auxiliares_globais or {}):
                for _block in _collection.values():
                    _det = dict(getattr(_block, "detalhes", {}) or {})
                    _det["multi_validator"] = {"enabled": False, "skipped": True, "reason": "v60_docling_column_map_active"}
                    _block.detalhes = _det
        else:
            multi_validation = augment_compositions_with_multi_validation(
                comp,
                pdf_session=full_pdf_session,
                page_range=(c_ini, c_fim),
                context=context,
            )
        sinapi_profile_recheck = apply_sinapi_profile_recheck(comp, context=context, config=config)
        docling_assistive_repair = apply_docling_assistive_math_repair(
            comp,
            context=context,
            config=config,
            page_range=(c_ini, c_fim),
            pdf_session=full_pdf_session,
        )
    _ingest_external_messages(avisos, erros, ocorrencias, mensagens=comp_avisos, severidade="aviso", categoria="composicoes", etapa="composicoes")
    _ingest_external_messages(avisos, erros, ocorrencias, mensagens=comp_erros, severidade="erro", categoria="composicoes", etapa="composicoes")
    _push_message(
        avisos, erros, ocorrencias,
        codigo="composicoes_resumo_processamento",
        severidade="info",
        categoria="composicoes",
        mensagem=_msg_comp_summary(c_ini, c_fim, comp),
        etapa="composicoes",
        pagina_inicio=c_ini,
        pagina_fim=c_fim,
        evidencia={
            "principais": len(comp.principais),
            "auxiliares_globais": len(comp.auxiliares_globais),
            "aliases": len(comp.aliases_auxiliares),
        },
    )
    return {
        "composicoes": comp.model_dump(exclude_none=True, exclude_unset=True),
        "table_semantics": table_semantics,
        "multi_validator": multi_validation,
        "docling_assistive_repair": docling_assistive_repair,
        "sinapi_profile_recheck": sinapi_profile_recheck,
        "sicro_native": sicro_native,
        "avisos": avisos,
        "erros": erros,
        "ocorrencias": ocorrencias,
        "itens_faltando": [],
        "composicoes_nao_associadas_diretamente": [],
        "associacoes_por_indicio": [],
    }


def merge_staged_results(
    budget_stage: Dict[str, Any],
    compositions_stage: Dict[str, Any],
    config: dict,
    context: dict | None = None,
) -> Dict[str, Any]:
    context = context or {}
    avisos = list(budget_stage.get("avisos") or []) + list(compositions_stage.get("avisos") or [])
    erros = list(budget_stage.get("erros") or []) + list(compositions_stage.get("erros") or [])
    divergencias = list(budget_stage.get("divergencias") or [])
    ocorrencias = list(budget_stage.get("ocorrencias") or []) + list(compositions_stage.get("ocorrencias") or [])

    orc_dict = dict(budget_stage.get("orcamento_sintetico") or {})
    orc = OrcamentoSintetico(**orc_dict)
    item_refs = list(budget_stage.get("item_refs") or [])

    comp = Composicoes(**(compositions_stage.get("composicoes") or {}))
    comp, relation_avisos, itens_faltando, composicoes_nao_associadas, associacoes_por_indicio = reapply_orcamento_relations(
        comp,
        item_refs=item_refs,
        config=config,
    )
    avisos.extend(relation_avisos)

    if not getattr(orc, "descricao", ""):
        orc.descricao = str(context.get("obra_nome") or "").strip()

    orc, reconcile_changes, reconcile_occurrences = reconcile_budget_against_compositions(orc, comp)
    ocorrencias.extend(reconcile_occurrences)
    if reconcile_changes:
        avisos.append(f"[merge] reconciliacao_orcamento_composicoes=mandatory; ajustes={len(reconcile_changes)}")

    # v61.0.26: build a document-wide evidence graph before the conservative
    # registry pass.  It uses cross-table agreement, repetition and quality to
    # confirm descriptions, and also records negative locks so broken fragments
    # are not attached to rows that are already complete.
    evidence_graph = build_evidence_graph(orc, comp, context=context)
    evidence_graph_recheck = apply_evidence_graph_recheck(orc, comp, evidence_graph)

    # Compatibility/conservative pass kept after the evidence graph.  The graph
    # may repair high-confidence budget/composition descriptions first; this
    # registry catches remaining truncations without relying on document-specific
    # text rules.
    description_registry = build_description_registry(orc, comp)
    budget_profile_recheck = apply_registry_recheck_to_budget(orc, description_registry)
    composition_registry_recheck = apply_registry_recheck_to_compositions(comp, description_registry)
    if (evidence_graph_recheck.get("metrics") or {}).get("repairs_applied"):
        avisos.append(f"[merge] evidence_graph_recheck=applied; ajustes={(evidence_graph_recheck.get('metrics') or {}).get('repairs_applied')}")
    if (budget_profile_recheck.get("metrics") or {}).get("repairs_applied"):
        avisos.append(f"[merge] budget_profile_recheck=applied; ajustes={(budget_profile_recheck.get('metrics') or {}).get('repairs_applied')}")
    if (composition_registry_recheck.get("metrics") or {}).get("repairs_applied"):
        avisos.append(f"[merge] composition_registry_recheck=applied; ajustes={(composition_registry_recheck.get('metrics') or {}).get('repairs_applied')}")

    document_learning_profile = build_document_learning_profile(orc, comp, context=context, config=config)
    weak_field_reparse_plan = build_weak_field_reparse_targets({"orcamento_sintetico": orc.model_dump(exclude_none=True) if hasattr(orc, "model_dump") else {}, "composicoes": sanitize_composicoes_for_output(comp, include_tipo=True).model_dump(exclude_none=True) if hasattr(sanitize_composicoes_for_output(comp, include_tipo=True), "model_dump") else {}}, document_learning_profile)
    budget_math_validation = validate_budget_math(orc)
    include_tipo = bool(((config or {}).get("output_options") or {}).get("include_tipo_in_final_json") or ((context or {}).get("output_options") or {}).get("include_tipo_in_final_json"))
    comp_out = sanitize_composicoes_for_output(comp, include_tipo=include_tipo)
    current_release = str(((config or {}).get("project") or {}).get("current_release") or "v61.0.11-sicro-section-engine-and-span-fix")
    documento_correcao, correction_occurrences = build_correction_document(comp_out, version=current_release)
    repair_summary = dict(compositions_stage.get("docling_assistive_repair") or {})
    sinapi_profile_summary = dict(compositions_stage.get("sinapi_profile_recheck") or {})
    sicro_native_summary = dict(compositions_stage.get("sicro_native") or {})
    profile_recheck_summary = {
        "version": "v61.0.75-correction-output-contract-and-review-index",
        "description_registry_size": len(description_registry),
        "evidence_graph": evidence_graph_recheck,
        "budget": budget_profile_recheck,
        "compositions": composition_registry_recheck,
        "budget_math_validation": budget_math_validation,
    }
    # Ensure correction document is built after SICRO native merge; attach the native audit for Lovable/debug.
    if sicro_native_summary:
        documento_correcao.setdefault("sicro_native", sicro_native_summary)
    documento_correcao = augment_correction_with_repair_summary(documento_correcao, repair_summary)
    if sicro_native_summary:
        ocorrencias.append({
            "codigo": "sicro_native_v61_0_20_merge",
            "severidade": "info" if sicro_native_summary.get("ok") else "aviso",
            "categoria": "composicoes",
            "mensagem": (
                f"SICRO nativo v61.0.20 aplicado: total={sicro_native_summary.get('native_total_composicoes', 0)}, "
                f"substituidos={len(sicro_native_summary.get('replaced') or [])}, "
                f"auxiliares={len(sicro_native_summary.get('created_auxiliares') or [])}, "
                f"text_warnings={sicro_native_summary.get('text_warnings', 0)}."
            ),
            "etapa": "sicro_native_merge",
            "evidencia": sicro_native_summary,
        })
    if profile_recheck_summary:
        bm = (profile_recheck_summary.get("budget") or {}).get("metrics") or {}
        cm = (profile_recheck_summary.get("compositions") or {}).get("metrics") or {}
        ocorrencias.append({
            "codigo": "profile_aware_broken_line_recheck",
            "severidade": "info",
            "categoria": "orcamento",
            "mensagem": (
                f"Rechecagem perfil/descrição aplicada ao orçamento e SINAPI-like: "
                f"budget_reparos={bm.get('repairs_applied', 0)}, "
                f"composition_reparos={cm.get('repairs_applied', 0)}, "
                f"registry={profile_recheck_summary.get('description_registry_size', 0)}."
            ),
            "etapa": "profile_aware_broken_line_recheck",
            "evidencia": profile_recheck_summary,
        })
    if (budget_math_validation.get("summary") or {}).get("warnings"):
        ocorrencias.append({
            "codigo": "budget_math_recheck_candidates",
            "severidade": "aviso",
            "categoria": "orcamento",
            "mensagem": f"Validação matemática do orçamento encontrou {(budget_math_validation.get('summary') or {}).get('warnings', 0)} linhas candidatas a rechecagem.",
            "etapa": "budget_math_validator",
            "evidencia": budget_math_validation,
        })
    if document_learning_profile:
        ocorrencias.append({
            "codigo": "document_learning_profile",
            "severidade": "info",
            "categoria": "sistema",
            "mensagem": "Perfil do documento aprendido para orçamento, SINAPI-like e SICRO.",
            "etapa": "document_learning_layer",
            "evidencia": {
                "new_units_detected": len(((document_learning_profile.get("enrichment_report") or {}).get("new_units_detected") or [])),
                "sicro_blocks": (document_learning_profile.get("sicro_profile") or {}).get("blocks_seen"),
                "sinapi_like_blocks": (document_learning_profile.get("sinapi_like_profile") or {}).get("blocks_seen"),
            },
        })
    if sinapi_profile_summary:
        m = dict(sinapi_profile_summary.get("metrics") or {})
        ocorrencias.append({
            "codigo": "sinapi_profile_recheck",
            "severidade": "info",
            "categoria": "composicoes",
            "mensagem": (
                f"Rechecagem SINAPI-like com perfil aprendido: linhas={m.get('non_sicro_rows', 0)}, "
                f"registry={m.get('description_registry_entries', 0)}, "
                f"reparos_texto={m.get('description_repairs_applied', 0)}, "
                f"reparos_matematicos={m.get('math_repairs_applied', 0)}."
            ),
            "etapa": "sinapi_profile_recheck",
            "evidencia": {k: v for k, v in sinapi_profile_summary.items() if k != "registry_preview"},
        })
    if repair_summary:
        ocorrencias.append({
            "codigo": "docling_assistive_math_repair",
            "severidade": "info",
            "categoria": "composicoes",
            "mensagem": (
                f"Reparo assistivo com bandas Docling: candidatos={repair_summary.get('repair_candidates', 0)}, "
                f"tentativas={repair_summary.get('repairs_attempted', 0)}, "
                f"aceitos={repair_summary.get('repairs_accepted', 0)}."
            ),
            "etapa": "reparo_composicoes",
            "evidencia": repair_summary,
        })
    ocorrencias.extend(correction_occurrences)
    resumo_validacao = _build_validation_resumo(avisos=avisos, erros=erros, ocorrencias=ocorrencias)
    validacao_kwargs = {
        "itens_faltando": sorted(set(itens_faltando)),
        "composicoes_nao_associadas_diretamente": sorted(set(composicoes_nao_associadas)),
        "associacoes_por_indicio": associacoes_por_indicio,
        "avisos": avisos,
        "erros": erros,
        "divergencias": divergencias,
        "ocorrencias": ocorrencias,
        "resumo": resumo_validacao,
    }

    resp = ParseResponse(
        base_id="misto",
        orcamento_sintetico=orc,
        composicoes=comp_out,
        validacao=Validacao(**validacao_kwargs),
        documento_correcao=documento_correcao,
    )
    resp.meta.performance["document_learning_profile"] = document_learning_profile
    resp.meta.performance["enrichment_report"] = document_learning_profile.get("enrichment_report", {})
    resp.meta.performance["evidence_graph"] = evidence_graph
    resp.meta.performance["profile_aware_recheck"] = profile_recheck_summary
    resp.meta.performance["budget_math_validation"] = budget_math_validation
    resp.meta.performance["weak_field_reparse_plan"] = weak_field_reparse_plan
    # Do not rely on pydantic's ``exclude_unset`` for meta: ``meta`` is created
    # by default and then populated by the merge/recheck stages, so older dumps
    # silently dropped the learned profile from the final JSON.
    payload = resp.model_dump(exclude_none=True, exclude_unset=True)
    payload["meta"] = resp.meta.model_dump(exclude_none=True)

    # v61.0.33: execute the evidence-only selective field reparse before the
    # browser worker attempts PDF-based targeted recovery.  This makes the
    # safest correction first: cross-checking budget <-> compositions using the
    # first extraction itself, then emitting only unresolved weak fields as
    # surgical recovery targets.
    payload, selective_field_report = run_selective_field_reparse_executor(payload, apply=True)
    payload.setdefault("meta", {}).setdefault("performance", {})["selective_field_reparse_executor"] = selective_field_report
    if selective_field_report.get("summary", {}).get("applied"):
        payload.setdefault("validacao", {}).setdefault("ocorrencias", []).append({
            "codigo": "selective_field_reparse_executor",
            "severidade": "info",
            "categoria": "rechecagem",
            "mensagem": f"Selective Field Reparse Executor aplicou {selective_field_report.get('summary', {}).get('applied', 0)} correções seguras antes da recuperação pesada.",
            "etapa": "selective_field_reparse_executor",
            "evidencia": selective_field_report.get("summary", {}),
        })

    # v61.0.35: orchestrate all description candidates produced by the first
    # extraction, cross-table evidence, ownership checks and conservative
    # current-value preservation.  This engine is additive: it only applies a
    # patch when the candidate wins by consensus; otherwise it records the
    # ambiguity for Lovable/debug overlay and leaves the JSON untouched.
    payload, consensus_report = run_candidate_profile_consensus_engine(payload, apply=True)
    payload.setdefault("meta", {}).setdefault("performance", {})["candidate_profile_consensus_engine"] = consensus_report
    if consensus_report.get("summary", {}).get("applied"):
        payload.setdefault("validacao", {}).setdefault("ocorrencias", []).append({
            "codigo": "candidate_profile_consensus_engine",
            "severidade": "info",
            "categoria": "rechecagem",
            "mensagem": f"Candidate Profile Consensus Engine aplicou {consensus_report.get('summary', {}).get('applied', 0)} correções por consenso de perfis.",
            "etapa": "candidate_profile_consensus_engine",
            "evidencia": consensus_report.get("summary", {}),
        })

    # v61.0.38: final semantic closure pass.  It treats budget rows,
    # SINAPI-like rows and SICRO section rows as evidence-bound records and
    # tries to close each one using cross-table facts, auxiliary-global facts,
    # numeric constraints and fragment ownership before targeted recovery asks
    # PyMuPDF to sweep unresolved fields.
    payload, line_closure_report = run_line_certainty_closure_engine(payload, apply=True, max_rounds=int(((context or {}).get("accuracy_profile") or {}).get("max_closure_rounds") or 8))
    payload.setdefault("meta", {}).setdefault("performance", {})["line_certainty_closure_engine"] = line_closure_report
    return payload
