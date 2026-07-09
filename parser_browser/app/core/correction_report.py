from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

try:
    from pydantic import BaseModel
except Exception:  # pragma: no cover
    BaseModel = object  # type: ignore


def _as_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(exclude_none=False)  # type: ignore[attr-defined]
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _norm_list(values: Iterable[Any]) -> List[Any]:
    out: List[Any] = []
    seen = set()
    for value in values or []:
        marker = repr(value)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(value)
    return out


def _block_page_info(block: Any) -> tuple[int | None, int | None, List[int]]:
    data = _as_dict(block)
    detalhes = dict(data.get("detalhes") or {})
    paginas = data.get("paginas") or detalhes.get("paginas") or []
    if not isinstance(paginas, list):
        paginas = []
    paginas_norm = sorted({int(p) for p in paginas if isinstance(p, (int, float)) and int(p) > 0})
    pagina_inicio = data.get("pagina_inicio") or detalhes.get("pagina_inicio")
    pagina_fim = data.get("pagina_fim") or detalhes.get("pagina_fim")
    try:
        pagina_inicio = int(pagina_inicio) if pagina_inicio not in (None, "") else None
    except Exception:
        pagina_inicio = None
    try:
        pagina_fim = int(pagina_fim) if pagina_fim not in (None, "") else None
    except Exception:
        pagina_fim = None
    if paginas_norm:
        pagina_inicio = pagina_inicio or paginas_norm[0]
        pagina_fim = pagina_fim or paginas_norm[-1]
    return pagina_inicio, pagina_fim, paginas_norm


def _collect_line_missing_fields(line: Any, *, principal: bool = False) -> List[str]:
    data = _as_dict(line)
    required = ["codigo", "banco", "descricao"]
    if principal:
        required.extend(["und", "quant", "valor_unit", "total"])
    else:
        required.extend(["und", "quant"])
    missing = []
    for field in required:
        value = data.get(field)
        if value in (None, ""):
            missing.append(field)
    return missing


def _iter_block_rows(block: Any) -> Iterable[Tuple[str, Dict[str, Any]]]:
    data = _as_dict(block)
    principal = data.get("principal")
    if principal:
        yield "principal", _as_dict(principal)
    for row in data.get("composicoes_auxiliares") or []:
        yield "composicao_auxiliar", _as_dict(row)
    for row in data.get("insumos") or []:
        yield "insumo", _as_dict(row)


def _line_total_or_fallback(row: Dict[str, Any]) -> float | None:
    total = _as_float(row.get("total"))
    if total is not None:
        return total
    quant = _as_float(row.get("quant"))
    unit = _as_float(row.get("valor_unit"))
    if quant is not None and unit is not None:
        return round(quant * unit, 6)
    return None


def _compute_math(block: Any, *, tolerance: float = 0.05) -> Dict[str, Any]:
    from app.parser.math_status import compute_component_math
    data = _as_dict(block)
    detalhes = dict(data.get("detalhes") or {})
    precomputed = detalhes.get("math_status")
    if isinstance(precomputed, dict) and precomputed.get("status"):
        return dict(precomputed)
    return compute_component_math(data, tolerance_abs=tolerance)


def _math_status_is_error(status: Dict[str, Any]) -> bool:
    return str((status or {}).get("status") or "") in {
        "component_sum_lower_than_principal",
        "component_sum_greater_than_principal",
    }


def _is_sicro_special_block(block: Any) -> bool:
    try:
        from app.parser.math_status import is_sicro_special_block
        return bool(is_sicro_special_block(block))
    except Exception:
        data = _as_dict(block)
        principal = _as_dict(data.get("principal"))
        return "SICRO" in str(principal.get("banco") or "").upper()





def _sicro_dict_from_block(block: Any) -> Dict[str, Any]:
    data = _as_dict(block)
    detalhes = data.get("detalhes") if isinstance(data.get("detalhes"), dict) else {}
    # v61.0.57 public contract: SICRO sections live directly on the block.
    if isinstance(data.get("secoes"), dict) and data.get("secoes"):
        out = {"secoes": dict(data.get("secoes") or {})}
        for key in ("validacao", "resumos", "document_consistency", "document_consistency_warnings", "text_integrity", "text_audit_summary"):
            if isinstance(data.get(key), (dict, list)) and data.get(key):
                out[key] = data.get(key)
        return out
    if isinstance(data.get("sicro"), dict):
        return dict(data.get("sicro") or {})
    if isinstance(detalhes.get("sicro"), dict):
        return dict(detalhes.get("sicro") or {})
    return {}


