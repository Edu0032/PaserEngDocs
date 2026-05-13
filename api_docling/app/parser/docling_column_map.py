from __future__ import annotations

import re
import bisect
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from app.parser.column_merge_resolver import build_merge_resolution, looks_like_banco, looks_like_codigo, looks_like_unit, looks_like_number, looks_like_money

KNOWN_UNITS = {'m','m²','m2','m³','m3','kg','un','und','vb','h','hs','l','cj','tb','gl','pç','pc','pr','sc','t','rl','cx','mes','m3xkm','%'}

@dataclass(frozen=True)
class ColumnBand:
    canonical: str
    header: str = ''
    physical_index: int | None = None
    x0: float = 0.0
    x1: float = 0.0
    width: float = 0.0
    geometry_confidence: float | None = None
    structural_only: bool = False
    ignore_in_domain: bool = False
    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2.0

def _clean(text: Any) -> str:
    return re.sub(r'\s+', ' ', str(text or '').strip())

def _canonical(raw: Any) -> str:
    s = _clean(raw).lower()
    s = (s.replace('ç','c').replace('ã','a').replace('á','a').replace('à','a').replace('é','e').replace('ê','e').replace('í','i').replace('ó','o').replace('ô','o').replace('ú','u'))
    aliases = {
        'item':'controle_linha','controle':'controle_linha','controle linha':'controle_linha','linha':'controle_linha',
        'codigo':'codigo','cod':'codigo','cód':'codigo','banco':'banco','fonte':'banco',
        'descricao':'descricao','descrição':'descricao','especificacoes dos servicos':'descricao','especificações dos serviços':'descricao',
        'tipo':'tipo','und':'und','unid':'und','unidade':'und','quant':'quant','quant.':'quant','quantidade':'quant',
        'valor unit':'valor_unit','valor unit.':'valor_unit','valor unitario':'valor_unit','valor unitário':'valor_unit',
        'total':'total','valor total':'total','item_agregador':'item_agregador',
        'custo_unitario_sem_bdi':'custo_unitario_sem_bdi','custo_unitario_com_bdi':'custo_unitario_com_bdi','custo_parcial':'custo_parcial','custo_total':'custo_total',
    }
    return aliases.get(s, s.replace(' ', '_'))

