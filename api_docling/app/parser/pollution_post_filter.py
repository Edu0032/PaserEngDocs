from __future__ import annotations
import re
from typing import Any, Dict, Iterable, List, Tuple
def _norm_terms(terms:Iterable[Any])->List[str]:
    out=[]; seen=set()
    for term in terms or []:
        text=' '.join(str(term or '').replace('\u00a0',' ').split()).strip(); key=text.lower()
        if text and key not in seen: seen.add(key); out.append(text)
    return out
def pollution_terms_from_context(context:Dict[str,Any]|None)->List[str]:
    context=context or {}; hints=dict(context.get('ai_hints') or {}); profile=dict(hints.get('header_footer_profile') or {}); terms=[]
    for key in ['recurring_headers','recurring_footers','budget_headers','budget_footers','composition_headers','composition_footers']: terms.extend(profile.get(key) or [])
    tables=dict(hints.get('table_hints') or context.get('tables') or {})
    for table in tables.values():
        if not isinstance(table,dict): continue
        tph=table.get('table_parent_header') or {}
        if isinstance(tph,dict):
            if tph.get('text'): terms.append(tph.get('text'))
            terms.extend(tph.get('texts') or [])
        terms.extend(table.get('non_column_context') or []); terms.extend(table.get('header_noise_terms') or [])
    dp=dict(context.get('document_profile') or {})
    for key in ['header_phrases_recorrentes','footer_phrases_recorrentes','frases_institucionais_para_ignorar','marcadores_de_secao_recorrentes']: terms.extend(dp.get(key) or [])
    return _norm_terms(terms)
def clean_pollution_text(text:Any, terms:Iterable[str])->Tuple[str,List[str]]:
    cleaned=' '.join(str(text or '').replace('\u00a0',' ').split()).strip(); removed=[]
    for term in _norm_terms(terms):
        new=re.sub(re.escape(term)+r'\s*[:\-.]*\s*',' ',cleaned,flags=re.I)
        if new!=cleaned: removed.append(term); cleaned=new
    return re.sub(r'\s+',' ',cleaned).strip(), removed
