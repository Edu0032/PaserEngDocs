from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Tuple

from app.core.numeric_fidelity import apply_numeric_sources_to_row, audit_decimal_loss


SICRO_SECTION_ALIASES = {
    "A": "equipamentos",
    "B": "mao_obra",
    "C": "materiais",
    "D": "atividades_auxiliares",
    "E": "tempos_fixos",
    "F": "momentos_transporte",
}
SICRO_PUBLIC_SECTION_KEYS = set(SICRO_SECTION_ALIASES.values())
SICRO_FORBIDDEN_ROW_FIELDS = {
    "descricao", "natureza", "tipo", "tipo_status", "row_uid", "block_uid",
    "page_hint", "row_index_in_block", "numeric_source", "detalhes", "valor_unit",
    "total", "quant", "und", "banco_coluna",
}


def _clean_empty_deep(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _clean_empty_deep(v) for k, v in obj.items() if v not in (None, "", [], {})}
    if isinstance(obj, list):
        return [_clean_empty_deep(v) for v in obj if v not in (None, "", [], {})]
    return obj


def _source_text(row: dict, field: str, fallback_field: str | None = None) -> Any:
    detalhes = row.get("detalhes") if isinstance(row.get("detalhes"), dict) else {}
    src = detalhes.get("numeric_source") if isinstance(detalhes, dict) else None
    if isinstance(src, dict):
        meta = src.get(field) or (src.get(fallback_field) if fallback_field else None)
        if isinstance(meta, dict) and meta.get("source_text") not in (None, ""):
            return str(meta.get("source_text")).strip()
    value = row.get(fallback_field or field)
    if isinstance(value, float):
        return str(value).replace('.', ',')
    return value