def _sicro_validation_ok(block: Any) -> bool:
    """Return True when a block is already validated by the native SICRO engine.

    SICRO has a different contract from SINAPI-like compositions.  In the clean
    contract, the authoritative information is under ``sicro.secoes`` /
    ``sicro.validacao``.  Legacy fields such as ``insumos`` or
    ``composicoes_auxiliares`` are intentionally empty and must not be used to
    raise ``campos_vazios``.
    """
    data = _as_dict(block)
    detalhes = data.get("detalhes") if isinstance(data.get("detalhes"), dict) else {}
    sicro = _sicro_dict_from_block(data)
    if not isinstance(sicro, dict) or not sicro:
        return False

    validacao = sicro.get("validacao") if isinstance(sicro.get("validacao"), dict) else {}
    if validacao:
        if validacao.get("ok") is False:
            return False
        if validacao.get("issues"):
            return False
        if validacao.get("contract_issues"):
            return False
        if validacao.get("text_warnings"):
            return False

    secoes = sicro.get("secoes") if isinstance(sicro.get("secoes"), dict) else {}
    has_section_rows = False
    for section in (secoes or {}).values():
        if isinstance(section, dict) and isinstance(section.get("linhas"), list) and section.get("linhas"):
            has_section_rows = True
            break
    has_public_rows = any(
        isinstance(sicro.get(key), list) and bool(sicro.get(key))
        for key in (
            "equipamentos",
            "mao_obra",
            "materiais",
            "atividades_auxiliares",
            "tempos_fixos",
            "momentos_transporte",
        )
    )
    # Some valid SICRO transport compositions may have only section A/B and
    # summaries; either representation is enough as long as the native contract
    # was attached and did not report issues.
    native_meta = data.get("sicro_native") or detalhes.get("sicro_native")
    native_source = isinstance(native_meta, dict) and str(native_meta.get("source") or "").startswith("sicro_only")
    return bool(has_section_rows or has_public_rows or validacao or native_source)


def _sicro_correction_status(block: Any) -> Dict[str, Any]:
    sicro = _sicro_dict_from_block(block)
    validacao = sicro.get("validacao") if isinstance(sicro.get("validacao"), dict) else {}
    return {
        "status": "sicro_native_validated" if _sicro_validation_ok(block) else "sicro_native_contract_missing",
        "strict_sum_validation": False,
        "sicro_validacao_ok": bool(validacao.get("ok")) if validacao else _sicro_validation_ok(block),
        "issues": list(validacao.get("issues") or []) if isinstance(validacao, dict) else [],
        "text_warnings": list(validacao.get("text_warnings") or []) if isinstance(validacao, dict) else [],
        "contract_issues": list(validacao.get("contract_issues") or []) if isinstance(validacao, dict) else [],
    }


def _sicro_should_skip_generic_validation(block: Any) -> bool:
    return _is_sicro_special_block(block) and _sicro_validation_ok(block)

