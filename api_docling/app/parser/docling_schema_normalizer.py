from __future__ import annotations

import copy
import re
from typing import Any, Dict, Iterable, List, Tuple


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _norm(value: Any) -> str:
    s = _clean(value).lower()
    return (s.replace('ç','c').replace('ã','a').replace('á','a').replace('à','a')
             .replace('â','a').replace('é','e').replace('ê','e').replace('í','i')
             .replace('ó','o').replace('ô','o').replace('õ','o').replace('ú','u'))


def _canonical(raw: Any) -> str:
    s = _norm(raw)
    aliases = {
        'item': 'controle_linha', '1.1': 'controle_linha', '2.1': 'controle_linha',
        'controle': 'controle_linha', 'controle linha': 'controle_linha', 'controle_linha': 'controle_linha',
        'codigo': 'codigo', 'código': 'codigo', 'cod': 'codigo', 'cod.': 'codigo',
        'banco': 'banco', 'fonte': 'fonte',
        'descricao': 'descricao', 'descrição': 'descricao', 'especificacoes dos servicos': 'descricao',
        'tipo': 'tipo', 'und': 'und', 'unidade': 'und', 'quant': 'quant', 'quant.': 'quant',
        'valor unit': 'valor_unit', 'valor unit.': 'valor_unit', 'valor unitario': 'valor_unit', 'valor unitário': 'valor_unit',
        'total': 'total', 'custo parcial': 'custo_parcial', 'custo total': 'custo_total',
        's/ b.d.i': 'custo_unitario_sem_bdi', 'c/ b.d.i': 'custo_unitario_com_bdi',
        'item_agregador': 'item_agregador',
    }
    return aliases.get(s, s.replace(' ', '_'))


def _header_text(header: Dict[str, Any]) -> str:
    # `text` is the historical header label; v60.5.2 adds sample_text/content_text for body samples.
    return _clean(header.get('header_text') or header.get('text') or header.get('header') or '')


def _sample_text(header: Dict[str, Any]) -> str:
    return _clean(header.get('sample_text') or header.get('content_text') or header.get('first_row_text') or '')


