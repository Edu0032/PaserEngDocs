from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

PARAMETROS_MARKERS = {'PARÂMETROS', 'PARAMETROS', 'DATA-BASE', 'BDI DE SERVIÇOS', 'BDI DIFERENCIADO'}
BUDGET_REQUIRED_COLS = {'item_agregador', 'codigo', 'fonte', 'descricao'}
COMPOSITION_REQUIRED_COLS = {'codigo', 'descricao', 'und', 'quant'}


def _upper_texts(values: List[str]) -> List[str]:
    return [str(v or '').strip().upper() for v in values if str(v or '').strip()]


def _header_texts(template: Dict[str, Any]) -> List[str]:
    return _upper_texts([str(col.get('header_text') or '') for col in list(template.get('column_schema') or [])])


def _mapped_col_names(template: Dict[str, Any]) -> set[str]:
    return {
        str(col.get('canonical_name') or '').strip()
        for col in list(template.get('column_schema') or [])
        if str(col.get('canonical_name') or '').strip()
    }


def _col_count(template: Dict[str, Any]) -> int:
    return len(list(template.get('column_schema') or []))


def _page_width_ratio(template: Dict[str, Any]) -> float:
    cols = list(template.get('column_schema') or [])
    x0_vals = [col.get('x0') for col in cols if col.get('x0') is not None]
    x1_vals = [col.get('x1') for col in cols if col.get('x1') is not None]
    if not x0_vals or not x1_vals:
        bbox = list(template.get('bbox') or [])
        if len(bbox) == 4 and bbox[2] > bbox[0]:
            x0_vals = [bbox[0]]
            x1_vals = [bbox[2]]
    if not x0_vals or not x1_vals:
        return 1.0
    leftmost = min(float(x) for x in x0_vals)
    rightmost = max(float(x) for x in x1_vals)
    page_width = 595.0 if rightmost > 1.0 else 1.0
    return max(0.0, min(1.0, (rightmost - leftmost) / page_width))


def _matches_non_table_panel(header_texts: List[str], panel: Dict[str, Any]) -> bool:
    must_contain = _upper_texts(list(panel.get('must_contain_text') or []))
    if not must_contain:
        return False
    matches = 0
    for text in must_contain:
        if any(text in ht for ht in header_texts):
            matches += 1
    return matches >= min(2, len(must_contain))