def build_correction_document(composicoes: Any, *, tolerance: float = 0.05, version: str = "v61.0.11-sicro-section-engine-and-span-fix") -> Tuple[Dict[str, Any], List[dict]]:
    data = _as_dict(composicoes)
    if isinstance(data.get("sinapi_like"), dict) or isinstance(data.get("sicro"), dict):
        collections = {}
        for family in ("sinapi_like", "sicro"):
            fam = data.get(family) if isinstance(data.get(family), dict) else {}
            for name in ("principais", "auxiliares_globais"):
                blocks = fam.get(name) if isinstance(fam, dict) else None
                if isinstance(blocks, dict):
                    collections[f"{family}.{name}"] = blocks
    else:
        collections = {
            "principais": data.get("principais") or {},
            "auxiliares_globais": data.get("auxiliares_globais") or {},
        }
    entries: List[Dict[str, Any]] = []
    ocorrencias: List[dict] = []
    total_blocks = 0
    total_math_errors = 0
    total_missing_field_blocks = 0
    total_page_span_missing = 0

    for collection_name, blocks in collections.items():
        if not isinstance(blocks, dict):
            continue
        for key, block in blocks.items():
            total_blocks += 1
            block_data = _as_dict(block)
            principal = _as_dict(block_data.get("principal"))
            pagina_inicio, pagina_fim, paginas = _block_page_info(block_data)
            is_sicro_block = _is_sicro_special_block(block_data)
            sicro_contract_ok = is_sicro_block and _sicro_validation_ok(block_data)
            principal_missing = [] if sicro_contract_ok else _collect_line_missing_fields(principal, principal=True)
            row_issues: List[Dict[str, Any]] = []
            if not sicro_contract_ok:
                for idx, (row_type, row) in enumerate(_iter_block_rows(block_data)):
                    missing = _collect_line_missing_fields(row, principal=(row_type == "principal"))
                    financial_missing = [f for f in missing if f in {"und", "quant", "valor_unit", "total"}]
                    if missing:
                        row_issue = {
                            "tipo_linha": row_type,
                            "indice": idx,
                            "codigo": str(row.get("codigo") or ""),
                            "banco": str(row.get("banco") or ""),
                            "campos_faltantes": missing,
                            "campos_financeiros_faltantes": financial_missing,
                        }
                        detalhes_linha = dict(row.get("detalhes") or {})
                        tail_parse = detalhes_linha.get("tail_parse")
                        if isinstance(tail_parse, dict) and tail_parse:
                            row_issue["tail_parse"] = tail_parse
                        row_issues.append(row_issue)

            math_info = _sicro_correction_status(block_data) if sicro_contract_ok else _compute_math(block_data, tolerance=tolerance)
            block_errors: List[str] = []
            if _math_status_is_error(math_info):
                total_math_errors += 1
                block_errors.append("divergencia_matematica")
                ocorrencias.append({
                    "codigo": "composicao_divergencia_matematica",
                    "severidade": "erro",
                    "categoria": "composicoes",
                    "mensagem": f"Divergência matemática detectada na composição {key}.",
                    "etapa": "validacao_composicoes",
                    "item": str(block_data.get("item") or ""),
                    "ref_id": str(key),
                    "pagina_inicio": pagina_inicio,
                    "pagina_fim": pagina_fim,
                    "causa": "A soma dos componentes coletados não bate com o total da composição principal.",
                    "sugestao": "Reprocessar o bloco completo e conferir se houve quebra indevida ou perda de linhas financeiras.",
                    "evidencia": {
                        "total_principal": math_info.get("principal_total") or math_info.get("total_principal"),
                        "soma_coletada": math_info.get("component_sum") or math_info.get("soma_coletada"),
                        "diferenca": math_info.get("delta") or math_info.get("diferenca"),
                        "status": math_info.get("status"),
                        "summary_rows_ignored": math_info.get("summary_rows_ignored"),
                    },
                })

            if row_issues:
                total_missing_field_blocks += 1
                block_errors.append("campos_vazios")
                missing_severity = "aviso" if _is_sicro_special_block(block_data) else "erro"
                ocorrencias.append({
                    "codigo": "composicao_campos_vazios",
                    "severidade": missing_severity,
                    "categoria": "composicoes",
                    "mensagem": f"Campos vazios críticos detectados na composição {key}.",
                    "etapa": "validacao_composicoes",
                    "item": str(block_data.get("item") or ""),
                    "ref_id": str(key),
                    "pagina_inicio": pagina_inicio,
                    "pagina_fim": pagina_fim,
                    "causa": "Um ou mais campos relevantes ficaram vazios após a extração.",
                    "sugestao": "Tentar reextração local/contextual e revisar a composição no documento de correção.",
                    "evidencia": {
                        "linhas_afetadas": len(row_issues),
                        "campos_principal": principal_missing,
                    },
                })

            if pagina_inicio is None or pagina_fim is None:
                total_page_span_missing += 1
                block_errors.append("page_span_ausente")
                ocorrencias.append({
                    "codigo": "composicao_span_paginas_ausente",
                    "severidade": "aviso",
                    "categoria": "composicoes",
                    "mensagem": f"A composição {key} não possui rastreio completo de página inicial/final.",
                    "etapa": "validacao_composicoes",
                    "item": str(block_data.get("item") or ""),
                    "ref_id": str(key),
                    "causa": "O bloco foi materializado sem span completo de páginas.",
                    "sugestao": "Reprocessar o bloco em modo robusto e reforçar continuidade multi-página.",
                })

            if block_errors:
                detalhes = dict(block_data.get("detalhes") or {})
                entries.append({
                    "colecao": collection_name,
                    "chave": str(key),
                    "item": str(block_data.get("item") or ""),
                    "codigo": str(principal.get("codigo") or ""),
                    "banco": str(principal.get("banco") or ""),
                    "descricao": str(principal.get("descricao") or ""),
                    "und": str(principal.get("und") or ""),
                    "pagina_inicio": pagina_inicio,
                    "pagina_fim": pagina_fim,
                    "paginas": paginas,
                    "tipos_erro": block_errors,
                    "validacao_matematica": math_info,
                    "campos_faltantes": row_issues,
                    "motivo_fechamento": str(detalhes.get("motivo_fechamento") or ""),
                    "origens_extracao": _norm_list(detalhes.get("origens_extracao") or []),
                    "tentativas_recuperacao": _norm_list(detalhes.get("tentativas_recuperacao") or []),
                    "status_completude": str(detalhes.get("status_completude") or ""),
                })

    summary = {
        "total_blocos_analisados": total_blocks,
        "total_registros_com_erro": len(entries),
        "total_divergencias_matematicas": total_math_errors,
        "total_blocos_com_campos_vazios": total_missing_field_blocks,
        "total_blocos_sem_span_paginas": total_page_span_missing,
    }
    return {
        "versao": str(version or "v61.0.11-sicro-section-engine-and-span-fix"),
        "resumo": summary,
        "composicoes_com_problema": entries,
    }, ocorrencias
