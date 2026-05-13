from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from app.config.loader import load_base_config

@dataclass(frozen=True)
class SicroFieldScore:
    field: str
    score: int
    reasons: Tuple[str, ...]

def _strip_accents(text: str) -> str:
    return ''.join(ch for ch in unicodedata.normalize('NFD', text) if unicodedata.category(ch) != 'Mn')

def norm(text: Any) -> str:
    return ' '.join(str(text or '').replace('\xa0',' ').split()).strip()

def norm_key(text: Any) -> str:
    return _strip_accents(norm(text)).upper()

def load_sicro_engine_config() -> Dict[str, Any]:
    try:
        return (((load_base_config() or {}).get('knowledge_bases') or {}).get('sicro') or {})
    except Exception:
        return {}

def _regex_fullmatch(pattern: str, value: str) -> bool:
    try:
        return bool(re.fullmatch(pattern, value, flags=re.IGNORECASE))
    except re.error:
        return False

def classify_code_token(value: Any, config: Optional[Dict[str, Any]] = None) -> str:
    text = norm(value).replace(' ','')
    if not text: return ''
    config = config or load_sicro_engine_config()
    for name, meta in ((config.get('code_patterns') or {}) if isinstance(config,dict) else {}).items():
        pat = meta.get('regex') if isinstance(meta,dict) else str(meta or '')
        if pat and _regex_fullmatch(pat, text): return str(name)
    if re.fullmatch(r'E\d{3,5}', text, flags=re.I): return 'equipamento'
    if re.fullmatch(r'P\d{3,5}', text, flags=re.I): return 'mao_obra'
    if re.fullmatch(r'M\d{3,5}', text, flags=re.I): return 'material'
    if re.fullmatch(r'\d{7}', text): return 'composicao_atual_7_digitos'
    if re.fullmatch(r'\d\s+[A-Z]\s+\d{2}\s+\d{3}\s+\d{2}', norm(value), flags=re.I): return 'sicro2_legado_espacado'
    return ''

def looks_like_bank(value: Any) -> bool:
    key = norm_key(value)
    return key in {'SICRO','SICRO3','SICRO 3','DNIT'} or bool(re.search(r'\bSICRO\s*3?\b|\bDNIT\b', key))

def resolve_code_bank(first: Any, second: Any, config: Optional[Dict[str, Any]] = None) -> Tuple[str,str,Dict[str,Any]]:
    a,b = norm(first), norm(second)
    a_bank,b_bank = looks_like_bank(a), looks_like_bank(b)
    a_code,b_code = classify_code_token(a,config), classify_code_token(b,config)
    ev={'first':a,'second':b,'first_is_bank':a_bank,'second_is_bank':b_bank,'first_code_type':a_code,'second_code_type':b_code,'rule':'content_based_code_bank_resolution'}
    if a_bank and b_code: return b,a,ev
    if b_bank and a_code: return a,b,ev
    if a_bank: return b,a,ev
    if b_bank: return a,b,ev
    if a_code and not b_code: return a,b,ev
    if b_code and not a_code: return b,a,ev
    return a,b,ev

def classify_unit(value: Any, config: Optional[Dict[str, Any]] = None) -> str:
    raw=norm(value); key=norm_key(raw).replace(' ','')
    try: units_root=(((load_base_config() or {}).get('knowledge_bases') or {}).get('units') or {})
    except Exception: units_root={}
    groups={'transport':units_root.get('transport') or ['t.km','tkm','m³.km','m3.km','m³xkm','m3xkm','M3XKM'], 'productivity':units_root.get('productivity') or ['m³/h','m3/h','m²/h','m2/h','t/h','km/h','un/h'], 'common':units_root.get('common') or ['%','h','m','m²','m2','m³','m3','kg','t','un','und','mês','mes','l']}
    for group, vals in groups.items():
        if any(norm_key(u).replace(' ','')==key for u in vals): return group
    return ''

def parse_decimal_ptbr(value: Any) -> Optional[Decimal]:
    text=norm(value).replace('R$','').strip()
    if not re.fullmatch(r'-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+(?:,\d+)?', text): return None
    try: return Decimal(text.replace('.','').replace(',','.'))
    except InvalidOperation: return None

def numeric_profile(value: Any) -> str:
    text=norm(value); dec=parse_decimal_ptbr(text)
    if dec is None: return ''
    scale=len(text.split(',')[-1]) if ',' in text else 0
    if scale>=6: return 'quantity_high_precision'
    if scale==4: return 'cost_4'
    if scale==3: return 'dmt_distance'
    if scale==2: return 'factor_2' if dec<=Decimal('1.00') else 'money_2'
    return 'integer_or_quantity'

