from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple
import re

from app.core.schemas import Composicoes, OrcamentoItem, OrcamentoSintetico
from app.parser.unit_resolution import normalize_unit, looks_like_dimension_context
from app.parser.broken_line_recovery import pollution_reason, similarity


def _iter_leaf_items(nodes: Iterable[OrcamentoItem]) -> Iterable[OrcamentoItem]:
    for node in nodes or []:
        filhos = getattr(node, 'filhos', None) or []
        if str(getattr(node, 'tipo', '')).lower() == 'item':
            yield node
        if filhos:
            yield from _iter_leaf_items(filhos)


def _norm_text(text: Any) -> str:
    return ' '.join(str(text or '').replace('\xa0', ' ').split()).strip()


def _canon_bank(value: Any) -> str:
    s = _norm_text(value).upper().replace(' ', '')
    if s in {'SICRO', 'SICRO2', 'SICRO3', 'DNIT'}:
        return 'SICRO'
    if s in {'SINAPI', 'CAIXA'}:
        return 'SINAPI'
    if s in {'PROPRIO', 'PRÓPRIO', 'ANP'}:
        return 'PRÓPRIO'
    return s


def _norm_code(value: Any) -> str:
    # Preserve / and - in codes; remove only whitespace and uppercase.
    return _norm_text(value).upper().replace(' ', '')


def _looks_truncated(text: str) -> bool:
    s = _norm_text(text)
    if not s:
        return False
    if len(s) < 40:
        return True
    if re.search(r'\b\(PIGMENTADA\)$', s):
        return True
    if s.endswith(')') and 'AF_' not in s and len(s) < 80:
        return True
    if s.endswith('OU EQUIV.)'):
        return True
    if s.endswith('(1 MÓDULO)'):
        return True
    return False


def _comp_index(comp: Composicoes) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for coll in (comp.principais or {}, comp.auxiliares_globais or {}):
        for key, block in coll.items():
            principal = getattr(block, 'principal', None)
            if principal is None:
                continue
            codigo = _norm_code(getattr(principal, 'codigo', '') or '')
            banco = _canon_bank(getattr(principal, 'banco', '') or '')
            if not codigo or not banco:
                continue
            out[f'{codigo}|{banco}'] = {
                'codigo': codigo,
                'banco': banco,
                'descricao': str(getattr(principal, 'descricao', '') or '').strip(),
                'und': str(getattr(principal, 'und', '') or '').strip(),
                'pagina_inicio': getattr(block, 'pagina_inicio', None),
                'pagina_fim': getattr(block, 'pagina_fim', None),
            }
    return out




def _budget_index(orcamento: OrcamentoSintetico) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for item in _iter_leaf_items(orcamento.itens_raiz):
        codigo = _norm_code(getattr(item, 'codigo', '') or '')
        banco = _canon_bank(getattr(item, 'fonte', '') or '')
        if not codigo or not banco:
            continue
        key = f'{codigo}|{banco}'
        desc = str(getattr(item, 'especificacao', '') or '').strip()
        # Keep the strongest budget evidence per code/bank. The budget may contain
        # the same code in multiple items with contextual suffixes; do not collapse
        # different complete descriptions automatically, but keep the longest clean
        # one for repairing a clearly truncated/empty composition principal.
        cur = out.get(key)
        if not cur or len(_norm_text(desc)) > len(_norm_text(cur.get('descricao'))):
            out[key] = {
                'codigo': codigo,
                'banco': banco,
                'descricao': desc,
                'und': str(getattr(item, 'und', '') or '').strip(),
                'item': getattr(item, 'item', ''),
            }
    return out


def _safe_description_candidate(text: Any) -> bool:
    desc = _norm_text(text)
    return bool(desc and not pollution_reason(desc) and not desc.startswith('-'))


def _should_cross_patch(current: str, candidate: str) -> bool:
    current = _norm_text(current)
    candidate = _norm_text(candidate)
    if not _safe_description_candidate(candidate):
        return False
    if not current:
        return len(candidate) >= 8
    if pollution_reason(current):
        return True
    if _norm_text(current).upper() == _norm_text(candidate).upper():
        return False
    if _looks_truncated(current) and len(candidate) > len(current) + 5:
        return True
    # Cross-table repair is allowed only when the candidate clearly contains the
    # current truncated text or is very similar. It is deliberately conservative.
    sim = similarity(current, candidate)
    return bool(len(candidate) > len(current) + 12 and (_norm_text(current).upper() in _norm_text(candidate).upper() or sim >= 0.78))


