from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable

from app.config.knowledge_base import list_units
from app.core.schemas import Composicoes, OrcamentoSintetico

VERSION = 'v61.0.75-correction-output-contract-and-review-index'


def _clean(value: Any) -> str:
    return ' '.join(str(value or '').replace('\xa0', ' ').split()).strip()


def _canon_bank(value: Any) -> str:
    s = _clean(value).upper().replace(' ', '')
    if s in {'SICRO', 'SICRO2', 'SICRO3', 'DNIT'}:
        return 'SICRO'
    if s in {'SINAPI', 'CAIXA'}:
        return 'SINAPI'
    if s in {'PROPRIO', 'PRÓPRIO', 'ANP'}:
        return 'PRÓPRIO'
    return s


def _is_sicro(value: Any) -> bool:
    return _canon_bank(value) == 'SICRO'


def _known_units(config: dict | None) -> set[str]:
    out: set[str] = set()
    for u in list_units(config or {}):
        if not isinstance(u, dict):
            continue
        vals = [u.get('canonical'), *(u.get('aliases') or [])]
        for v in vals:
            s = _clean(v).upper().replace(' ', '')
            if s:
                out.add(s)
    return out


def _walk_budget_items(nodes: Iterable[Any]):
    for node in nodes or []:
        yield node
        filhos = getattr(node, 'filhos', None) if not isinstance(node, dict) else node.get('filhos')
        yield from _walk_budget_items(filhos or [])


def _iter_blocks(comp: Composicoes):
    for collection, blocks in (('principais', comp.principais), ('auxiliares_globais', comp.auxiliares_globais)):
        for key, block in (blocks or {}).items():
            yield collection, key, block


def _iter_lines(block: Any):
    principal = getattr(block, 'principal', None)
    if principal is not None:
        yield 'principal', principal
    for r in getattr(block, 'composicoes_auxiliares', []) or []:
        yield 'composicao_auxiliar', r
    for r in getattr(block, 'insumos', []) or []:
        yield 'insumo', r


def _as_float_if_numeric(value: Any) -> float | None:
    try:
        if value in (None, ''):
            return None
        return float(value)
    except Exception:
        return None


def _family_from_path(path: list[str], obj: dict | None = None) -> str:
    joined = ' '.join(path).lower()
    obj = obj or {}
    explicit = _clean(obj.get('family') or obj.get('table_family') or obj.get('table_type') or obj.get('kind')).lower()
    text = f'{joined} {explicit}'
    if any(k in text for k in ('orcamento', 'orçamento', 'budget', 'synthetic')):
        return 'budget'
    if 'sicro' in text:
        return 'sicro'
    if any(k in text for k in ('composition', 'composicao', 'composição', 'sinapi')):
        return 'sinapi_like'
    return 'generic'