def infer_section_from_header(header_text: Any, config: Optional[Dict[str, Any]] = None) -> str:
    key = norm_key(header_text)
    config = config or load_sicro_engine_config()
    if not key:
        return ''

    # A-F are valid SICRO section identifiers, but a single-letter anchor is
    # dangerous as a plain substring ("A" appears inside BANCO/MATERIAL).
    # Prefer the explicit first token and longer semantic anchors first.
    first = key.split()[0] if key.split() else ''
    if first in {'A', 'B', 'C', 'D', 'E', 'F'}:
        return first

    candidates: List[Tuple[int, str, str]] = []
    for sec, meta in (config.get('sections') or {}).items():
        if sec == 'principal' or not isinstance(meta, dict):
            continue
        labels = [meta.get('label'), meta.get('public_key')] + list(meta.get('anchors') or [])
        for label in labels:
            lab = norm_key(label)
            if not lab or len(lab) <= 1:
                continue
            candidates.append((len(lab), str(sec), lab))
    for _length, sec, lab in sorted(candidates, reverse=True):
        if lab in key:
            return sec

    if 'MOMENTO DE TRANSPORTE' in key or 'DMT' in key:
        return 'F'
    if 'TEMPO FIXO' in key or 'TEMPOS FIXOS' in key:
        return 'E'
    if 'ATIVIDADES AUXILIARES' in key:
        return 'D'
    if 'MATERIAL' in key:
        return 'C'
    if 'MAO DE OBRA' in key or 'MÃO DE OBRA' in key:
        return 'B'
    if 'EQUIP' in key:
        return 'A'
    return ''

def score_token_for_field(token: Any, field_meta: Dict[str,Any], config: Optional[Dict[str,Any]]=None) -> SicroFieldScore:
    token_norm=norm(token); score=0; reasons=[]
    if not token_norm: return SicroFieldScore(str(field_meta.get('field') or ''),0,tuple())
    if field_meta.get('pattern') and _regex_fullmatch(str(field_meta['pattern']), token_norm.replace(' ','')):
        score+=40; reasons.append('code_pattern')
    expected=[norm_key(x) for x in (field_meta.get('expected_values') or [])]
    if expected and norm_key(token_norm) in expected: score+=40; reasons.append('expected_value')
    if field_meta.get('unit_group') and classify_unit(token_norm, config) in {str(field_meta.get('unit_group')), 'common'}:
        score+=25; reasons.append('unit_match')
    if field_meta.get('numeric_profile') and numeric_profile(token_norm)==field_meta.get('numeric_profile'):
        score+=25; reasons.append('numeric_profile')
    if field_meta.get('text_length') and parse_decimal_ptbr(token_norm) is None and not classify_code_token(token_norm, config) and not looks_like_bank(token_norm):
        tl=field_meta['text_length']
        if int(tl.get('min',0)) <= len(token_norm) <= int(tl.get('max',9999)):
            score+=20; reasons.append('text_length')
    return SicroFieldScore(str(field_meta.get('field') or ''), score, tuple(reasons))

def validate_public_sicro_row(section: str, row: Dict[str,Any], config: Optional[Dict[str,Any]]=None) -> Dict[str,Any]:
    config=config or load_sicro_engine_config(); meta=((config.get('sections') or {}).get(section) or {})
    missing=[]; warnings=[]
    for field in meta.get('field_schema') or []:
        if not isinstance(field,dict) or not field.get('required'): continue
        val=row
        for part in str(field.get('field') or '').split('.'):
            val=val.get(part) if isinstance(val,dict) else None
        if val in (None,'',[],{}): missing.append(field.get('field'))
    def scan(obj,path=''):
        if isinstance(obj,dict):
            for k,v in obj.items(): scan(v, f'{path}.{k}' if path else str(k))
        elif isinstance(obj,list):
            for i,v in enumerate(obj): scan(v, f'{path}[{i}]')
        elif isinstance(obj,float): warnings.append(f'float_public_value:{path}')
        elif isinstance(obj,str) and re.fullmatch(r'-?\d+\.\d+',obj): warnings.append(f'dot_decimal_public_value:{path}')
    scan(row)
    return {'section':section,'ok':not missing and not warnings,'missing':missing,'warnings':warnings}

def sicro_public_section_keys(config: Optional[Dict[str,Any]]=None) -> Dict[str,str]:
    config=config or load_sicro_engine_config(); return {str(sec):str(meta.get('public_key') or sec) for sec,meta in (config.get('sections') or {}).items() if sec!='principal' and isinstance(meta,dict)}
