from __future__ import annotations
from typing import Any, Dict, Iterable, List, Tuple
from app.core.schemas import BlocoComposicao, Composicoes, LinhaComposicao, LinhaInsumo
from app.parser.composition_math_triage import triage_composition_block
from app.parser.docling_assistive_bands import get_docling_assistive_profile, profile_for_family
from app.parser.docling_column_map import DoclingColumnMap
from app.parser.math_status import as_dict, is_summary_row, compute_component_math
from app.parser.pollution_post_filter import clean_pollution_text, pollution_terms_from_context
from app.parser.description_guard import repair_financial_tail, strip_noise_from_description

PROBLEM_STATUSES={'component_sum_lower_than_principal','component_sum_greater_than_principal'}

def _summary_markers_from_context(context:Dict[str,Any]|None)->List[str]:
    hints=dict((context or {}).get('ai_hints') or {})
    prof=dict(hints.get('header_footer_profile') or {})
    markers=list(prof.get('composition_footers') or [])
    comp=dict((dict(hints.get('table_hints') or {})).get('composition') or {})
    # v60: body_stop_markers may contain row-control values (Composição,
    # Composição Auxiliar, Insumo) and even codes/banks from selection policies.
    # Those are NOT summary rows and must never remove real components.
    markers += list(comp.get('header_noise_terms') or [])
    base=['MO sem LS','LS =>','MO com LS','Valor do BDI','Valor com BDI','Total sem BDI','Total Geral']
    markers += base
    return [m for m in markers if str(m or '').strip()]

def _clean_line_description(line: LinhaComposicao|LinhaInsumo, terms:Iterable[str])->bool:
    changed = False
    # Stage 0: recover financial tail accidentally appended to descricao and
    # remove Docling/payload/header/tipo noise using strict guards.
    tail = repair_financial_tail(line, pollution_terms=terms)
    if tail.get('changed'):
        changed = True
    cleaned, removed=clean_pollution_text(getattr(line,'descricao',''),terms)
    guarded, guard_removed = strip_noise_from_description(cleaned, pollution_terms=terms)
    removed = list(removed or []) + list(guard_removed or [])
    if guarded != getattr(line,'descricao',''):
        line.descricao=guarded
        changed = True
    if removed:
        det=dict(getattr(line,'detalhes',{}) or {})
        det.setdefault('pollution_post_filter',{})
        det['pollution_post_filter'].setdefault('removed_terms',[])
        det['pollution_post_filter']['removed_terms'].extend(removed)
        line.detalhes=det
        changed = True
    return changed

def _split_summary_rows(rows:List[Any], markers:List[str])->Tuple[List[Any],List[Dict[str,Any]]]:
    kept=[]; summary=[]
    for row in rows:
        if is_summary_row(row, summary_markers=markers): summary.append(as_dict(row))
        else: kept.append(row)
    return kept, summary

def _has_suspicious_missing(block:BlocoComposicao)->bool:
    rows=[block.principal]+list(block.composicoes_auxiliares or [])+list(block.insumos or [])
    for row in rows:
        for field in ('codigo','banco','descricao','und','quant'):
            if getattr(row, field, None) in ('', None):
                return True
    return False

def _apply_light_cleanup(block:BlocoComposicao, *, summary_markers:List[str], pollution_terms:List[str])->Dict[str,Any]:
    aux, aux_sum=_split_summary_rows(list(block.composicoes_auxiliares or []), summary_markers)
    ins, ins_sum=_split_summary_rows(list(block.insumos or []), summary_markers)
    removed=aux_sum+ins_sum
    if removed:
        block.composicoes_auxiliares=aux
        block.insumos=[x if isinstance(x,LinhaInsumo) else LinhaInsumo(**as_dict(x)) for x in ins]
    pollution=0
    for line in [block.principal]+list(block.composicoes_auxiliares or [])+list(block.insumos or []):
        pollution += 1 if _clean_line_description(line,pollution_terms) else 0
    details=dict(block.detalhes or {})
    if removed:
        # v60: summary rows are preserved lightly as raw audit text, not used as components.
        details.setdefault('summary_rows_raw', [])
        details['summary_rows_raw'].extend(removed)
        details['summary_rows'] = removed
    if pollution:
        details['pollution_post_filter']={'lines_cleaned':pollution}
    block.detalhes=details
    return {'removed_summary_rows':len(removed),'pollution_cleanups':pollution}