def _format_ptbr_public_number(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = (f"{value:.7f}" if abs(value) < 1 else f"{value:.4f}")
        text = text.rstrip('0').rstrip('.') if '.' in text else text
        return text.replace('.', ',')
    if isinstance(value, dict):
        return {k: _format_ptbr_public_number(v) for k, v in value.items() if v not in (None, '', [], {})}
    if isinstance(value, list):
        return [_format_ptbr_public_number(v) for v in value if v not in (None, '', [], {})]
    return value




def _export_sicro_summary(resumos: dict) -> dict:
    # v61.0.23: preserve all public summary fields produced by the native SICRO
    # engine.  Only empty/internal keys are removed recursively.
    if not isinstance(resumos, dict):
        return {}
    return _clean_empty_deep(_format_ptbr_public_number({k: v for k, v in resumos.items() if not str(k).startswith('_')}))


def _canon_bank_public(value: Any) -> str:
    s = str(value or '').strip().upper().replace(' ', '')
    if s in {'SICRO', 'SICRO2', 'SICRO3', 'DNIT'}:
        return 'SICRO'
    return str(value or '').strip().upper()


def _is_sicro_bank(value: Any) -> bool:
    return _canon_bank_public(value) == 'SICRO'


def _strip_runtime_keys(row: dict) -> dict:
    out: dict[str, Any] = {}
    for k, v in (row or {}).items():
        ks = str(k)
        if ks.startswith('_') or ks in {'row_uid', 'block_uid', 'page_hint', 'row_index_in_block', 'tipo_status', 'raw_trace'}:
            continue
        if ks == 'detalhes':
            # detalhes carries extraction internals. Domain information is lifted
            # into explicit public fields before this clean row is returned.
            continue
        out[ks] = _format_ptbr_public_number(v)
    return out


def _sicro_public_row(section: str, row: dict) -> dict:
    """Export one native SICRO section row as read-only public data.

    v61.0.58: Python must not cascade/recalculate SICRO section values from
    referenced auxiliaries.  The native SICRO engine is the source of truth for
    the printed values in each section row.  The D section relation is exported
    only as metadata for Lovable to understand downstream impact chains; it must
    never overwrite ``preco_unitario``/``custo``.
    """
    if not isinstance(row, dict):
        return {}
    original = dict(row or {})
    sec = str(section or '').upper()
    det = original.get('detalhes') if isinstance(original.get('detalhes'), dict) else {}
    src = det.get('numeric_source') if isinstance(det.get('numeric_source'), dict) else {}

    def numeric_text(*fields: str) -> Any:
        for field in fields:
            meta = src.get(field) if isinstance(src, dict) else None
            if isinstance(meta, dict) and meta.get('source_text') not in (None, ''):
                return str(meta.get('source_text')).strip()
        return None

    def pick(*values: Any) -> Any:
        for value in values:
            if value not in (None, '', [], {}):
                return value
        return None

    def put(out: dict, key: str, *values: Any) -> None:
        value = pick(*values)
        if value not in (None, '', [], {}) and out.get(key) in (None, '', [], {}):
            out[key] = _format_ptbr_public_number(value)

    bank = pick(original.get('banco'), original.get('fonte'), 'SICRO')
    out: dict[str, Any] = {}
    put(out, 'codigo', original.get('codigo'))
    put(out, 'banco', bank)

    # Native-only mapping.  Do not read generic aliases such as descricao/und/
    # quant/valor_unit/total here, because those can be introduced by generic
    # SINAPI-like or cascade stages after the native SICRO engine has already
    # emitted the correct structure.
    if sec == 'A':
        put(out, 'equipamento', original.get('equipamento'), original.get('descricao'))
        put(out, 'quantidade', original.get('quantidade'), numeric_text('quant'))
        utilizacao = dict(original.get('utilizacao') or {}) if isinstance(original.get('utilizacao'), dict) else {}
        if not utilizacao.get('operativa'):
            utilizacao['operativa'] = numeric_text('utilizacao_operativa')
        if not utilizacao.get('improdutiva'):
            utilizacao['improdutiva'] = numeric_text('utilizacao_improdutiva')
        if any(v not in (None, '', [], {}) for v in utilizacao.values()):
            out['utilizacao'] = _clean_empty_deep(_format_ptbr_public_number(utilizacao))
        custo_operacional = dict(original.get('custo_operacional') or {}) if isinstance(original.get('custo_operacional'), dict) else {}
        if not custo_operacional.get('operativa'):
            custo_operacional['operativa'] = numeric_text('custo_operacional_operativa')
        if not custo_operacional.get('improdutiva'):
            custo_operacional['improdutiva'] = numeric_text('custo_operacional_improdutiva')
        if any(v not in (None, '', [], {}) for v in custo_operacional.values()):
            out['custo_operacional'] = _clean_empty_deep(_format_ptbr_public_number(custo_operacional))
        put(out, 'custo_horario', original.get('custo_horario'), original.get('custo'), numeric_text('custo_horario', 'total'))
    elif sec == 'B':
        put(out, 'mao_obra', original.get('mao_obra'), original.get('descricao'))
        put(out, 'quantidade', original.get('quantidade'), numeric_text('quant'))
        put(out, 'salario_hora', original.get('salario_hora'), numeric_text('salario_hora', 'valor_unit'))
        put(out, 'custo_horario', original.get('custo_horario'), original.get('custo'), numeric_text('custo_horario', 'total'))
    elif sec == 'C':
        put(out, 'material', original.get('material'), original.get('descricao'))
        put(out, 'unidade', original.get('unidade'), original.get('und'))
        put(out, 'quantidade', original.get('quantidade'), numeric_text('quant'))
        put(out, 'preco_unitario', original.get('preco_unitario'), numeric_text('preco_unitario', 'valor_unit'))
        put(out, 'custo', original.get('custo'), original.get('custo_horario'), numeric_text('custo_horario', 'total'))
    elif sec == 'D':
        put(out, 'atividade_auxiliar', original.get('atividade_auxiliar'), original.get('descricao'))
        put(out, 'unidade', original.get('unidade'), original.get('und'))
        put(out, 'quantidade', original.get('quantidade'), numeric_text('quant'))
        put(out, 'preco_unitario', original.get('preco_unitario'), numeric_text('preco_unitario', 'valor_unit'))
        put(out, 'custo', original.get('custo'), original.get('custo_horario'), numeric_text('custo_horario', 'total'))
        codigo = str(out.get('codigo') or '').strip()
        banco_ref = _canon_bank_public(out.get('banco') or 'SICRO')
        if codigo:
            out['referencia'] = _clean_empty_deep({
                'tipo': 'composicao_auxiliar_sicro',
                'chave': f"{codigo.upper().replace(' ', '')}|{banco_ref}",
                'relacao': 'secao_D_referencia_auxiliar_sem_mutacao_no_python',
                'impacto_lovable': 'se_o_preco_da_auxiliar_for_alterado_no_lovable_recalcular_a_cadeia_que_referencia_esta_auxiliar',
            })
    elif sec == 'E':
        det = original.get('detalhes') if isinstance(original.get('detalhes'), dict) else {}
        put(out, 'insumo', det.get('insumo_origem'), original.get('insumo'))
        put(out, 'codigo', det.get('codigo_servico'), original.get('codigo'))
        put(out, 'tempo_fixo', original.get('tempo_fixo'), original.get('descricao'))
        put(out, 'unidade', original.get('unidade'), original.get('und'))
        put(out, 'quantidade', original.get('quantidade'), numeric_text('quant'))
        put(out, 'preco_unitario', original.get('preco_unitario'), numeric_text('preco_unitario', 'valor_unit'))
        put(out, 'custo', original.get('custo'), original.get('custo_horario'), numeric_text('custo_horario', 'total'))
    elif sec == 'F':
        det = original.get('detalhes') if isinstance(original.get('detalhes'), dict) else {}
        put(out, 'insumo', det.get('insumo_origem'), original.get('insumo'))
        put(out, 'momento_transporte', original.get('momento_transporte'), original.get('descricao'))
        put(out, 'unidade', original.get('unidade'), original.get('und'))
        put(out, 'quantidade', original.get('quantidade'), numeric_text('quant'))
        raw_dmt = det.get('dmt') if isinstance(det.get('dmt'), dict) else original.get('dmt') if isinstance(original.get('dmt'), dict) else {}
        dmt = {}
        for branch_name, branch in raw_dmt.items():
            if not isinstance(branch, dict):
                continue
            dmt[branch_name] = _clean_empty_deep({
                'codigo': branch.get('codigo'),
                'quantidade_dmt': branch.get('quantidade_dmt_text') or (str(branch.get('quantidade_dmt')).replace('.', ',') if branch.get('quantidade_dmt') is not None else None),
                'preco_unitario_dmt': branch.get('preco_unitario_dmt_text') or (str(branch.get('preco_unitario_dmt')).replace('.', ',') if branch.get('preco_unitario_dmt') is not None else None),
            })
        if dmt:
            out['dmt'] = dmt
        put(out, 'custo', original.get('custo'), original.get('custo_horario'), numeric_text('custo_horario', 'total'))
    else:
        allowed = {'codigo', 'banco', 'servico', 'unidade', 'quantidade', 'preco_unitario', 'custo', 'custo_horario'}
        for key, value in original.items():
            if key in allowed and value not in (None, '', [], {}):
                out[key] = _format_ptbr_public_number(value)

    forbidden = {
        'descricao', 'und', 'quant', 'valor_unit', 'total', 'banco_coluna',
        'banco_canonico', 'natureza', 'tipo', 'detalhes', '_cascaded_from',
        'sicro_section_totals', 'cascaded_from'
    }
    for key in list(out.keys()):
        if key in forbidden or str(key).startswith('_'):
            out.pop(key, None)
    return _clean_empty_deep(out)

def _section_code_from_public_key(public_key: str) -> str:
    for code, alias in SICRO_SECTION_ALIASES.items():
        if alias == public_key:
            return code
    return ""




def _sicro_pages_from_payload(sicro_payload: dict) -> list[int]:
    """Collect real page numbers from SICRO section rows before public cleanup."""
    pages: set[int] = set()
    if not isinstance(sicro_payload, dict):
        return []
    raw_sections = sicro_payload.get('secoes') if isinstance(sicro_payload.get('secoes'), dict) else {}
    public_keys = {'equipamentos','mao_obra','materiais','atividades_auxiliares','tempos_fixos','momentos_transporte'}
    sources: list[Any] = []
    if isinstance(raw_sections, dict):
        for sec_value in raw_sections.values():
            if isinstance(sec_value, dict) and isinstance(sec_value.get('linhas'), list):
                sources.append(sec_value.get('linhas'))
            elif isinstance(sec_value, list):
                sources.append(sec_value)
    for key in public_keys:
        if isinstance(sicro_payload.get(key), list):
            sources.append(sicro_payload.get(key))
    for rows in sources:
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            det = row.get('detalhes') if isinstance(row.get('detalhes'), dict) else {}
            for raw in (row.get('page'), row.get('pagina'), det.get('page'), det.get('pagina')):
                try:
                    if raw not in (None, ''):
                        pages.add(int(raw))
                except Exception:
                    pass
    return sorted(pages)


def _normalize_sicro_span(block: dict, sicro_payload: dict | None = None) -> None:
    """Fix SICRO page spans using real section rows and a conservative gap guard."""
    if not isinstance(block, dict):
        return
    pages = _sicro_pages_from_payload(sicro_payload or {})
    if not pages:
        raw_pages = block.get('paginas') if isinstance(block.get('paginas'), list) else []
        cleaned = []
        for raw in raw_pages:
            try:
                cleaned.append(int(raw))
            except Exception:
                pass
        cleaned = sorted(set(cleaned))
        if len(cleaned) >= 2 and cleaned[1] - cleaned[0] > 3:
            cleaned = cleaned[1:]
        pages = cleaned
    if pages:
        block['paginas'] = pages
        block['pagina_inicio'] = pages[0]
        block['pagina_fim'] = pages[-1]
    else:
        block.pop('paginas', None)
        block.pop('pagina_inicio', None)
        block.pop('pagina_fim', None)


def _normalize_sicro_payload(sicro: dict) -> dict:
    """Return the final public SICRO contract without legacy duplication.

    Contract v61.0.20:
    - the only official place for section rows is ``sicro.secoes.A-F``;
    - public aliases such as ``equipamentos``/``materiais`` are not emitted in
      the clean JSON to avoid duplicated data;
    - C/D/E/F use ``custo`` instead of ``custo_horario``;
    - debug structures (Docling maps, legacy math status, evidence) stay out of
      the clean payload.
    """
    if not isinstance(sicro, dict):
        return {}

    raw_sections = sicro.get("secoes") if isinstance(sicro.get("secoes"), dict) else {}
    canonical_sections: dict[str, Any] = {}

    for sec, public_key in SICRO_SECTION_ALIASES.items():
        sec_value = raw_sections.get(sec) if isinstance(raw_sections, dict) else None
        sec_meta: dict[str, Any] = {}
        rows: list[Any] = []
        if isinstance(sec_value, dict):
            rows = list(sec_value.get("linhas") or []) if isinstance(sec_value.get("linhas"), list) else []
            sec_meta = {k: v for k, v in sec_value.items() if k != "linhas"}
        elif isinstance(sec_value, list):
            rows = list(sec_value)
        elif isinstance(sicro.get(public_key), list):
            rows = list(sicro.get(public_key) or [])

        clean_rows = [_sicro_public_row(sec, r) for r in rows if isinstance(r, dict)]
        clean_rows = [r for r in clean_rows if isinstance(r, dict) and r]
        if not clean_rows:
            continue
        section_out: dict[str, Any] = {
            "nome": sec_meta.get("nome") or public_key,
            "public_key": public_key,
            "linhas": clean_rows,
        }
        if sec_meta.get("total_reportado") not in (None, "", [], {}):
            section_out["total_reportado"] = _format_ptbr_public_number(sec_meta.get("total_reportado"))
        if isinstance(sec_meta.get("validacao_total"), dict) and sec_meta.get("validacao_total"):
            section_out["validacao_total"] = _clean_empty_deep(_format_ptbr_public_number(sec_meta.get("validacao_total")))
        canonical_sections[sec] = section_out

    result: dict[str, Any] = {}
    if canonical_sections:
        result["secoes"] = canonical_sections

    resumos = sicro.get("resumos")
    if isinstance(resumos, dict) and resumos:
        result["resumos"] = _export_sicro_summary(resumos)

    validacao = sicro.get("validacao")
    if isinstance(validacao, dict) and validacao:
        # Keep only the compact domain validation, not row evidence/debug.
        result["validacao"] = _clean_empty_deep({
            "ok": validacao.get("ok"),
            "issues": validacao.get("issues") or [],
            "texto_ok": validacao.get("texto_ok"),
            "text_warnings": validacao.get("text_warnings") or [],
            "text_repairs_applied": validacao.get("text_repairs_applied") or [],
            "summary_validation": validacao.get("summary_validation") or {},
        })

    for optional in ("text_integrity", "document_consistency", "document_consistency_warnings", "text_audit_summary"):
        value = sicro.get(optional)
        if isinstance(value, (dict, list)) and value:
            result[optional] = _clean_empty_deep(_format_ptbr_public_number(value))

    return _clean_empty_deep({k: v for k, v in result.items() if v not in (None, "", [], {})})




def _normalize_sicro_principal(row: dict) -> dict:
    """Export a SICRO principal from native fields only.

    v61.0.58: do not restore principal numbers from generic fields or numeric
    sources after the native bridge.  If a later stage produced valor_unit/total
    or mutated floats, those values are ignored for SICRO public output.
    """
    if not isinstance(row, dict):
        return {}
    detalhes = row.get('detalhes') if isinstance(row.get('detalhes'), dict) else {}
    original = dict(detalhes.get('sicro_principal_original') or {})
    native = original if original else row
    src = (detalhes.get('numeric_source') if isinstance(detalhes.get('numeric_source'), dict) else {})

    def numeric_text(*fields: str) -> Any:
        for field in fields:
            meta = src.get(field) if isinstance(src, dict) else None
            if isinstance(meta, dict) and meta.get('source_text') not in (None, ''):
                return str(meta.get('source_text')).strip()
        return None

    def string_fallback(value: Any) -> Any:
        # Fallback to legacy/generic values only when they are textual tokens,
        # not mutated floats from cascade/debug math.
        return value if isinstance(value, str) and value.strip() else None

    def pick(*values: Any) -> Any:
        for value in values:
            if value not in (None, '', [], {}):
                return value
        return None

    out: dict[str, Any] = {}
    out['codigo'] = pick(native.get('codigo'))
    out['banco'] = pick(native.get('banco'), 'SICRO')
    out['servico'] = pick(native.get('servico'), string_fallback(row.get('descricao'))) 
    out['unidade'] = pick(native.get('unidade'), string_fallback(row.get('und'))) 
    out['quantidade'] = pick(native.get('quantidade'), numeric_text('quant'), string_fallback(row.get('quant'))) 
    out['custo_unitario'] = pick(native.get('custo_unitario'), numeric_text('valor_unit'), string_fallback(row.get('valor_unit'))) 
    out['custo_total'] = pick(native.get('custo_total'), numeric_text('total'), string_fallback(row.get('total'))) 
    if isinstance(native.get('document_consistency'), dict) and native.get('document_consistency'):
        out['document_consistency'] = native.get('document_consistency')
    for key in ('producao_equipe', 'fator_bdi', 'data_base', 'fonte'):
        if native.get(key) not in (None, '', [], {}):
            out[key] = native.get(key)

    forbidden = {
        'descricao', 'und', 'quant', 'valor_unit', 'total', 'banco_coluna',
        'banco_canonico', 'natureza', 'tipo', 'detalhes', '_cascaded_from',
        'sicro_section_totals', 'cascaded_from'
    }
    for key in list(out.keys()):
        if key in forbidden or str(key).startswith('_'):
            out.pop(key, None)
    return _clean_empty_deep(_format_ptbr_public_number(out))

def _dedup_strings(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values or []:
        s = str(value or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _dedup_dicts(values: Iterable[dict]) -> List[dict]:
    out: List[dict] = []
    seen = set()
    for value in values or []:
        if not isinstance(value, dict):
            continue
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(value)
    return out


def _short_message(message: str, *, limit: int = 160) -> str:
    s = " ".join(str(message or "").split())
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"


def _compact_occurrences(ocorrencias: Iterable[dict]) -> List[dict]:
    grouped: Dict[Tuple[str, str, str, str], dict] = {}
    order: List[Tuple[str, str, str, str]] = []
    for occ in ocorrencias or []:
        if not isinstance(occ, dict):
            continue
        codigo = str(occ.get("codigo") or "").strip() or "ocorrencia"
        severidade = str(occ.get("severidade") or "info").strip() or "info"
        categoria = str(occ.get("categoria") or "sistema").strip() or "sistema"
        etapa = str(occ.get("etapa") or "").strip()
        key = (codigo, severidade, categoria, etapa)
        if key not in grouped:
            grouped[key] = {
                "codigo": codigo,
                "severidade": severidade,
                "categoria": categoria,
                "etapa": etapa,
                "mensagem": _short_message(occ.get("mensagem") or codigo),
                "quantidade": 0,
                "exemplos": {},
                "detalhes": {},
            }
            order.append(key)
        entry = grouped[key]
        entry["quantidade"] += 1
        item = str(occ.get("item") or "").strip()
        ref = str(occ.get("ref_id") or "").strip()
        pag_ini = occ.get("pagina_inicio")
        pag_fim = occ.get("pagina_fim")
        exemplos = entry["exemplos"]
        if item:
            exemplos.setdefault("itens", [])
            if item not in exemplos["itens"] and len(exemplos["itens"]) < 6:
                exemplos["itens"].append(item)
        if ref:
            exemplos.setdefault("refs", [])
            if ref not in exemplos["refs"] and len(exemplos["refs"]) < 6:
                exemplos["refs"].append(ref)
        if pag_ini is not None:
            page_marker = pag_ini if pag_fim in (None, pag_ini) else f"{pag_ini}-{pag_fim}"
            exemplos.setdefault("paginas", [])
            if page_marker not in exemplos["paginas"] and len(exemplos["paginas"]) < 6:
                exemplos["paginas"].append(page_marker)

        detalhes = entry["detalhes"]
        if occ.get("causa") and "causa" not in detalhes:
            detalhes["causa"] = _short_message(str(occ.get("causa") or ""), limit=110)
        if occ.get("sugestao") and "sugestao" not in detalhes:
            detalhes["sugestao"] = _short_message(str(occ.get("sugestao") or ""), limit=110)
        evidencia = occ.get("evidencia")
        if isinstance(evidencia, dict):
            slim_evidence = {}
            for k in ("quantidade", "exemplos", "principais", "auxiliares_globais", "aliases"):
                if k in evidencia:
                    slim_evidence[k] = evidencia[k]
            if slim_evidence and "evidencia" not in detalhes:
                detalhes["evidencia"] = slim_evidence

    compacted: List[dict] = []
    for key in order:
        entry = grouped[key]
        if entry["quantidade"] > 1:
            entry["mensagem"] = f"{entry['mensagem']} (x{entry['quantidade']})"
        if not entry["exemplos"]:
            entry.pop("exemplos", None)
        if not entry["detalhes"]:
            entry.pop("detalhes", None)
        compacted.append(entry)
    return compacted


def _compact_associations(values: Iterable[dict]) -> List[dict]:
    out: List[dict] = []
    seen = set()
    for value in values or []:
        if not isinstance(value, dict):
            continue
        compact = {
            "status": str(value.get("status") or "associada_por_indicio"),
            "item_orcamento": str(value.get("item_orcamento") or ""),
            "ref_id_orcamento": str(value.get("ref_id_orcamento") or ""),
            "codigo_orcamento": str(value.get("codigo_orcamento") or ""),
            "codigo_composicao_encontrado": str(value.get("codigo_composicao_encontrado") or ""),
            "chave_bloco": str(value.get("chave_bloco") or ""),
            "divergencia_codigo": bool(value.get("divergencia_codigo")),
            "suspeitas": list(value.get("suspeitas") or []),
        }
        marker = json.dumps(compact, ensure_ascii=False, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(compact)
    return out


def compact_parse_result(result: dict) -> dict:
    validacao = result.get("validacao")
    if not isinstance(validacao, dict):
        return result

    compact_occurrences = _compact_occurrences(validacao.get("ocorrencias") or [])
    validacao["ocorrencias"] = compact_occurrences
    validacao["associacoes_por_indicio"] = _compact_associations(validacao.get("associacoes_por_indicio") or [])
    validacao["itens_faltando"] = sorted(set(validacao.get("itens_faltando") or []))
    validacao["itens_extras"] = sorted(set(validacao.get("itens_extras") or []))
    validacao["composicoes_nao_associadas_diretamente"] = sorted(set(validacao.get("composicoes_nao_associadas_diretamente") or []))

    resumo = dict(validacao.get("resumo") or {})
    resumo["total_ocorrencias_compactadas"] = len(compact_occurrences)
    resumo["agrupamento_aplicado"] = True
    resumo["total_associacoes_por_indicio"] = len(validacao.get("associacoes_por_indicio") or [])
    resumo["total_composicoes_nao_associadas"] = len(validacao.get("composicoes_nao_associadas_diretamente") or [])
    validacao["resumo"] = resumo

    # remove superfícies redundantes do payload final
    validacao.pop("avisos", None)
    validacao.pop("erros", None)
    validacao.pop("divergencias", None)

    for key in ("associacoes_por_indicio", "itens_faltando", "itens_extras", "composicoes_nao_associadas_diretamente"):
        if not validacao.get(key):
            validacao.pop(key, None)

    result["validacao"] = validacao
    return result



def _sanitize_public_description_value(value: Any) -> Any:
    """Remove public summary arrows without applying document-specific text rules."""
    if not isinstance(value, str):
        return value
    text = " ".join(value.replace("\u00a0", " ").split()).strip()
    if not text:
        return text
    # Summary markers must not leak inside public descriptions.  If the row is a
    # pure summary label, make it empty so correction/quality gates can flag it.
    norm = text.upper()
    if "=>" in text:
        before = text.split("=>", 1)[0].strip()
        if re.search(r"\b(CUSTO|VALOR|TOTAL|BDI|LS|MO)\b", before, flags=re.I) and len(before.split()) <= 8:
            return ""
        return before.rstrip(" -:")
    return text


def _format_public_row_numbers(row: dict) -> None:
    # Keep public numeric fidelity as pt-BR strings after all calculations/rechecks
    # have finished. Internal numeric values should live in audit/calculation
    # surfaces, not in the final public row fields.
    for key in ("quant", "valor_unit", "total", "quantidade", "preco_unitario", "custo_horario", "custo", "salario_hora", "custo_unitario", "custo_total"):
        if key in row and isinstance(row.get(key), (int, float)) and not isinstance(row.get(key), bool):
            row[key] = _format_ptbr_public_number(row.get(key))



def _format_public_budget_numbers(node: dict) -> None:
    if not isinstance(node, dict):
        return
    # v61.0.59: budget numeric_source is the physical PDF token and is
    # reapplied after any validation/recalculation stages that may have touched
    # public fields.  Calculations remain audit-only.
    apply_numeric_sources_to_row(node)
    for key in ("quant", "custo_unitario_sem_bdi", "custo_unitario_com_bdi", "custo_parcial", "custo_total", "total"):
        if key in node and isinstance(node.get(key), (int, float)) and not isinstance(node.get(key), bool):
            node[key] = _format_ptbr_public_number(node.get(key))
    decimal_issues = audit_decimal_loss(node)
    if decimal_issues:
        node.setdefault("detalhes", {}).setdefault("numeric_fidelity_issues", decimal_issues)
    detalhes = node.get("detalhes")
    if isinstance(detalhes, dict):
        detalhes.pop("numeric_source", None)
        if not detalhes:
            node.pop("detalhes", None)
    for key in ("descricao", "especificacao"):
        if key in node:
            node[key] = _sanitize_public_description_value(node.get(key))
    filhos = node.get("filhos")
    if isinstance(filhos, list):
        for child in filhos:
            if isinstance(child, dict):
                _format_public_budget_numbers(child)


def _format_public_budget_tree(result: dict) -> None:
    orc = result.get("orcamento_sintetico") if isinstance(result.get("orcamento_sintetico"), dict) else {}
    if not isinstance(orc, dict):
        return
    for key in ("total", "custo_total"):
        if key in orc and isinstance(orc.get(key), (int, float)) and not isinstance(orc.get(key), bool):
            orc[key] = _format_ptbr_public_number(orc.get(key))
    for node in orc.get("itens_raiz") or []:
        if isinstance(node, dict):
            _format_public_budget_numbers(node)


_PUBLIC_NUMERIC_FLOAT_FIELDS = {
    "quant", "valor_unit", "total", "quantidade", "preco_unitario", "custo_horario",
    "custo", "salario_hora", "custo_unitario", "custo_unitario_sem_bdi",
    "custo_unitario_com_bdi", "custo_parcial", "custo_total", "preco_item", "preco_total",
}
_INTERNAL_AUDIT_KEYS = {
    "detalhes", "math_status", "math_triage", "docling_assistance", "multi_validator",
    "numeric_fidelity_issues", "_calc", "validacao", "auditoria", "evidence", "evidencia",
    "field_evidence_grades", "meta", "performance", "documento_correcao",
    "documento_evidencias", "documento_enriquecimento", "analise_orcamentaria",
}

def _collect_public_float_errors(obj: Any, path: str = "") -> list[dict[str, Any]]:
    """Flag float leaks only in public domain numeric fields.

    v61.0.50: internal audit/math fields such as detalhes.math_status.delta are
    allowed to be floats.  The public fidelity gate must protect the values that
    Lovable displays as extracted budget/composition data, not diagnostic metrics.
    """
    errors: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k) in _INTERNAL_AUDIT_KEYS:
                continue
            child_path = f"{path}.{k}" if path else str(k)
            if isinstance(v, float):
                if str(k) in _PUBLIC_NUMERIC_FLOAT_FIELDS:
                    errors.append({"path": child_path, "field": str(k), "value": v})
            elif isinstance(v, (dict, list)):
                errors.extend(_collect_public_float_errors(v, child_path))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            child_path = f"{path}.{i}" if path else str(i)
            if isinstance(v, float):
                field = path.rsplit('.', 1)[-1] if path else ''
                if field in _PUBLIC_NUMERIC_FLOAT_FIELDS:
                    errors.append({"path": child_path, "field": field, "value": v})
            elif isinstance(v, (dict, list)):
                errors.extend(_collect_public_float_errors(v, child_path))
    return errors

def _public_description_fields(row: dict) -> None:
    for key in ("descricao", "especificacao", "material", "mao_obra", "equipamento", "atividade_auxiliar", "tempo_fixo", "momento_transporte", "servico"):
        if key in row:
            row[key] = _sanitize_public_description_value(row.get(key))

def _prune_runtime_row_fields(row: dict) -> dict:
    if not isinstance(row, dict):
        return row
    apply_numeric_sources_to_row(row)
    _format_public_row_numbers(row)
    _public_description_fields(row)
    decimal_issues = audit_decimal_loss(row)
    if decimal_issues:
        row.setdefault("detalhes", {}).setdefault("numeric_fidelity_issues", decimal_issues)
    for key in ("tipo", "tipo_status", "row_uid", "block_uid", "page_hint", "row_index_in_block"):
        row.pop(key, None)
    if not row.get('banco_coluna'):
        row.pop('banco_coluna', None)
    detalhes = row.get('detalhes')
    if isinstance(detalhes, dict):
        detalhes.pop('numeric_source', None)
        detalhes.pop('source_numeric_texts', None)
        detalhes.pop('code_bank_detection', None)
        detalhes.pop('secao_label', None)
        detalhes.pop('tipo_linha', None)
        # Keep domain-relevant SICRO data, but remove transient extraction internals.
        for k in list(detalhes.keys()):
            if str(k).startswith('_') or str(k).endswith('_debug'):
                detalhes.pop(k, None)
    if not row.get('detalhes'):
        row.pop('detalhes', None)
    if row.get('quant') in ('', None):
        row.pop('quant', None)
    if row.get('valor_unit') in ('', None):
        row.pop('valor_unit', None)
    if row.get('total') in ('', None):
        row.pop('total', None)
    return row





def _apply_sicro_native_public_block(block: dict, sicro_payload: dict | None = None) -> None:
    """Keep SICRO blocks in the native public shape: principal + secoes.

    This is not a late sanitizer; it is the public integration point for the
    native SICRO engine.  The generic SINAPI-like lists are internal-only for
    SICRO and are not exported.
    """
    if not isinstance(block, dict):
        return
    payload = sicro_payload
    if not isinstance(payload, dict):
        if isinstance(block.get('sicro'), dict):
            payload = block.get('sicro')
        else:
            det = block.get('detalhes') if isinstance(block.get('detalhes'), dict) else {}
            payload = det.get('sicro') if isinstance(det.get('sicro'), dict) else None
    normalized = _normalize_sicro_payload(payload or {}) if isinstance(payload, dict) else {}
    # Prefer the principal preserved from the native SICRO payload.  The block
    # principal may have been wrapped in the generic LinhaComposicao model and
    # later touched by generic repair/cascade passes; those values are not
    # allowed to mutate the SICRO public contract.
    native_principal = (payload or {}).get('principal') if isinstance(payload, dict) else None
    if isinstance(native_principal, dict) and native_principal:
        block['principal'] = _normalize_sicro_principal(native_principal)
    elif isinstance(block.get('principal'), dict):
        block['principal'] = _normalize_sicro_principal(block.get('principal') or {})
    if isinstance(normalized, dict):
        for key in ('secoes', 'resumos', 'validacao', 'text_integrity', 'document_consistency', 'document_consistency_warnings', 'text_audit_summary'):
            if normalized.get(key) not in (None, '', [], {}):
                block[key] = normalized.get(key)
    # keep page span, but remove internal/generic containers
    if isinstance(payload, dict):
        _normalize_sicro_span(block, payload)
    for key in ('sicro', 'detalhes', 'composicoes_auxiliares', 'insumos', 'sicro_section_totals', '_cascaded_from'):
        block.pop(key, None)
    # Avoid empty canonical containers and generic aliases at the block level.
    for key in ('descricao', 'und', 'quant', 'valor_unit', 'total', 'banco_coluna', 'banco_canonico'):
        block.pop(key, None)

def _is_sicro_public_block(block_key: str, block: dict) -> bool:
    principal = block.get('principal') if isinstance(block.get('principal'), dict) else {}
    banco = principal.get('banco') or principal.get('banco_canonico') or principal.get('banco_coluna') or ''
    if _is_sicro_bank(banco):
        return True
    if isinstance(block.get('secoes'), dict) and block.get('secoes'):
        return True
    if isinstance(block.get('sicro'), dict) and block.get('sicro'):
        return True
    if '|' in str(block_key) and _is_sicro_bank(str(block_key).split('|', 1)[1]):
        return True
    return False



def _block_has_item(block: dict) -> bool:
    return bool(str((block or {}).get('item') or '').strip())


def _enforce_sicro_item_classification(composicoes: dict) -> dict:
    """Move SICRO blocks according to the official rule: item => principal."""
    if not isinstance(composicoes, dict):
        return composicoes
    sicro = composicoes.setdefault('sicro', {'principais': {}, 'auxiliares_globais': {}})
    if not isinstance(sicro, dict):
        return composicoes
    principals = sicro.setdefault('principais', {})
    aux = sicro.setdefault('auxiliares_globais', {})
    if not isinstance(principals, dict) or not isinstance(aux, dict):
        return composicoes
    for key, block in list(principals.items()):
        if isinstance(block, dict) and not _block_has_item(block):
            aux[key] = block
            principals.pop(key, None)
    for key, block in list(aux.items()):
        if isinstance(block, dict) and _block_has_item(block):
            principals[key] = block
            aux.pop(key, None)
    return composicoes


def _prune_already_split_public_rows(composicoes: dict) -> None:
    if not isinstance(composicoes, dict):
        return
    for family in ('sinapi_like', 'sicro'):
        fam = composicoes.get(family)
        if not isinstance(fam, dict):
            continue
        for collection_name in ('principais', 'auxiliares_globais'):
            blocks = fam.get(collection_name)
            if not isinstance(blocks, dict):
                continue
            for key, block in list(blocks.items()):
                if not isinstance(block, dict):
                    continue
                if family == 'sicro' or _is_sicro_public_block(str(key), block):
                    payload = block.get('sicro') if isinstance(block.get('sicro'), dict) else None
                    if not isinstance(payload, dict):
                        det = block.get('detalhes') if isinstance(block.get('detalhes'), dict) else {}
                        payload = det.get('sicro') if isinstance(det.get('sicro'), dict) else None
                    _apply_sicro_native_public_block(block, payload)
                    continue
                principal = block.get('principal')
                if isinstance(principal, dict):
                    _prune_runtime_row_fields(principal)
                for group in ('composicoes_auxiliares', 'insumos'):
                    rows = block.get(group)
                    if isinstance(rows, list):
                        for row in rows:
                            if isinstance(row, dict):
                                _prune_runtime_row_fields(row)
                        if not rows:
                            block.pop(group, None)
                if not block.get('detalhes'):
                    block.pop('detalhes', None)

def _split_composicoes_by_family(composicoes: dict) -> dict:
    if not isinstance(composicoes, dict):
        return composicoes
    # Already split; keep as is but still enforce official SICRO item classification.
    if isinstance(composicoes.get('sinapi_like'), dict) or isinstance(composicoes.get('sicro'), dict):
        composicoes.setdefault('sinapi_like', {'principais': {}, 'auxiliares_globais': {}})
        composicoes.setdefault('sicro', {'principais': {}, 'auxiliares_globais': {}})
        _prune_already_split_public_rows(composicoes)
        return _enforce_sicro_item_classification(composicoes)
    sinapi_like = {'principais': {}, 'auxiliares_globais': {}}
    sicro = {'principais': {}, 'auxiliares_globais': {}}
    for collection_name in ('principais', 'auxiliares_globais'):
        blocks = composicoes.get(collection_name) or {}
        if not isinstance(blocks, dict):
            continue
        for key, block in blocks.items():
            if not isinstance(block, dict):
                continue
            target = sicro if _is_sicro_public_block(str(key), block) else sinapi_like
            target[collection_name][key] = block
    out = {
        'sinapi_like': sinapi_like,
        'sicro': sicro,
    }
    aliases = composicoes.get('aliases_auxiliares')
    if isinstance(aliases, dict) and aliases:
        out['aliases_auxiliares'] = aliases
    _prune_already_split_public_rows(out)
    return _enforce_sicro_item_classification(out)


def _iter_family_blocks(composicoes: dict):
    if not isinstance(composicoes, dict):
        return
    seen = set()
    for family in ('sinapi_like', 'sicro'):
        fam = composicoes.get(family) or {}
        if isinstance(fam, dict):
            for collection_name in ('principais', 'auxiliares_globais'):
                for key, block in (fam.get(collection_name) or {}).items():
                    if isinstance(block, dict):
                        marker = (family, collection_name, str(key), id(block))
                        if marker not in seen:
                            seen.add(marker)
                            yield family, collection_name, key, block
    # Some v61 public payloads still retain the flat legacy collections next to
    # the split family mirrors.  The quality gate must inspect them too; otherwise
    # flat SINAPI-like rows with missing numeric fields can escape as status=ok.
    for collection_name in ('principais', 'auxiliares_globais'):
        for key, block in (composicoes.get(collection_name) or {}).items():
            if isinstance(block, dict):
                family = 'sicro' if _is_sicro_public_block(str(key), block) else 'sinapi_like'
                marker = (family, collection_name, str(key), id(block))
                if marker not in seen:
                    seen.add(marker)
                    yield family, collection_name, key, block



def _iter_public_rows_in_block(block: dict):
    principal = block.get('principal') if isinstance(block.get('principal'), dict) else None
    if principal is not None:
        yield 'principal', None, principal
    for group in ('composicoes_auxiliares', 'insumos'):
        rows = block.get(group)
        if isinstance(rows, list):
            for idx, row in enumerate(rows):
                if isinstance(row, dict):
                    yield group, idx, row



def _public_text_issue_reason(value: Any) -> str:
    if not isinstance(value, str):
        return ''
    text = ' '.join(value.replace('\u00a0', ' ').split()).strip()
    if not text:
        return ''
    if '=>' in text:
        return 'arrow_marker'
    if text.startswith('-'):
        return 'leading_orphan_fragment'
    if len(re.findall(r"\bAF_\d{2}/\d{4}\b", text, flags=re.I)) >= 2:
        return 'multiple_service_anchors'
    if re.search(r"\b(COM ENCARGOS COMPLEMENTARES)\b\s+\w+\s+\w+\s+\w+", text, flags=re.I):
        suffix = re.split(r"COM ENCARGOS COMPLEMENTARES", text, flags=re.I, maxsplit=1)[1].strip(' -:.;')
        allowed = {'HORISTA', 'MENSALISTA', 'DIURNO', 'NOTURNO'}
        toks = suffix.upper().split()
        if toks and not (len(toks) <= 2 and all(t in allowed for t in toks)):
            return 'suspicious_suffix_after_confirmed_service'
    return ''

def _public_text_pollution_issues(result: dict) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    composicoes = result.get('composicoes') if isinstance(result.get('composicoes'), dict) else {}
    for family, collection, key, block in list(_iter_family_blocks(composicoes) or []):
        for group, idx, row in _iter_public_rows_in_block(block):
            for field in ('descricao', 'especificacao', 'material', 'mao_obra', 'equipamento', 'atividade_auxiliar', 'tempo_fixo', 'momento_transporte'):
                val = row.get(field)
                reason = _public_text_issue_reason(val)
                if reason:
                    issues.append({'code': 'public_text_pollution', 'reason': reason, 'family': family, 'collection': collection, 'block': key, 'row_group': group, 'row_index': idx, 'field': field, 'value': str(val)[:180]})
    def walk_budget(nodes, path='orcamento_sintetico.itens_raiz'):
        if not isinstance(nodes, list): return
        for i, node in enumerate(nodes):
            if isinstance(node, dict):
                val = node.get('especificacao') or node.get('descricao')
                reason = _public_text_issue_reason(val)
                if reason:
                    issues.append({'code': 'public_budget_text_pollution', 'reason': reason, 'path': f'{path}.{i}', 'item': node.get('item'), 'field': 'especificacao' if node.get('especificacao') else 'descricao', 'value': str(val)[:180]})
                walk_budget(node.get('filhos'), f'{path}.{i}.filhos')
    walk_budget(((result.get('orcamento_sintetico') or {}).get('itens_raiz') or []))
    return issues

def _quality_gate_final(result: dict) -> dict:
    composicoes = result.get('composicoes') if isinstance(result.get('composicoes'), dict) else {}
    issues: list[dict[str, Any]] = []
    sicro_missing: list[dict[str, Any]] = []
    float_errors: list[dict[str, Any]] = []
    # Recursive public numeric fidelity: final JSON values visible to Lovable should
    # not leak Python floats. Internal calculation values must stay in audit-only
    # structures, not public rows/budget fields.
    for err in _collect_public_float_errors({"orcamento_sintetico": result.get("orcamento_sintetico"), "composicoes": composicoes}):
        float_errors.append(err)
    family_split_ok = isinstance(composicoes.get('sinapi_like'), dict) and isinstance(composicoes.get('sicro'), dict)
    if not family_split_ok:
        issues.append({'code': 'composition_family_split_missing', 'severity': 'blocking', 'blocks_json_ok': True})
    essential_by_section = {
        'A': ['codigo', 'banco', 'equipamento', 'quantidade', 'utilizacao', 'custo_operacional', 'custo_horario'],
        'B': ['codigo', 'banco', 'mao_obra', 'quantidade', 'salario_hora', 'custo_horario'],
        'C': ['codigo', 'banco', 'material', 'quantidade', 'unidade', 'preco_unitario', 'custo'],
        'D': ['codigo', 'banco', 'atividade_auxiliar', 'quantidade', 'unidade', 'preco_unitario', 'custo'],
        'E': ['insumo', 'banco', 'tempo_fixo', 'codigo', 'quantidade', 'unidade', 'preco_unitario', 'custo'],
        'F': ['insumo', 'banco', 'momento_transporte', 'quantidade', 'unidade', 'custo'],
    }
    for family, collection, key, block in list(_iter_family_blocks(composicoes) or []):
        for group, idx, row in _iter_public_rows_in_block(block):
            for k, v in row.items():
                if isinstance(v, float):
                    float_errors.append({'family': family, 'collection': collection, 'block': key, 'row_group': group, 'row_index': idx, 'field': k, 'value': v})
        if family != 'sicro':
            try:
                from app.parser.math_status import compute_component_math
                math = compute_component_math(block)
            except Exception:
                math = {}
            math_status = str((math or {}).get('status') or '')
            if int((math or {}).get('missing_component_totals') or 0) > 0:
                issues.append({'code': 'sinapi_like_component_math_unclosed', 'severity': 'blocking', 'blocks_json_ok': True, 'collection': collection, 'block': key, 'math_status': math})
            for group, idx, row in _iter_public_rows_in_block(block):
                required = ('und', 'quant', 'valor_unit', 'total')
                missing_public = [field for field in required if row.get(field) in (None, '', [], {})]
                if missing_public and (math_status in {'component_sum_lower_than_principal', 'component_sum_greater_than_principal', 'not_validatable'} or group != 'principal'):
                    issues.append({'code': 'sinapi_like_public_numeric_missing', 'severity': 'blocking', 'blocks_json_ok': True, 'collection': collection, 'block': key, 'row_group': group, 'row_index': idx, 'codigo': row.get('codigo'), 'missing': missing_public})
            continue
        principal = block.get('principal') if isinstance(block.get('principal'), dict) else {}
        if collection == 'principais' and not str(block.get('item') or '').strip():
            issues.append({'code': 'sicro_principal_without_item', 'severity': 'blocking', 'blocks_json_ok': True, 'block': key})
        if collection == 'auxiliares_globais' and str(block.get('item') or '').strip():
            issues.append({'code': 'sicro_auxiliar_with_item', 'severity': 'blocking', 'blocks_json_ok': True, 'block': key})
        secoes = block.get('secoes') if isinstance(block.get('secoes'), dict) else {}
        if not secoes:
            sicro_payload = block.get('sicro') if isinstance(block.get('sicro'), dict) else {}
            secoes = sicro_payload.get('secoes') if isinstance(sicro_payload.get('secoes'), dict) else {}
        forbidden_principal = {'descricao', 'und', 'quant', 'valor_unit', 'total', 'banco_coluna', 'banco_canonico', 'composicoes_auxiliares', 'insumos', 'detalhes', '_cascaded_from', 'sicro_section_totals'}
        leaked_principal = [f for f in forbidden_principal if f in principal]
        if leaked_principal:
            issues.append({'code': 'sicro_principal_generic_alias_leaked', 'severity': 'blocking', 'blocks_json_ok': True, 'block': key, 'fields': leaked_principal})
        leaked_block = [f for f in ('composicoes_auxiliares', 'insumos', 'detalhes', 'sicro', '_cascaded_from', 'sicro_section_totals') if f in block]
        if leaked_block:
            issues.append({'code': 'sicro_block_generic_container_leaked', 'severity': 'blocking', 'blocks_json_ok': True, 'block': key, 'fields': leaked_block})
        for sec, sec_data in (secoes or {}).items():
            rows = sec_data.get('linhas') if isinstance(sec_data, dict) else []
            required = essential_by_section.get(str(sec), [])
            for idx, row in enumerate(rows or []):
                if not isinstance(row, dict):
                    continue
                forbidden_row_keys = {'descricao', 'und', 'quant', 'valor_unit', 'total', 'banco_coluna', 'banco_canonico', 'natureza', 'tipo', 'detalhes', '_cascaded_from', 'sicro_section_totals'}
                leaked_row_keys = [rk for rk in forbidden_row_keys if rk in row]
                if leaked_row_keys:
                    issues.append({'code': 'sicro_section_row_generic_or_cascade_field_leaked', 'severity': 'blocking', 'blocks_json_ok': True, 'block': key, 'section': sec, 'row': idx, 'fields': leaked_row_keys})
                for k, v in row.items():
                    if isinstance(v, float):
                        float_errors.append({'block': key, 'section': sec, 'row': idx, 'field': k, 'value': v})
                missing = [field for field in required if row.get(field) in (None, '', [], {})]
                if missing:
                    sicro_missing.append({'block': key, 'section': sec, 'row': idx, 'missing': missing})
    public_pollution = _public_text_pollution_issues(result)
    issues.extend({'code': 'sicro_public_row_incomplete', 'severity': 'blocking', 'blocks_json_ok': True, **x} for x in sicro_missing[:50])
    issues.extend({'code': 'public_float_leaked', 'severity': 'blocking', 'blocks_json_ok': True, **x} for x in float_errors[:50])
    issues.extend({'severity': 'warning', 'blocks_json_ok': False, **x} for x in public_pollution[:50])
    # Evidence-first public fields: when the final real-flow orchestrator has
    # produced a physical evidence report, unresolved public numeric evidence is
    # blocking.  Do not require this report when no PDF was available; mandatory
    # orchestrator failures handle that separately.
    evidence_doc = result.get('documento_evidencias') if isinstance(result.get('documento_evidencias'), dict) else {}
    ev_report = evidence_doc.get('public_numeric_evidence_report') if isinstance(evidence_doc.get('public_numeric_evidence_report'), dict) else {}
    if ev_report and ev_report.get('attempted', True) and ev_report.get('strict_public_evidence_required'):
        for missing_ev in list(ev_report.get('blocking_missing_evidence') or [])[:50]:
            issues.append({'code': 'public_numeric_without_physical_evidence', 'severity': 'blocking', 'blocks_json_ok': True, **(missing_ev if isinstance(missing_ev, dict) else {'detail': missing_ev})})

    # v61.0.62: keep the final gate aligned with the existing recovery tools.
    # If the physical numeric tail recovery report still has current blocking
    # unresolved rows, surface them as quality issues instead of letting stale
    # correction summaries hide the problem.
    perf = ((result.get('meta') or {}).get('performance') or {}) if isinstance(result.get('meta'), dict) else {}
    for rep_name in ('physical_numeric_tail_recovery', 'physical_numeric_tail_recovery_finalize', 'physical_numeric_tail_recovery_accuracy_flow', 'physical_numeric_tail_recovery_standalone'):
        rep = perf.get(rep_name) if isinstance(perf, dict) else None
        if isinstance(rep, dict):
            for unresolved in list(rep.get('blocking_unresolved') or [])[:50]:
                issues.append({'code': 'physical_numeric_tail_unresolved', 'severity': 'blocking', 'blocks_json_ok': True, 'source_report': rep_name, **(unresolved if isinstance(unresolved, dict) else {'detail': unresolved})})
    corr = result.get('documento_correcao') if isinstance(result.get('documento_correcao'), dict) else {}
    corr_resumo = corr.get('resumo') if isinstance(corr.get('resumo'), dict) else {}
    valid_resumo = ((result.get('validacao') or {}).get('resumo') or {}) if isinstance(result.get('validacao'), dict) else {}
    # v61.0.51: final validation may contain human-review diagnostics from
    # hierarchy/references.  They should not fail the public quality gate when
    # public fields, math fields and closure are already consistent.  The
    # correction document now exposes these as review items instead.
    final_validation_synced = True
    severity_summary = {
        'blocking': sum(1 for issue in issues if str((issue or {}).get('severity') or '') == 'blocking' or (issue or {}).get('blocks_json_ok')),
        'warning': sum(1 for issue in issues if str((issue or {}).get('severity') or '') == 'warning'),
        'info': sum(1 for issue in issues if str((issue or {}).get('severity') or '') == 'info'),
    }
    blocking_issues = [issue for issue in issues if str((issue or {}).get('severity') or '') == 'blocking' or (issue or {}).get('blocks_json_ok')]
    return {
        'version': 'v61.0.75-correction-output-contract-and-review-index',
        'ok': not blocking_issues and not any(i.get('code') in {'public_float_leaked', 'sinapi_like_public_numeric_missing', 'sinapi_like_component_math_unclosed'} for i in issues if isinstance(i, dict)),
        'family_split_ok': family_split_ok,
        'sicro_public_rows_incomplete': sicro_missing[:100],
        'numeric_fidelity_errors': float_errors[:100],
        'public_text_pollution': public_pollution[:100],
        'legacy_fields_leaked': [],
        'final_validation_synced': final_validation_synced,
        'severity_summary': severity_summary,
        'blocking_issue_count': len(blocking_issues),
        'issues': issues[:200],
    }


def _sync_correction_document_with_quality_gate(result: dict) -> None:
    gate = ((result.get('auditoria_final') or {}).get('quality_gate') or {}) if isinstance(result.get('auditoria_final'), dict) else {}
    if not isinstance(gate, dict):
        return
    doc = result.setdefault('documento_correcao', {})
    if not isinstance(doc, dict):
        result['documento_correcao'] = doc = {}
    qissues = list(gate.get('issues') or [])
    if qissues:
        doc['quality_gate'] = gate
        warnings = doc.setdefault('warnings', [])
        if isinstance(warnings, list):
            existing = {json.dumps(w, ensure_ascii=False, sort_keys=True, default=str) for w in warnings if isinstance(w, dict)}
            for issue in qissues:
                entry = {'tipo': 'quality_gate_issue', **(issue if isinstance(issue, dict) else {'message': str(issue)})}
                marker = json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str)
                if marker not in existing:
                    warnings.append(entry); existing.add(marker)
        resumo = doc.setdefault('resumo', {})
        if isinstance(resumo, dict):
            resumo['total_quality_gate_issues'] = len(qissues)
            resumo['quality_gate_ok'] = bool(gate.get('ok'))
            resumo['quality_gate_severity_summary'] = gate.get('severity_summary') or {}
            resumo['quality_gate_blocking_issue_count'] = int(gate.get('blocking_issue_count') or 0)
            # A failed gate is a real final issue even if composition math is clean.
            if not gate.get('ok'):
                resumo['total_registros_com_erro'] = max(int(resumo.get('total_registros_com_erro') or 0), 1)


def refresh_quality_gate_after_repairs(result: dict) -> dict:
    """Recompute the final public quality gate after late repair/closure passes.

    v61.0.51: late browser flows may repair compositions after the initial
    compacting pass.  Reuse the public-field-only quality gate so internal audit
    floats (detalhes.math_status, scores, tolerances, etc.) do not make Lovable
    think the public JSON is invalid.
    """
    if not isinstance(result, dict):
        return {}
    gate = _quality_gate_final(result)
    result.setdefault('auditoria_final', {})['quality_gate'] = gate
    # Remove stale quality-gate issues from previous versions before syncing the
    # current gate.  Keep non-quality warnings intact.
    doc = result.setdefault('documento_correcao', {})
    if isinstance(doc, dict):
        warnings = doc.get('warnings')
        if isinstance(warnings, list):
            doc['warnings'] = [w for w in warnings if not (isinstance(w, dict) and w.get('tipo') == 'quality_gate_issue')]
        if gate.get('ok'):
            if result.get('status') == 'quality_gate_failed':
                result['status'] = 'ok'
            doc.pop('quality_gate', None)
            resumo = doc.setdefault('resumo', {})
            if isinstance(resumo, dict):
                resumo['total_quality_gate_issues'] = 0
                resumo['quality_gate_ok'] = True
                resumo['quality_gate_severity_summary'] = gate.get('severity_summary') or {'blocking': 0, 'warning': 0, 'info': 0}
                resumo['quality_gate_blocking_issue_count'] = 0
                # Do not clear real error counters here; only remove false public
                # float failures caused by stale quality-gate sync.
        else:
            doc['quality_gate'] = gate
    _sync_correction_document_with_quality_gate(result)
    return gate


def prune_runtime_only_fields(result: dict) -> dict:
    composicoes = result.get('composicoes')
    if not isinstance(composicoes, dict):
        return result
    for collection_name in ('principais', 'auxiliares_globais'):
        blocks = composicoes.get(collection_name)
        if not isinstance(blocks, dict):
            continue
        for block_key, block in list(blocks.items()):
            if not isinstance(block, dict):
                continue
            principal = block.get('principal')
            principal_bank = ''
            if isinstance(principal, dict):
                principal_bank = str(principal.get('banco') or principal.get('banco_coluna') or '').upper()
                if _is_sicro_bank(principal_bank):
                    block['principal'] = _normalize_sicro_principal(principal)
                else:
                    _prune_runtime_row_fields(principal)
            detalhes_block = block.get('detalhes')
            sicro_payload = None
            if isinstance(detalhes_block, dict) and isinstance(detalhes_block.get('sicro'), dict):
                sicro_payload = detalhes_block.get('sicro')
            elif isinstance(block.get('sicro'), dict):
                sicro_payload = block.get('sicro')
            if isinstance(sicro_payload, dict):
                normalized_sicro = _normalize_sicro_payload(sicro_payload or {})
                if _is_sicro_bank(principal_bank):
                    # SICRO final output is native: principal + secoes/resumos/validacao.
                    # Do not expose the generic SINAPI-like containers.
                    _apply_sicro_native_public_block(block, sicro_payload)
                else:
                    if isinstance(detalhes_block, dict):
                        detalhes_block['sicro'] = normalized_sicro
            aux_rows = block.get('composicoes_auxiliares')
            if isinstance(aux_rows, list):
                for row in aux_rows:
                    if isinstance(row, dict):
                        _prune_runtime_row_fields(row)
                if not aux_rows:
                    block.pop('composicoes_auxiliares', None)
            insumos = block.get('insumos')
            if isinstance(insumos, list):
                for row in insumos:
                    if isinstance(row, dict):
                        _prune_runtime_row_fields(row)
                if not insumos:
                    block.pop('insumos', None)
            if not block.get('detalhes'):
                block.pop('detalhes', None)
            if block.get('item') in ('', None):
                block.pop('item', None)
            if not block.get('principal') and not block.get('composicoes_auxiliares') and not block.get('insumos'):
                blocks.pop(block_key, None)
        if not blocks:
            composicoes.pop(collection_name, None)
    if isinstance(composicoes.get('aliases_auxiliares'), dict) and not composicoes.get('aliases_auxiliares'):
        composicoes.pop('aliases_auxiliares', None)
    # Public v61.0.23 contract: separate SINAPI-like and SICRO families.  The
    # internal parser still uses the legacy flat model, but the final JSON does
    # not expose that flat mirror.
    result['composicoes'] = _split_composicoes_by_family(composicoes)
    _format_public_budget_tree(result)
    result.setdefault('auditoria_final', {})['quality_gate'] = _quality_gate_final(result)
    meta = result.get('meta')
    if isinstance(meta, dict):
        meta.pop('tipo_enrichment', None)
    result.pop('tipo_manifest', None)
    result.pop('_tipo_support', None)

    # Keep final_result.validacao consistent with the correction document exported to Lovable.
    corr = result.get('documento_correcao')
    corr_resumo = corr.get('resumo') if isinstance(corr, dict) else None
    if isinstance(corr_resumo, dict) and int(corr_resumo.get('total_registros_com_erro') or 0) == 0 and int(corr_resumo.get('total_divergencias_matematicas') or 0) == 0:
        validacao = result.get('validacao')
        if isinstance(validacao, dict):
            validacao['ocorrencias'] = []
            validacao.pop('composicoes_nao_associadas_diretamente', None)
            resumo_v = dict(validacao.get('resumo') or {})
            resumo_v.update({'total_erros': 0, 'tem_erros': False, 'total_ocorrencias_compactadas': 0})
            validacao['resumo'] = resumo_v

    input_md = (meta or {}).get('input_metadata') if isinstance(meta, dict) else None
    if isinstance(input_md, dict) and not input_md.get('metadata_extraida_ia'):
        input_md.pop('metadata_extraida_ia', None)
    if isinstance(input_md, dict) and not input_md.get('document_profile'):
        input_md.pop('document_profile', None)
    # Recompute after validation sync/pruning so the audit reflects the final JSON.
    result.setdefault('auditoria_final', {})['quality_gate'] = _quality_gate_final(result)
    _sync_correction_document_with_quality_gate(result)
    qgate = ((result.get('auditoria_final') or {}).get('quality_gate') or {}) if isinstance(result.get('auditoria_final'), dict) else {}
    corr_resumo = ((result.get('documento_correcao') or {}).get('resumo') or {}) if isinstance(result.get('documento_correcao'), dict) else {}
    if isinstance(qgate, dict) and qgate and not qgate.get('ok', True):
        result['status'] = 'quality_gate_failed'
    elif int(corr_resumo.get('total_registros_com_erro') or 0) > 0:
        result['status'] = 'ok_with_warnings'
    elif result.get('status') not in {'error'}:
        result['status'] = 'ok'
    return result