def _summarize_band_items(bands: dict[str, list[dict]]) -> dict:
    summary = {}
    for name, vals in bands.items():
        x0 = sorted([v for v in (_as_float_if_numeric(v.get('x0')) for v in vals) if v is not None])
        x1 = sorted([v for v in (_as_float_if_numeric(v.get('x1')) for v in vals) if v is not None])
        summary[name] = {
            'observations': len(vals),
            'x0_median': round(x0[len(x0)//2], 3) if x0 else None,
            'x1_median': round(x1[len(x1)//2], 3) if x1 else None,
            'samples': vals[:3],
        }
    return summary


def _extract_column_bands(context: dict | None) -> dict:
    """Extract column bands separated by table/family.

    v61.0.23 merged all columns by canonical name, so budget.descricao and
    composition.descricao could pollute each other's profile.  v61.0.24 keeps
    independent buckets and still returns a legacy flat summary for older callers.
    """
    ctx = context or {}
    source = ctx.get('normalizer_clean_payload') or ctx.get('structured_tables') or ctx.get('docling_clean_payload') or {}
    by_family: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

    def walk(obj: Any, path: list[str]):
        if isinstance(obj, dict):
            family_here = _family_from_path(path, obj)
            if isinstance(obj.get('columns'), list):
                for col in obj.get('columns') or []:
                    if not isinstance(col, dict):
                        continue
                    canonical = _clean(col.get('canonical') or col.get('canonical_name') or col.get('name'))
                    if not canonical:
                        continue
                    fam = _family_from_path(path + [canonical], col)
                    if fam == 'generic':
                        fam = family_here
                    item = {'canonical': canonical, 'family': fam}
                    for k in ('x0', 'x1', 'width', 'physical_index', 'geometry_confidence', 'sample_text', 'header', 'header_text'):
                        if col.get(k) not in (None, ''):
                            item[k] = col.get(k)
                    by_family[fam][canonical].append(item)
            for k, v in obj.items():
                walk(v, path + [str(k)])
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, path + [str(i)])

    walk(source, [])
    out = {fam: _summarize_band_items(vals) for fam, vals in by_family.items()}
    # Backward-compatible flat view with generic last priority and family labels in samples.
    flat: dict[str, list[dict]] = defaultdict(list)
    for fam, vals in by_family.items():
        for canonical, items in vals.items():
            flat[canonical].extend(items)
    out['flat'] = _summarize_band_items(flat)
    return out




def _weak_description(value: Any) -> bool:
    text = _clean(value)
    if not text:
        return True
    norm = text.upper()
    tail = (norm.split() or [''])[-1]
    if tail in {'DE', 'DA', 'DO', 'DAS', 'DOS', 'PARA', 'COM', 'E', 'EM', 'A', 'O', 'AO'}:
        return True
    return len(text) < 42 and 'AF_' not in norm


def _build_selective_reparse_plan(orcamento: OrcamentoSintetico, comp: Composicoes) -> dict:
    budget_targets = []
    composition_targets = []
    for item in _walk_budget_items(getattr(orcamento, 'itens_raiz', []) or []):
        if str(getattr(item, 'tipo', '')).lower() != 'item':
            continue
        desc = _clean(getattr(item, 'especificacao', ''))
        if _weak_description(desc):
            budget_targets.append({
                'item': getattr(item, 'item', ''),
                'codigo': getattr(item, 'codigo', ''),
                'fonte': getattr(item, 'fonte', ''),
                'field': 'especificacao',
                'reason': 'missing_or_weak_budget_description',
                'family': 'budget',
                'table_family': 'budget',
                'action': 'targeted_recovery_local',
                'page': getattr(item, 'pagina', None) or getattr(item, 'page_hint', None) or getattr(item, 'pagina_inicio', None),
            })
    for collection, key, block in _iter_blocks(comp):
        principal = getattr(block, 'principal', None)
        if principal is not None and _is_sicro(getattr(principal, 'banco', '')):
            continue
        for group, line in _iter_lines(block):
            desc = _clean(getattr(line, 'descricao', ''))
            if _weak_description(desc):
                composition_targets.append({
                    'collection': collection,
                    'block_key': key,
                    'row_group': group,
                    'codigo': getattr(line, 'codigo', ''),
                    'banco': getattr(line, 'banco', ''),
                    'field': 'descricao',
                    'reason': 'missing_or_weak_composition_description',
                    'family': 'sinapi_like',
                    'table_family': 'composition',
                    'action': 'targeted_recovery_local',
                    'page': getattr(line, 'page_hint', None) or getattr(block, 'pagina_inicio', None),
                })
    return {
        'mode': 'selective_profile_reparse_targets',
        'budget_targets': budget_targets[:120],
        'composition_targets': composition_targets[:120],
        'summary': {
            'budget_targets': len(budget_targets),
            'composition_targets': len(composition_targets),
            'total_targets': len(budget_targets) + len(composition_targets),
        },
    }

def build_document_learning_profile(orcamento: OrcamentoSintetico, comp: Composicoes, *, context: dict | None = None, config: dict | None = None) -> Dict[str, Any]:
    known_units = _known_units(config)
    unit_counter: Counter[str] = Counter()
    new_units: dict[str, dict] = {}
    bank_counter: Counter[str] = Counter()
    budget_items = 0
    budget_break_candidates = 0
    for item in _walk_budget_items(getattr(orcamento, 'itens_raiz', []) or []):
        tipo = _clean(getattr(item, 'tipo', '') if not isinstance(item, dict) else item.get('tipo'))
        if tipo.lower() == 'item':
            budget_items += 1
        unit = _clean(getattr(item, 'und', '') if not isinstance(item, dict) else item.get('und')).upper().replace(' ', '')
        desc = _clean(getattr(item, 'especificacao', '') if not isinstance(item, dict) else item.get('especificacao'))
        if unit:
            unit_counter[unit] += 1
            if unit not in known_units and re.fullmatch(r'[A-Z%0-9²³./-]{1,10}', unit) and not re.search(r'[,.]\d', unit):
                new_units.setdefault(unit, {'value': unit, 'confidence': 0.75, 'evidence': []})['evidence'].append('orcamento.und')
        if desc and len(desc) < 35:
            budget_break_candidates += 1
    family_counts = Counter()
    description_lengths: list[int] = []
    for collection, key, block in _iter_blocks(comp):
        principal = getattr(block, 'principal', None)
        bank = _canon_bank(getattr(principal, 'banco', '') if principal else '')
        family = 'sicro' if bank == 'SICRO' else 'sinapi_like'
        family_counts[family] += 1
        bank_counter[bank] += 1
        for _, line in _iter_lines(block):
            unit = _clean(getattr(line, 'und', '')).upper().replace(' ', '')
            if unit:
                unit_counter[unit] += 1
                if unit not in known_units and re.fullmatch(r'[A-Z%0-9²³./-]{1,10}', unit) and not re.search(r'[,.]\d', unit):
                    ent = new_units.setdefault(unit, {'value': unit, 'confidence': 0.82, 'evidence': []})
                    ent['evidence'].append(f'{collection}.{key}')
            desc = _clean(getattr(line, 'descricao', ''))
            if desc:
                description_lengths.append(len(desc))
    for ent in new_units.values():
        ent['evidence'] = sorted(set(ent.get('evidence') or []))[:8]
        ent['confidence'] = min(0.98, float(ent.get('confidence') or 0.75) + min(len(ent['evidence']), 5) * 0.02)
    column_bands_by_family = _extract_column_bands(context)
    budget_bands = column_bands_by_family.get('budget') or column_bands_by_family.get('flat') or {}
    sinapi_bands = column_bands_by_family.get('sinapi_like') or column_bands_by_family.get('composition') or column_bands_by_family.get('flat') or {}
    calibrated_profile = (((context or {}).get('normalizer_clean_payload') or {}).get('metadata') or {}).get('calibrated_document_profile') or ((context or {}).get('calibrated_document_profile') or {})
    if isinstance(calibrated_profile, dict):
        ctables = calibrated_profile.get('tables') or {}
        for cname, table in (ctables.items() if isinstance(ctables, dict) else []):
            target = budget_bands if cname == 'budget' else sinapi_bands if cname in {'composition', 'sinapi_like'} else None
            if isinstance(target, dict):
                for col in table.get('columns') or []:
                    if isinstance(col, dict) and col.get('canonical'):
                        target.setdefault(col.get('canonical'), {'observations': 0})
                        if col.get('x0') is not None:
                            target[col.get('canonical')]['x0_median'] = col.get('x0')
                        if col.get('x1') is not None:
                            target[col.get('canonical')]['x1_median'] = col.get('x1')
                        target[col.get('canonical')]['geometry_source'] = col.get('geometry_source') or 'calibrated_document_profile'
    selective_reparse_plan = _build_selective_reparse_plan(orcamento, comp)
    return {
        'version': VERSION,
        'budget_profile': {
            'items_seen': budget_items,
            'short_description_candidates': budget_break_candidates,
            'units_seen': dict(unit_counter),
            'column_bands': {k: v for k, v in budget_bands.items() if k in {'item_agregador','codigo','fonte','descricao','und','quant','custo_unitario_sem_bdi','custo_unitario_com_bdi','custo_parcial','custo_total'}},
        },
        'sinapi_like_profile': {
            'blocks_seen': int(family_counts.get('sinapi_like') or 0),
            'description_length_median': sorted(description_lengths)[len(description_lengths)//2] if description_lengths else 0,
            'column_bands': {k: v for k, v in sinapi_bands.items() if k in {'controle_linha','codigo','banco','descricao','tipo','und','quant','valor_unit','total'}},
            'column_bands_by_family': {k: v for k, v in column_bands_by_family.items() if k != 'flat'},
            'line_break_recovery_enabled': True,
        },
        'sicro_profile': {
            'blocks_seen': int(family_counts.get('sicro') or 0),
            'adapter_policy': 'non_destructive_authoritative_v20',
            'classification_rule': 'has_item_is_principal_else_global_auxiliary',
        },
        'header_footer_profile': (context or {}).get('metadata_extraida_ia', {}).get('header_footer_profile') or {},
        'numeric_profile': {'public_numeric_strings_preferred': True},
        'selective_reparse_plan': selective_reparse_plan,
        'custom_bank_matches': [],
        'enrichment_report': {
            'new_units_detected': sorted(new_units.values(), key=lambda x: (-float(x.get('confidence') or 0), x.get('value'))),
            'banks_seen': dict(bank_counter),
        },
    }