def _reconcile_compositions_against_budget(comp: Composicoes, budget_idx: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    changes: List[Dict[str, Any]] = []
    ocorrencias: List[Dict[str, Any]] = []
    for collection_name, blocks in (("principais", comp.principais or {}), ("auxiliares_globais", comp.auxiliares_globais or {})):
        for block_key, block in blocks.items():
            principal = getattr(block, 'principal', None)
            if principal is None:
                continue
            codigo = _norm_code(getattr(principal, 'codigo', '') or '')
            banco = _canon_bank(getattr(principal, 'banco', '') or '')
            key = f'{codigo}|{banco}' if codigo and banco else ''
            ref = budget_idx.get(key)
            if not ref:
                continue
            current_desc = str(getattr(principal, 'descricao', '') or '').strip()
            ref_desc = str(ref.get('descricao') or '').strip()
            if _should_cross_patch(current_desc, ref_desc):
                before = current_desc
                principal.descricao = ref_desc
                change = {
                    'tipo': 'composicao_descricao_reconciliada_orcamento',
                    'colecao': collection_name,
                    'chave': block_key,
                    'codigo': codigo,
                    'banco': banco,
                    'antes': before,
                    'depois': ref_desc,
                    'item_orcamento': ref.get('item'),
                }
                changes.append(change)
                ocorrencias.append({
                    'codigo': 'composicao_descricao_reconciliada_orcamento',
                    'severidade': 'info',
                    'categoria': 'composicoes',
                    'mensagem': f'Descrição da composição refinada usando orçamento sintético para {key}.',
                    'etapa': 'cross_table_reconcile_first_pass',
                    'ref_id': key,
                    'evidencia': {'antes': before, 'depois': ref_desc, 'item_orcamento': ref.get('item')},
                })
            # Unit only fills missing/suspicious principal unit; it never overwrites a valid unit.
            current_unit = str(getattr(principal, 'und', '') or '').strip()
            ref_unit = str(ref.get('und') or '').strip()
            if ref_unit and not current_unit:
                principal.und = ref_unit
                changes.append({'tipo': 'composicao_unidade_reconciliada_orcamento', 'colecao': collection_name, 'chave': block_key, 'codigo': codigo, 'banco': banco, 'antes': current_unit, 'depois': ref_unit})
    return changes, ocorrencias


def reconcile_budget_against_compositions(orcamento: OrcamentoSintetico, comp: Composicoes) -> Tuple[OrcamentoSintetico, List[Dict[str, Any]], List[Dict[str, Any]]]:
    idx = _comp_index(comp)
    budget_idx = _budget_index(orcamento)
    changes: List[Dict[str, Any]] = []
    ocorrencias: List[Dict[str, Any]] = []
    for item in _iter_leaf_items(orcamento.itens_raiz):
        codigo = _norm_code(getattr(item, 'codigo', '') or '')
        banco = _canon_bank(getattr(item, 'fonte', '') or '')
        key = f'{codigo}|{banco}'
        ref = idx.get(key)
        if not ref:
            continue
        current_unit = str(getattr(item, 'und', '') or '').strip()
        current_desc = str(getattr(item, 'especificacao', '') or '').strip()
        ref_unit = str(ref.get('und') or '').strip()
        ref_desc = str(ref.get('descricao') or '').strip()

        current_norm = normalize_unit(current_unit)
        ref_norm = normalize_unit(ref_unit)
        suspicious_unit = current_norm in {'CM', 'MM'} or (looks_like_dimension_context(current_desc) and current_norm in {'CM', 'MM', ''})
        if ref_norm and ref_norm != current_norm and suspicious_unit:
            item.und = ref_unit
            change = {
                'tipo': 'orcamento_unidade_reconciliada_composicao',
                'item': item.item,
                'codigo': codigo,
                'banco': banco,
                'antes': current_unit,
                'depois': ref_unit,
                'pagina_inicio': ref.get('pagina_inicio'),
                'pagina_fim': ref.get('pagina_fim'),
            }
            changes.append(change)
            ocorrencias.append({
                'codigo': 'orcamento_unidade_reconciliada_composicao',
                'severidade': 'info',
                'categoria': 'orcamento',
                'mensagem': f'Unidade reconciliada com a composição analítica para {item.item} ({codigo}|{banco}).',
                'etapa': 'merge',
                'item': item.item,
                'ref_id': key,
                'pagina_inicio': ref.get('pagina_inicio'),
                'pagina_fim': ref.get('pagina_fim'),
                'evidencia': {'antes': current_unit, 'depois': ref_unit},
            })
        if ref_desc and (_looks_truncated(current_desc) or suspicious_unit):
            if len(_norm_text(ref_desc)) > len(_norm_text(current_desc)) + 8:
                before = current_desc
                item.especificacao = ref_desc
                change = {
                    'tipo': 'orcamento_descricao_reconciliada_composicao',
                    'item': item.item,
                    'codigo': codigo,
                    'banco': banco,
                    'antes': before,
                    'depois': ref_desc,
                    'pagina_inicio': ref.get('pagina_inicio'),
                    'pagina_fim': ref.get('pagina_fim'),
                }
                changes.append(change)
                ocorrencias.append({
                    'codigo': 'orcamento_descricao_reconciliada_composicao',
                    'severidade': 'info',
                    'categoria': 'orcamento',
                    'mensagem': f'Descrição do orçamento refinada usando a composição analítica para {item.item} ({codigo}|{banco}).',
                    'etapa': 'merge',
                    'item': item.item,
                    'ref_id': key,
                    'pagina_inicio': ref.get('pagina_inicio'),
                    'pagina_fim': ref.get('pagina_fim'),
                })
    comp_changes, comp_occurrences = _reconcile_compositions_against_budget(comp, budget_idx)
    changes.extend(comp_changes)
    ocorrencias.extend(comp_occurrences)
    return orcamento, changes, ocorrencias