def _tables_from_context(context: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    st = dict((context or {}).get('structured_tables') or {})
    raw_tables = st.get('tables')
    if isinstance(raw_tables, dict):
        return [dict(v) for v in raw_tables.values() if isinstance(v, dict)]
    if isinstance(raw_tables, list):
        return [dict(v) for v in raw_tables if isinstance(v, dict)]
    maybe = [v for v in st.values() if isinstance(v, dict) and (v.get('columns') or v.get('column_schema'))]
    return [dict(v) for v in maybe]

class DoclingColumnMap:
    """Column geometry map derived from Docling. v60 rules: controle_linha is preserved; tipo is optional and ignored by default."""
    control_columns = {'controle_linha'}
    text_columns = {'controle_linha','banco','descricao'}
    strict_columns = {'codigo'}
    unit_columns = {'und'}
    numeric_columns = {'quant'}
    money_columns = {'valor_unit','total','custo_unitario_sem_bdi','custo_unitario_com_bdi','custo_parcial','custo_total'}

    def __init__(self, column_schema: Iterable[Dict[str, Any]] | None = None, *, include_tipo_in_final_json: bool = False, family: str = 'composition', table_id: str = ''):
        self.include_tipo_in_final_json = bool(include_tipo_in_final_json)
        self.family = family
        self.table_id = table_id
        self.bands: List[ColumnBand] = []
        self._normalizer_sample_words: List[Dict[str, Any]] = []
        for col in list(column_schema or []):
            if not isinstance(col, dict):
                continue
            meta = dict(col.get('metadata') or {})
            canonical = _canonical(col.get('canonical_name') or col.get('canonical') or col.get('canonicalName') or col.get('name') or '')
            header = _clean(col.get('header_text') or col.get('header') or canonical)
            # v61: Normalizer-refined geometry overrides raw/effective Docling bounds.
            x0 = col.get('normalizer_x0', meta.get('normalizer_x0', meta.get('effective_x0', col.get('x0'))))
            x1 = col.get('normalizer_x1', meta.get('normalizer_x1', meta.get('effective_x1', col.get('x1'))))
            if not canonical or x0 is None or x1 is None:
                # Synthetic classification/logical-only columns have no trustworthy geometry.
                # Keep their payload sample as evidence for the merged-column resolver.
                mode = str(col.get('mode') or meta.get('mode') or '').lower()
                if canonical and (bool(meta.get('classification_only')) or mode == 'classification_only' or col.get('physical_index') is None):
                    sample = meta.get('payload_sample_text') or col.get('sample_text') or col.get('content_text')
                    for source in list(meta.get('expected_between') or col.get('expected_between') or []):
                        if sample and source:
                            self._normalizer_sample_words.append({'source_column': str(source), 'text': sample, 'expected_column': canonical})
                continue
            try:
                x0f = float(x0); x1f = float(x1)
            except Exception:
                continue
            if x1f < x0f:
                x0f, x1f = x1f, x0f
            try:
                pidx = int(col.get('physical_index')) if col.get('physical_index') is not None else None
            except Exception:
                pidx = None
            width = float(col.get('normalizer_width', meta.get('normalizer_width', meta.get('effective_width', col.get('width', x1f - x0f)))) or (x1f - x0f))
            structural_only = (bool(meta.get('structural_only')) and not (canonical == 'tipo' and self.include_tipo_in_final_json)) or (canonical == 'tipo' and not self.include_tipo_in_final_json)
            ignore_in_domain = (bool(meta.get('ignore_in_domain')) and not (canonical == 'tipo' and self.include_tipo_in_final_json)) or (canonical == 'tipo' and not self.include_tipo_in_final_json)
            self.bands.append(ColumnBand(canonical, header, pidx, x0f, x1f, width, meta.get('geometry_confidence', col.get('geometry_confidence', col.get('confidence'))), structural_only, ignore_in_domain))
        original_columns = {b.canonical for b in self.bands}
        self.expected_order = self._default_expected_order(str(self.family or 'composition').lower())
        self.merge_resolution = build_merge_resolution(
            [b.canonical for b in self.bands],
            self.expected_order,
            sample_words=self._normalizer_sample_words,
            known_banks=None,
        )
        self.synthetic_columns: List[str] = list(self.merge_resolution.missing_columns)
        self.bands.sort(key=lambda b: ((b.physical_index if b.physical_index is not None else 10000), b.x0, b.canonical))
        self._bands_by_x0 = sorted(self.bands, key=lambda b: (b.x0, b.x1, b.canonical))
        self._band_x0s = [b.x0 for b in self._bands_by_x0]
        self.has_geometry = bool(self.bands)
        self.available_columns = [b.canonical for b in self.bands]
        self.effective_columns = list(dict.fromkeys(self.available_columns + list(self.merge_resolution.missing_columns)))
        self.missing_core = [c for c in ['controle_linha','codigo','banco','descricao','und','quant','valor_unit','total'] if c not in original_columns]
        self.merged_columns_detected = list(self.merge_resolution.detected)


    @staticmethod
    def _default_expected_order(family: str) -> List[str]:
        if family == 'budget':
            return ['item_agregador','codigo','fonte','descricao','und','quant','custo_unitario_sem_bdi','custo_unitario_com_bdi','custo_parcial','custo_total']
        if family == 'sicro':
            return ['controle_linha','codigo','banco','descricao','und','quant','valor_unit','total']
        return ['controle_linha','codigo','banco','descricao','tipo','und','quant','valor_unit','total']

    @classmethod
    def empty(cls) -> 'DoclingColumnMap':
        return cls([])

    @staticmethod
    def include_tipo_from_options(config: Dict[str, Any] | None = None, context: Dict[str, Any] | None = None) -> bool:
        cfg = config or {}; ctx = context or {}
        for holder in (cfg.get('output_options'), cfg.get('output'), cfg.get('performance'), cfg.get('parser_options'), ctx.get('output_options'), ctx.get('parser_options')):
            if isinstance(holder, dict) and 'include_tipo_in_final_json' in holder:
                return bool(holder.get('include_tipo_in_final_json'))
        return False

    @classmethod
    def from_context(cls, context: Dict[str, Any] | None, *, config: Dict[str, Any] | None = None, family: str = 'composition') -> 'DoclingColumnMap':
        include_tipo = cls.include_tipo_from_options(config=config, context=context)
        requested = str(family or 'composition').lower()
        chosen: Dict[str, Any] | None = None
        for t in _tables_from_context(context):
            fam = str(t.get('family') or '').lower(); kind = str(t.get('kind') or '').lower(); tid = str(t.get('table_id') or t.get('template_id') or '').lower()
            if requested == 'budget' and (fam == 'budget' or kind == 'orcamento_sintetico' or tid.startswith('budget')):
                chosen = t; break
            if requested == 'composition' and (fam in {'composition','sinapi_like'} or kind in {'composicao_sinapi_like','composition'} or tid.startswith('composition')):
                chosen = t; break
            if requested == 'sicro' and (fam == 'sicro' or kind == 'composicao_sicro'):
                chosen = t; break
        if chosen is None:
            return cls.empty()
        cols = list(chosen.get('column_schema') or chosen.get('columns') or [])
        for col in list(chosen.get('ignored_columns') or []):
            if isinstance(col, dict):
                c = dict(col); meta = dict(c.get('metadata') or {})
                meta.setdefault('ignore_in_domain', True); meta.setdefault('structural_only', True)
                c['metadata'] = meta; cols.append(c)
        return cls(cols, include_tipo_in_final_json=include_tipo, family=requested, table_id=str(chosen.get('table_id') or chosen.get('template_id') or ''))

    def find_column(self, x0: float, x1: float | None = None, *, mode: str = 'domain', tolerance: float = 4.0) -> Optional[str]:
        if not self.bands:
            return None
        x1v = x0 if x1 is None else x1
        xc = (float(x0) + float(x1v)) / 2.0
        idx = bisect.bisect_right(self._band_x0s, xc + tolerance)
        start = max(0, idx - 4)
        stop = min(len(self._bands_by_x0), idx + 3)
        candidates = self._bands_by_x0[start:stop]
        matches = [b for b in candidates if b.x0 <= xc <= b.x1]
        if not matches:
            matches = [b for b in candidates if (b.x0 - tolerance) <= xc <= (b.x1 + tolerance)]
        if not matches:
            matches = [b for b in self.bands if (b.x0 - tolerance) <= xc <= (b.x1 + tolerance)]
        if not matches:
            return None
        band = sorted(matches, key=lambda b: (abs(b.center - xc), b.width))[0]
        if mode == 'raw':
            return band.canonical
        if band.canonical == 'tipo' and not self.include_tipo_in_final_json and mode == 'domain':
            return None
        if band.ignore_in_domain and mode == 'domain':
            return None
        return band.canonical

    def assign_word(self, word: Dict[str, Any], *, mode: str = 'domain') -> Optional[str]:
        try:
            x0 = float(word.get('x0') or 0); x1 = float(word.get('x1') if word.get('x1') is not None else x0)
        except Exception:
            return None
        source = self.find_column(x0, x1, mode='raw')
        if not source:
            return None
        text = word.get('text', '')
        # General merged-column resolver. Example: if Docling returned only a
        # banco band but codigo is an expected adjacent column, a token like
        # "93207" is routed to codigo while "SINAPI" stays in banco.
        routed = self.merge_resolution.classify(source, text)
        canonical = routed or source
        if canonical == 'tipo' and not self.include_tipo_in_final_json and mode == 'domain':
            return None
        if mode == 'domain':
            for band in self.bands:
                if band.canonical == canonical and band.ignore_in_domain:
                    return None
        return canonical

    def is_excluded(self, canonical: str, *, mode: str = 'domain') -> bool:
        c = _canonical(canonical)
        return c == 'tipo' and not self.include_tipo_in_final_json and mode == 'domain'

    def validate_field(self, canonical: str, text: str) -> bool:
        c = _canonical(canonical); s = _clean(text)
        if not s: return False
        if c in self.unit_columns: return _looks_like_unit(s)
        if c in self.numeric_columns: return _looks_numeric(s)
        if c in self.money_columns: return _looks_monetary(s)
        return True

    def header_layout(self) -> Dict[str, Any]:
        if not self.bands: return {}
        columns=[]
        for idx,b in enumerate(self.bands):
            prev=self.bands[idx-1] if idx>0 else None; nxt=self.bands[idx+1] if idx+1<len(self.bands) else None
            columns.append({'key':b.canonical,'x':b.x0,'left':((prev.x1+b.x0)/2.0 if prev else -1e9),'right':((b.x1+nxt.x0)/2.0 if nxt else None),'x0':b.x0,'x1':b.x1,'header':b.header})
        first=self.bands[0]
        item_header = first.header if first.canonical == 'controle_linha' and re.fullmatch(r'\d+(?:\.\d+)*', first.header or '') else ''
        layout={'line_index':0,'item_header':item_header,'label_cutoff':max(0.0, first.x0-12.0),'columns':columns,'x_positions':{b.canonical:b.x0 for b in self.bands},'docling_column_map':True}
        for b in self.bands:
            layout['x_'+('valor' if b.canonical=='valor_unit' else b.canonical)] = b.x0
        return layout

def _looks_numeric(text: str) -> bool:
    return looks_like_number(text)
def _looks_monetary(text: str) -> bool:
    return looks_like_money(text)
def _looks_like_unit(text: str) -> bool:
    return looks_like_unit(text)