def _mark_docling(block:BlocoComposicao, *, math:Dict[str,Any], triage:Dict[str,Any]|None, docling_profile:Dict[str,Any], repair_result:str, extra:Dict[str,Any]|None=None)->None:
    comp=profile_for_family(docling_profile,'composition')
    details=dict(block.detalhes or {})
    details['math_status']=math
    if triage is not None:
        details['math_triage']=triage
    details['docling_assistance']={
        'used':bool(comp.get('fields_assisted')),
        'mode':'docling_column_map',
        'columns_used':list(comp.get('fields_assisted') or []),
        'available_columns':list(comp.get('available_columns') or []),
        'missing_columns':list(comp.get('missing_columns') or []),
        'synthetic_columns':list(comp.get('synthetic_columns') or []),
        'merged_columns_detected':list(comp.get('merged_columns_detected') or []),
        'include_tipo_in_final_json':bool(comp.get('include_tipo_in_final_json')),
        'repair_result':repair_result,
    }
    if extra:
        details['docling_assistance'].update(extra)
    block.detalhes=details

def apply_docling_assistive_math_repair(comp:Composicoes,*,context:Dict[str,Any]|None=None,config:Dict[str,Any]|None=None,page_range:Tuple[int,int]|None=None,pdf_session:Any|None=None)->Dict[str,Any]:
    context=context or {}; config=config or {}
    docling_profile=get_docling_assistive_profile(context)
    docling_map=DoclingColumnMap.from_context(context, config=config, family='composition')
    markers=_summary_markers_from_context(context)
    pollution_terms=pollution_terms_from_context(context)
    stats={'enabled':bool(docling_profile.get('enabled')),'mode':'docling_column_map_math_repair','page_range':{'start':page_range[0],'end':page_range[1]} if page_range else None,'available_columns':list((docling_profile.get('by_family',{}).get('composition') or {}).get('available_columns') or []),'fields_assisted':list(docling_profile.get('composition_fields_assisted') or []),'missing_columns':list(docling_profile.get('composition_missing_core') or []),'repair_candidates':0,'repairs_attempted':0,'repairs_accepted':0,'math_divergences_before':0,'math_divergences_after':0,'blocks_with_missing_fields_before':0,'summary_rows_preserved':0,'pollution_cleanups':0,'stage3_recovery_attempted':0,'stage3_recovery_skipped':0,'blocks_touched_sample':[]}
    for collection_name, blocks in [('principais',comp.principais),('auxiliares_globais',comp.auxiliares_globais)]:
        for key, block in list((blocks or {}).items()):
            before=compute_component_math(block,summary_markers=markers)
            if before.get('status') in PROBLEM_STATUSES: stats['math_divergences_before']+=1
            if _has_suspicious_missing(block): stats['blocks_with_missing_fields_before']+=1
            cleanup=_apply_light_cleanup(block,summary_markers=markers,pollution_terms=pollution_terms)
            stats['summary_rows_preserved'] += cleanup['removed_summary_rows']
            stats['pollution_cleanups'] += cleanup['pollution_cleanups']
            after_cleanup=compute_component_math(block,summary_markers=markers)
            needs_heavy = after_cleanup.get('status') in PROBLEM_STATUSES or _has_suspicious_missing(block) or cleanup['removed_summary_rows'] or cleanup['pollution_cleanups']
            triage=None
            repair_result='cleanup_only' if (cleanup['removed_summary_rows'] or cleanup['pollution_cleanups']) else 'observed'
            if needs_heavy:
                stats['repair_candidates']+=1; stats['repairs_attempted']+=1
                triage=triage_composition_block(block,summary_markers=markers,docling_profile=docling_profile)
                # Full row recovery is intentionally guarded. v60 records enough state for
                # deterministic future re-extraction, but never fabricates rows without a
                # confident visual row parser.
                if pdf_session is not None and docling_map.has_geometry:
                    stats['stage3_recovery_attempted'] += 1
                    repair_result='needs_manual_review_or_future_reextract'
                else:
                    stats['stage3_recovery_skipped'] += 1
                    repair_result='heavy_repair_skipped_no_pdf_or_geometry'
            final=compute_component_math(block,summary_markers=markers)
            if final.get('status') not in PROBLEM_STATUSES and before.get('status') in PROBLEM_STATUSES:
                stats['repairs_accepted']+=1
                repair_result='accepted'
            if final.get('status') in PROBLEM_STATUSES: stats['math_divergences_after']+=1
            _mark_docling(block, math=final, triage=triage, docling_profile=docling_profile, repair_result=repair_result, extra={'docling_map_has_geometry':docling_map.has_geometry})
            if len(stats['blocks_touched_sample'])<25 and (needs_heavy or cleanup['removed_summary_rows'] or cleanup['pollution_cleanups']):
                stats['blocks_touched_sample'].append({'collection':collection_name,'key':str(key),'before_status':before.get('status'),'after_status':final.get('status'),'removed_summary_rows':cleanup['removed_summary_rows'],'pollution_cleanups':cleanup['pollution_cleanups'],'docling_columns_used':list((profile_for_family(docling_profile,'composition')).get('fields_assisted') or [])})
    return stats
