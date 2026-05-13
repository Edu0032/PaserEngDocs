from __future__ import annotations
from typing import Any, Dict
def augment_correction_with_repair_summary(document:Dict[str,Any], repair_summary:Dict[str,Any]|None)->Dict[str,Any]:
    doc=dict(document or {}); s=dict(repair_summary or {})
    if not s: return doc
    doc['docling_usage']={'enabled':bool(s.get('enabled')),'mode':s.get('mode'),'composition_assisted':bool(s.get('fields_assisted')),'fields_assisted':list(s.get('fields_assisted') or []),'missing_columns':list(s.get('missing_columns') or []),'composition_repair_candidates':int(s.get('repair_candidates') or 0),'composition_repairs_attempted':int(s.get('repairs_attempted') or 0),'composition_repairs_accepted':int(s.get('repairs_accepted') or 0),'math_divergences_before':int(s.get('math_divergences_before') or 0),'math_divergences_after':int(s.get('math_divergences_after') or 0)}
    doc.setdefault('decisoes_de_correcao',[])
    for item in list(s.get('blocks_touched_sample') or []):
        doc['decisoes_de_correcao'].append({'codigo':'docling_assistive_math_repair_decision','colecao':item.get('collection'),'chave':item.get('key'),'status_antes':item.get('before_status'),'status_depois':item.get('after_status'),'linhas_resumo_removidas':item.get('removed_summary_rows'),'limpezas_de_poluicao':item.get('pollution_cleanups'),'causas_provaveis':item.get('suspected_causes') or [],'colunas_docling_usadas':item.get('docling_columns_used') or []})
    return doc