def _expected_headers(table_hint: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for raw in list(_as_dict(table_hint).get('observed_headers') or []):
        if not isinstance(raw, dict):
            continue
        can = _canonical(raw.get('canonical') or raw.get('canonical_name') or raw.get('name') or _header_text(raw))
        if not can:
            continue
        item = dict(raw)
        item['canonical'] = can
        item['header_text'] = _header_text(raw)
        sample = _sample_text(raw)
        if sample:
            item['sample_text'] = sample
        out.append(item)
    return out


def _table_hints(payload_tables: Dict[str, Any] | None, family: str) -> Dict[str, Any]:
    tables = _as_dict(payload_tables)
    if family == 'budget':
        return _as_dict(tables.get('budget'))
    if family in {'composition', 'sinapi_like'}:
        return _as_dict(tables.get('composition') or tables.get('compositions'))
    return _as_dict(tables.get(family))


def _columns(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    cols = table.get('column_schema') or table.get('columns') or []
    return [dict(c) for c in cols if isinstance(c, dict)]


def _column_canonical(col: Dict[str, Any]) -> str:
    return _canonical(col.get('canonical_name') or col.get('canonical') or col.get('canonicalName') or col.get('name') or col.get('header_text') or col.get('header') or '')


def _column_header(col: Dict[str, Any]) -> str:
    return _clean(col.get('header_text') or col.get('header') or col.get('text') or '')


def _find_neighbors(expected_order: List[str], available: Iterable[str], missing: str) -> Tuple[str | None, str | None]:
    available_set = set(available)
    try:
        idx = expected_order.index(missing)
    except ValueError:
        return None, None
    left = None; right = None
    for j in range(idx - 1, -1, -1):
        if expected_order[j] in available_set:
            left = expected_order[j]; break
    for j in range(idx + 1, len(expected_order)):
        if expected_order[j] in available_set:
            right = expected_order[j]; break
    return left, right


def _table_family(table: Dict[str, Any]) -> str:
    fam = _clean(table.get('family') or '').lower()
    kind = _clean(table.get('kind') or '').lower()
    tid = _clean(table.get('table_id') or table.get('template_id') or '').lower()
    if fam == 'budget' or kind == 'orcamento_sintetico' or tid.startswith('budget'):
        return 'budget'
    if fam in {'composition', 'sinapi_like'} or 'composicao' in kind or tid.startswith('composition'):
        return 'composition'
    return fam or 'unknown'


def normalize_table_schema(table: Dict[str, Any], payload_tables: Dict[str, Any] | None = None) -> Dict[str, Any]:
    out = copy.deepcopy(table or {})
    family = _table_family(out)
    hints = _table_hints(payload_tables, family)
    expected_headers = _expected_headers(hints)
    if not expected_headers:
        return out

    expected_order = [h['canonical'] for h in expected_headers if h.get('canonical')]
    header_by_can = {h['canonical']: h for h in expected_headers}
    sample_by_can = {c: _sample_text(h) for c, h in header_by_can.items() if _sample_text(h)}
    header_text_by_can = {c: _header_text(h) for c, h in header_by_can.items() if _header_text(h)}

    cols = _columns(out)
    available = [_column_canonical(c) for c in cols if _column_canonical(c)]
    available_set = set(available)
    missing = [c for c in expected_order if c not in available_set]
    anomalies: List[Dict[str, Any]] = []
    synthetic: List[Dict[str, Any]] = []
    sample_words: List[Dict[str, Any]] = []

    # annotate columns with payload samples when canonical matches
    normalized_cols: List[Dict[str, Any]] = []
    for col in cols:
        c = _column_canonical(col)
        if c:
            col.setdefault('canonical_name', c)
            meta = dict(col.get('metadata') or {})
            if sample_by_can.get(c):
                meta.setdefault('payload_sample_text', sample_by_can[c])
            if header_text_by_can.get(c):
                meta.setdefault('payload_header_text', header_text_by_can[c])
            col['metadata'] = meta
        normalized_cols.append(col)

    for miss in missing:
        left, right = _find_neighbors(expected_order, available, miss)
        neighbors = [n for n in (left, right) if n]
        anomaly = {
            'code': 'missing_expected_column',
            'canonical': miss,
            'expected_between': [x for x in (left, right) if x],
            'payload_header_text': header_text_by_can.get(miss, ''),
            'sample_text': sample_by_can.get(miss, ''),
            'severity': 'high' if miss in {'codigo', 'banco', 'descricao'} else 'medium',
        }
        # Fused header: e.g. Docling returns a banco column with header "Código Banco".
        mh = _norm(header_text_by_can.get(miss, miss))
        for col in cols:
            cc = _column_canonical(col)
            if cc not in neighbors:
                continue
            hh = _norm(_column_header(col))
            nh = _norm(header_text_by_can.get(cc, cc))
            if mh and nh and mh in hh and nh in hh and mh != nh:
                anomaly.update({
                    'code': 'fused_header_detected',
                    'canonical_detected': cc,
                    'header_text': _column_header(col),
                    'suspected_missing': [miss],
                    'fusion_between': [miss, cc] if expected_order.index(miss) < expected_order.index(cc) else [cc, miss],
                })
                break
        anomalies.append(anomaly)
        # v61.0.2: missing/refined columns are owned exclusively by the Normalizer API.
        # This parser-side pass only records schema anomalies and payload samples.

    norm_meta = {
        'enabled': True,
        'family': family,
        'expected_order': expected_order,
        'available_columns': available,
        'missing_columns': missing,
        'sample_text_by_canonical': sample_by_can,
        'header_text_by_canonical': header_text_by_can,
        'schema_anomalies': anomalies,
        'synthetic_columns': [],
        'normalizer_sample_words': [],
        'confidence_after_normalization': 0.96 if not anomalies else (0.90 if sample_words else 0.75),
    }
    out['column_schema'] = normalized_cols
    out.setdefault('metadata', {})
    out['metadata'] = {**dict(out.get('metadata') or {}), 'docling_schema_normalization': norm_meta}
    # Top-level mirrors help existing debug UIs and reports.
    out['schema_anomalies'] = anomalies
    out['synthetic_columns'] = []
    out['missing_columns'] = missing
    return out


def _normalize_tables_container(tables_obj: Any, payload_tables: Dict[str, Any] | None) -> Any:
    if isinstance(tables_obj, dict):
        return {k: normalize_table_schema(v, payload_tables) if isinstance(v, dict) else v for k, v in tables_obj.items()}
    if isinstance(tables_obj, list):
        return [normalize_table_schema(v, payload_tables) if isinstance(v, dict) else v for v in tables_obj]
    return tables_obj


def normalize_docling_payload(payload: Dict[str, Any] | None, payload_tables: Dict[str, Any] | None = None) -> Dict[str, Any]:
    data = copy.deepcopy(payload or {})
    if not isinstance(data, dict):
        return {}
    tables_obj = data.get('tables')
    if tables_obj is not None:
        data['tables'] = _normalize_tables_container(tables_obj, payload_tables)
    st = data.get('structured_tables')
    if isinstance(st, dict) and st.get('tables') is not None:
        st = copy.deepcopy(st)
        st['tables'] = _normalize_tables_container(st.get('tables'), payload_tables)
        data['structured_tables'] = st
    # Aggregate summary.
    all_tables = []
    if isinstance(data.get('tables'), dict):
        all_tables.extend([v for v in data['tables'].values() if isinstance(v, dict)])
    elif isinstance(data.get('tables'), list):
        all_tables.extend([v for v in data['tables'] if isinstance(v, dict)])
    summary = {'enabled': True, 'tables_seen': len(all_tables), 'missing_columns': [], 'schema_anomalies': [], 'synthetic_columns': []}
    for t in all_tables:
        md = dict((t.get('metadata') or {}).get('docling_schema_normalization') or {})
        summary['missing_columns'].extend(md.get('missing_columns') or [])
        summary['schema_anomalies'].extend(md.get('schema_anomalies') or [])
        summary['synthetic_columns'].extend(md.get('synthetic_columns') or [])
    data.setdefault('metadata', {})
    data['metadata'] = {**dict(data.get('metadata') or {}), 'docling_schema_normalization': summary}
    return data
