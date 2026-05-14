from __future__ import annotations
from typing import Any, Dict, List
from app.parser.docling_column_map import DoclingColumnMap

TEXT_FIELDS={'descricao','tipo','controle_linha','banco','fonte'}
UNIT_FIELDS={'und'}
NUMERIC_FIELDS={'quant','valor_unit','total','custo_unitario_sem_bdi','custo_unitario_com_bdi','custo_parcial','custo_total'}

def _tables(payload: Dict[str,Any]|None) -> List[Dict[str,Any]]:
    st=dict((payload or {}).get('structured_tables') or {})
    raw=st.get('tables')
    if isinstance(raw, dict): return [dict(v) for v in raw.values() if isinstance(v,dict)]
    if isinstance(raw, list): return [dict(v) for v in raw if isinstance(v,dict)]
    return []

def _family(t:Dict[str,Any])->str:
    f=str(t.get('family') or '').lower(); k=str(t.get('kind') or '').lower(); tid=str(t.get('table_id') or t.get('template_id') or '').lower()
    if f=='budget' or k=='orcamento_sintetico' or tid.startswith('budget'): return 'budget'
    if f=='sicro' or k=='composicao_sicro' or tid.startswith('sicro'): return 'sicro'
    return 'composition'

def _col_from_band(b)->Dict[str,Any]:
    return {'canonical':b.canonical,'header':b.header,'physical_index':b.physical_index,'x0':b.x0,'x1':b.x1,'width':b.width,'geometry_source':'docling_column_map','geometry_confidence':b.geometry_confidence,'ignore_in_domain':b.ignore_in_domain,'structural_only':b.structural_only}

def get_docling_assistive_profile(context:Dict[str,Any]|None)->Dict[str,Any]:
    tables=_tables(context)
    prof={'enabled':bool(tables),'mode':'docling_column_map','tables_loaded':[],'by_family':{}}
    for raw in tables:
        fam=_family(raw)
        cmap=DoclingColumnMap.from_context({'structured_tables': {'tables':[raw]}}, context=(context or {}), family=fam) if False else None
        # Avoid relying on the first table selected by from_context when passing a single table with unusual family aliases.
        cols=list(raw.get('column_schema') or raw.get('columns') or [])
        for ic in list(raw.get('ignored_columns') or []):
            if isinstance(ic,dict):
                c=dict(ic); meta=dict(c.get('metadata') or {}); meta.setdefault('ignore_in_domain', True); meta.setdefault('structural_only', True); c['metadata']=meta; cols.append(c)
        cmap=DoclingColumnMap(cols, include_tipo_in_final_json=DoclingColumnMap.include_tipo_from_options(context=context), family=fam, table_id=str(raw.get('table_id') or raw.get('template_id') or ''))
        av=list(cmap.available_columns)
        effective=list(cmap.effective_columns)
        fields=[c for c in effective if c in (TEXT_FIELDS|UNIT_FIELDS|NUMERIC_FIELDS) and not (c=='tipo' and not cmap.include_tipo_in_final_json)]
        prof['by_family'][fam]={'table_id':raw.get('table_id') or raw.get('template_id'),'kind':raw.get('kind'),'family':fam,'page_start':raw.get('page_start') or raw.get('page'),'page_end':raw.get('page_end') or raw.get('page'),'available_columns':av,'effective_columns':effective,'synthetic_columns':list(cmap.synthetic_columns),'merged_columns_detected':list(cmap.merged_columns_detected),'columns':[_col_from_band(b) for b in cmap.bands],'text_columns':[c for c in effective if c in TEXT_FIELDS],'unit_columns':[c for c in effective if c in UNIT_FIELDS],'numeric_columns':[c for c in effective if c in NUMERIC_FIELDS],'fields_assisted':fields,'geometry_available':cmap.has_geometry,'missing_columns':list(cmap.missing_core),'include_tipo_in_final_json':cmap.include_tipo_in_final_json}
        prof['tables_loaded'].append(fam)
    comp=prof['by_family'].get('composition') or {}; budget=prof['by_family'].get('budget') or {}
    prof['composition_assisted']=bool(comp.get('fields_assisted'))
    prof['composition_fields_assisted']=list(comp.get('fields_assisted') or [])
    prof['composition_missing_core']=[c for c in ['controle_linha','codigo','banco','descricao','und','quant','valor_unit','total'] if c not in set(comp.get('available_columns') or [])]
    prof['budget_assisted']=bool(budget.get('fields_assisted') or budget.get('available_columns'))
    return prof

def profile_for_family(profile:Dict[str,Any],family:str)->Dict[str,Any]:
    return dict((profile or {}).get('by_family',{}).get(family) or {})
