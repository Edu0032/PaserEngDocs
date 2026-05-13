from __future__ import annotations
import re
from typing import Any, Dict

def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()

def _norm(value: Any) -> str:
    s = _clean(value).upper()
    accents = str.maketrans({'Á':'A','À':'A','Â':'A','Ã':'A','É':'E','Ê':'E','Í':'I','Ó':'O','Ô':'O','Õ':'O','Ú':'U','Ç':'C'})
    return s.translate(accents)

SECTION_HEADERS = {
    'A': ('EQUIP', 'EQUIPAMENTOS'),
    'B': ('MAO DE OBRA', 'MÃO DE OBRA'),
    'C': ('MATERIAL',),
    'D': ('ATIVIDADES AUXILIARES',),
    'E': ('TEMPO FIXO', 'TEMPOS FIXOS'),
    'F': ('MOMENTO DE TRANSPORTE', 'DMT', 'LN RP P'),
}
SECTION_COLUMNS = {
    'A': ['controle_linha','codigo','banco','equipamento','quantidade','utilizacao.operativa','utilizacao.improdutiva','custo_operacional.operativa','custo_operacional.improdutiva','custo_horario'],
    'B': ['controle_linha','codigo','banco','mao_obra','quantidade','salario_hora','custo_horario'],
    'C': ['controle_linha','banco','codigo','material','quantidade','unidade','preco_unitario','custo_horario'],
    'D': ['controle_linha','banco','codigo','atividade_auxiliar','quantidade','unidade','preco_unitario','custo_horario'],
    'E': ['controle_linha','banco','insumo','tempo_fixo','codigo','quantidade','unidade','preco_unitario','custo_horario'],
    'F': ['controle_linha','banco','insumo','momento_transporte','quantidade','unidade','dmt.LN','dmt.RP','dmt.P','custo_horario'],
}

def _line_words_bbox(line: Dict[str, Any]) -> Dict[str, float] | None:
    words = [w for w in (line.get('words') or []) if isinstance(w, dict)]
    if not words:
        return None
    try:
        return {
            'x0': round(min(float(w.get('x0', 0)) for w in words), 3),
            'x1': round(max(float(w.get('x1', 0)) for w in words), 3),
            'y0': round(min(float(w.get('y0', 0)) for w in words), 3),
            'y1': round(max(float(w.get('y1', 0)) for w in words), 3),
        }
    except Exception:
        return None

def _detect_section(text: str) -> str:
    n = _norm(text)
    m = re.match(r'^([ABCDEF])\b', n)
    if m:
        return m.group(1)
    for sec, anchors in SECTION_HEADERS.items():
        if any(anchor in n for anchor in anchors):
            return sec
    return ''

def build_sicro_section_maps(pages: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    maps: Dict[str, Any] = {}
    for local_page, pdata in sorted((pages or {}).items()):
        for line in list(pdata.get('lines') or []):
            text = _clean(line.get('text'))
            sec = _detect_section(text)
            if not sec:
                continue
            maps.setdefault(sec, {
                'section': sec,
                'local_page': local_page,
                'header_text': text,
                'header_bbox': _line_words_bbox(line) or {},
                'columns': [{'canonical': c, 'source': 'sicro_default_section_schema'} for c in SECTION_COLUMNS[sec]],
                'confidence': 0.72,
                'source': 'normalizer_sicro_section_map',
            })
    return maps