def score_template(
    template: Dict[str, Any],
    *,
    kind: str,
    non_table_panels: List[Dict[str, Any]] | None = None,
    selection_policy: Dict[str, Any] | None = None,
) -> Tuple[float, str, List[str]]:
    reasons: List[str] = []
    rejection_reasons: List[str] = []
    policy = dict(selection_policy or {})
    header_texts = _header_texts(template)
    mapped_cols = _mapped_col_names(template)
    col_count = _col_count(template)
    base_confidence = float(template.get('confidence') or 0.0)

    for panel in list(non_table_panels or []):
        if _matches_non_table_panel(header_texts, panel):
            rejection_reasons.append(f"template_matches_non_table_panel:{panel.get('label', '?')}")

    for reject_text in list(policy.get('reject_if_contains_text') or []):
        rt = str(reject_text or '').strip().upper()
        if rt and any(rt in ht for ht in header_texts):
            rejection_reasons.append(f'contains_rejected_text:{reject_text}')

    kind_norm = str(kind or '').strip().lower()
    if kind_norm in {'budget', 'orcamento_sintetico'}:
        parametros_hits = sum(1 for m in PARAMETROS_MARKERS if any(m in ht for ht in header_texts))
        if parametros_hits >= 2:
            rejection_reasons.append('contains_parametros_panel_markers')
        has_item = any('ITEM' in ht for ht in header_texts)
        has_codigo = any('CÓDIGO' in ht or 'CODIGO' in ht for ht in header_texts)
        if not (has_item and has_codigo):
            rejection_reasons.append('missing_item_or_codigo_in_budget_template')
        min_cols = int(policy.get('reject_if_col_count_below') or 5)
        if col_count < min_cols:
            rejection_reasons.append(f'too_few_columns:{col_count}<{min_cols}')
        missing = [c for c in BUDGET_REQUIRED_COLS if c not in mapped_cols]
        if len(missing) >= 3:
            rejection_reasons.append(f'too_many_required_cols_missing:{missing}')
    else:
        has_codigo = any('CÓDIGO' in ht or 'CODIGO' in ht or 'CÓDIGO BANCO' in ht or 'CÓDIGO BANCO' in ht for ht in header_texts)
        has_descricao = any('DESCRI' in ht for ht in header_texts)
        if not (has_codigo or has_descricao):
            rejection_reasons.append('missing_codigo_or_descricao_in_composition_template')
        min_cols = int(policy.get('reject_if_col_count_below') or 4)
        if col_count < min_cols:
            rejection_reasons.append(f'too_few_columns:{col_count}<{min_cols}')
        missing = [c for c in COMPOSITION_REQUIRED_COLS if c not in mapped_cols]
        if len(missing) >= 3:
            rejection_reasons.append(f'too_many_required_cols_missing:{missing}')

    required_cols = list(policy.get('reject_if_missing_required_cols') or [])
    if required_cols:
        missing = [c for c in required_cols if c not in mapped_cols]
        if len(missing) > len(required_cols) // 2:
            rejection_reasons.append(f'too_many_policy_required_cols_missing:{missing}')

    min_width = policy.get('reject_if_width_ratio_below')
    if min_width is not None:
        ratio = _page_width_ratio(template)
        if ratio < float(min_width):
            rejection_reasons.append(f'width_ratio_too_low:{ratio:.2f}<{float(min_width):.2f}')

    if rejection_reasons:
        return 0.0, 'rejected', rejection_reasons

    score = base_confidence
    bonus_texts = _upper_texts(list(policy.get('bonus_if_contains_text') or []))
    for t in bonus_texts:
        if any(t in ht for ht in header_texts):
            score += 0.25
    if kind_norm in {'budget', 'orcamento_sintetico'}:
        score += len(BUDGET_REQUIRED_COLS & mapped_cols) * 0.35
        if len(list(template.get('header_rows') or [])) >= 2:
            score += 0.5
            reasons.append('header_rows_ge_2')
        if bool(policy.get('bonus_if_has_grouped_headers')) and list(template.get('grouped_headers') or []):
            score += 1.0
            reasons.append('grouped_headers_detected')
    else:
        score += len(COMPOSITION_REQUIRED_COLS & mapped_cols) * 0.3
    reasons.extend([
        f'col_count:{col_count}',
        f'base_confidence:{base_confidence:.3f}',
        f'final_score:{score:.3f}',
    ])
    return round(score, 3), 'accepted', reasons


def select_best_template(
    templates: List[Dict[str, Any]],
    *,
    kind: str,
    non_table_panels: List[Dict[str, Any]] | None = None,
    selection_policy: Dict[str, Any] | None = None,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    scored: List[Tuple[float, Dict[str, Any]]] = []
    rejected: List[Dict[str, Any]] = []
    scored_info: List[Dict[str, Any]] = []
    for template in templates:
        score, status, reasons = score_template(
            template,
            kind=kind,
            non_table_panels=non_table_panels,
            selection_policy=selection_policy,
        )
        info = {
            'template_id': template.get('template_id') or template.get('table_id'),
            'kind': template.get('kind'),
            'family': template.get('family'),
            'score': score,
            'status': status,
            'reasons': reasons,
        }
        if status == 'rejected':
            rejected.append(info)
        else:
            scored.append((score, template))
        scored_info.append(info)
    if not scored:
        return None, scored_info, rejected
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[0][1], scored_info, rejected
