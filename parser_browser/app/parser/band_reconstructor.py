from __future__ import annotations
from typing import Any, Dict, List, Optional
from app.parser.docling_column_map import DoclingColumnMap, _looks_like_unit as _looks_unit, _looks_monetary, _looks_numeric

STRUCTURAL_ONLY_COLS = {'tipo'}

class ColumnBandMap:
    """Backward-compatible wrapper around v60 DoclingColumnMap."""
    def __init__(self, column_schema: List[Dict[str, Any]], *, include_tipo_in_final_json: bool = False):
        self._map = DoclingColumnMap(column_schema, include_tipo_in_final_json=include_tipo_in_final_json)
        self.bands = [(b.canonical, b.x0, b.x1) for b in self._map.bands]
        self.has_geometry = self._map.has_geometry

    def find_column(self, x_center: float, *, tolerance: float = 5.0) -> Optional[str]:
        return self._map.find_column(float(x_center), float(x_center), tolerance=tolerance)

def is_continuation_line(line_tokens: List[Dict[str, Any]], *, band_map: ColumnBandMap, continuation_policy: Dict[str, Any] | None = None) -> bool:
    if not band_map.has_geometry: return False
    continuation_policy = continuation_policy or {}
    strict_cols = set(continuation_policy.get('strict_columns') or [])
    for token in line_tokens:
        x0=float(token.get('x0') or 0); x1=float(token.get('x1') or x0)
        col=band_map._map.find_column(x0,x1)
        if col in strict_cols: return False
    return True

def reconstruct_continuation(prev_fields: Dict[str, Any], fragment_tokens: List[Dict[str, Any]], *, band_map: ColumnBandMap, continuation_policy: Dict[str, Any] | None = None) -> Dict[str, Any]:
    continuation_policy = continuation_policy or {}
    text_cols=set(continuation_policy.get('text_columns') or ['descricao','banco','fonte','controle_linha'])
    numeric_cols=set(continuation_policy.get('numeric_columns') or ['quant','quantidade'])
    money_cols=set(continuation_policy.get('money_columns') or ['custo_unitario_sem_bdi','custo_unitario_com_bdi','custo_total','custo_parcial','valor_unit','valor_total','total'])
    unit_cols=set(continuation_policy.get('unit_columns') or ['und','unidade'])
    updated=dict(prev_fields)
    for token in fragment_tokens:
        text=str(token.get('text') or '').strip()
        if not text: continue
        x0=float(token.get('x0') or 0); x1=float(token.get('x1') or x0)
        col=band_map._map.find_column(x0,x1)
        if col is None or col in STRUCTURAL_ONLY_COLS: continue
        current=str(updated.get(col) or '').strip()
        if col in text_cols:
            updated[col]=(current+' '+text).strip() if current else text
        elif col in numeric_cols:
            if not current and _looks_numeric(text): updated[col]=text
        elif col in money_cols:
            if not current and _looks_monetary(text): updated[col]=text
        elif col in unit_cols:
            if not current and _looks_unit(text): updated[col]=text
        elif not current:
            updated[col]=text
    return updated
