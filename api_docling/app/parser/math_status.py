from __future__ import annotations
from typing import Any, Dict, Iterable, List

def as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict): return dict(value)
    if hasattr(value, 'model_dump'):
        try: return dict(value.model_dump(mode='python'))
        except TypeError: return dict(value.model_dump())
    if hasattr(value, 'dict'): return dict(value.dict())
    return {}

def as_float(value: Any) -> float | None:
    if value in (None, ''): return None
    if isinstance(value, (int, float)): return float(value)
    text = str(value).strip().replace('R$', '').replace(' ', '')
    if not text: return None
    if ',' in text: text = text.replace('.', '').replace(',', '.')
    try: return float(text)
    except Exception: return None

def line_total_or_fallback(row: Any) -> float | None:
    data = as_dict(row)
    total = as_float(data.get('total'))
    if total is not None: return total
    quant = as_float(data.get('quant')); unit = as_float(data.get('valor_unit'))
    return round(quant * unit, 6) if quant is not None and unit is not None else None

def normalize_text(value: Any) -> str:
    return ' '.join(str(value or '').replace('\u00a0',' ').split()).strip()

def norm_lower(value: Any) -> str:
    import unicodedata
    text = normalize_text(value).lower()
    return ''.join(ch for ch in unicodedata.normalize('NFKD', text) if not unicodedata.combining(ch))

def is_summary_row(row: Any, summary_markers: Iterable[str] | None = None) -> bool:
    data = as_dict(row)
    hay = norm_lower(' '.join([str(data.get('natureza') or ''), str(data.get('codigo') or ''), str(data.get('banco') or ''), str(data.get('descricao') or '')]))
    markers = [m for m in (summary_markers or []) if str(m or '').strip()] or ['MO sem LS', 'LS =>', 'MO com LS', 'Valor do BDI', 'Valor com BDI']
    return any(norm_lower(m) and norm_lower(m) in hay for m in markers)

def is_sicro_special_block(block: Any) -> bool:
    data = as_dict(block); principal = as_dict(data.get('principal')); detalhes = as_dict(data.get('detalhes'))
    if 'sicro' in norm_lower(principal.get('banco')): return True
    if isinstance(detalhes.get('sicro'), dict) and detalhes.get('sicro'): return True
    secoes = as_dict(as_dict(detalhes.get('sicro')).get('secoes')) if isinstance(detalhes.get('sicro'), dict) else {}
    return any(str(k).upper() in {'A','B','C','D','E','F'} for k in secoes)

def compute_component_math(block: Any, *, tolerance_abs: float = 0.05, tolerance_rel: float = 0.001, summary_markers: Iterable[str] | None = None) -> Dict[str, Any]:
    data = as_dict(block); principal = as_dict(data.get('principal'))
    principal_total = line_total_or_fallback(principal)
    rows = list(data.get('composicoes_auxiliares') or []) + list(data.get('insumos') or [])
    summary_rows: List[Dict[str, Any]] = []; component_rows: List[Any] = []
    for row in rows:
        (summary_rows if is_summary_row(row, summary_markers) else component_rows).append(row if not is_summary_row(row, summary_markers) else as_dict(row))
    vals = [line_total_or_fallback(r) for r in component_rows]
    known = [v for v in vals if v is not None]
    component_sum = round(sum(known), 6)
    missing = len([v for v in vals if v is None])
    tolerance = max(tolerance_abs, abs(float(principal_total or 0)) * tolerance_rel)
    if is_sicro_special_block(block):
        return {'status':'sicro_special_case','strict_sum_validation':False,'principal_total':principal_total,'component_sum':component_sum,'delta':None if principal_total is None else round(float(principal_total)-component_sum,6),'tolerance':round(tolerance,6),'component_rows_count':len(component_rows),'summary_rows_ignored':len(summary_rows),'missing_component_totals':missing}
    if principal_total is None:
        return {'status':'not_validatable','reason':'principal_total_missing','principal_total':None,'component_sum':component_sum,'delta':None,'tolerance':round(tolerance,6),'component_rows_count':len(component_rows),'summary_rows_ignored':len(summary_rows),'missing_component_totals':missing}
    if not component_rows:
        return {'status':'not_validatable','reason':'no_component_rows','principal_total':principal_total,'component_sum':component_sum,'delta':round(float(principal_total)-component_sum,6),'tolerance':round(tolerance,6),'component_rows_count':0,'summary_rows_ignored':len(summary_rows),'missing_component_totals':missing}
    delta = round(float(principal_total)-component_sum, 6)
    if abs(delta) <= tolerance: status = 'ok' if abs(delta) <= tolerance_abs else 'ok_with_rounding'
    elif component_sum < float(principal_total): status = 'component_sum_lower_than_principal'
    else: status = 'component_sum_greater_than_principal'
    return {'status':status,'strict_sum_validation':True,'principal_total':principal_total,'component_sum':component_sum,'delta':delta,'tolerance':round(tolerance,6),'component_rows_count':len(component_rows),'summary_rows_ignored':len(summary_rows),'missing_component_totals':missing}

def math_status_is_error(status: Dict[str, Any]) -> bool:
    return str((status or {}).get('status') or '') in {'component_sum_lower_than_principal','component_sum_greater_than_principal'}
