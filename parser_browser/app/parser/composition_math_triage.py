from __future__ import annotations
from typing import Any, Dict, List
from app.parser.math_status import as_dict, compute_component_math, is_sicro_special_block
def collect_missing_fields(block:Any)->Dict[str,Any]:
    data=as_dict(block); out=[]; rows=[('principal',as_dict(data.get('principal')))] + [('composicao_auxiliar',as_dict(x)) for x in data.get('composicoes_auxiliares') or []] + [('insumo',as_dict(x)) for x in data.get('insumos') or []]
    for idx,(kind,row) in enumerate(rows):
        req=['codigo','banco','descricao','und','quant','valor_unit','total'] if kind=='principal' else ['codigo','banco','descricao','und','quant']
        miss=[f for f in req if row.get(f) in (None,'')]
        if miss: out.append({'kind':kind,'index':idx,'codigo':row.get('codigo'),'missing':miss})
    return {'rows_with_missing_fields':out,'total_rows_with_missing':len(out)}
def triage_composition_block(block:Any,*,summary_markers:List[str]|None=None,docling_profile:Dict[str,Any]|None=None)->Dict[str,Any]:
    math=compute_component_math(block,summary_markers=summary_markers); missing=collect_missing_fields(block); causes=[]; status=str(math.get('status') or '')
    if is_sicro_special_block(block): causes.append('possible_sicro_special_case')
    if missing['total_rows_with_missing']: causes.append('missing_fields')
    if status=='component_sum_lower_than_principal': causes += ['possible_block_closed_early','missing_component_rows']
    elif status=='component_sum_greater_than_principal': causes += ['possible_block_closed_late','possible_extra_component_rows']
    if int(math.get('summary_rows_ignored') or 0)>0: causes.append('summary_rows_detected')
    if int(math.get('missing_component_totals') or 0)>0: causes.append('missing_numeric_field')
    comp=dict((docling_profile or {}).get('by_family',{}).get('composition') or {}); fields=set(comp.get('fields_assisted') or [])
    if fields & {'descricao','tipo','und','quant','valor_unit','total'}: causes.append('docling_bands_available')
    priority='high' if (status in {'component_sum_lower_than_principal','component_sum_greater_than_principal'} or missing['total_rows_with_missing']) and 'docling_bands_available' in causes else ('medium' if missing['total_rows_with_missing'] else 'none')
    return {'status':status or 'unknown','math_status':math,'missing_fields':missing,'suspected_causes':sorted(set(causes)),'repair_priority':priority,'needs_docling_band_repair':priority in {'high','medium'}}
