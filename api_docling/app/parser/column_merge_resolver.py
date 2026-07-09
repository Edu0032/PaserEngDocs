from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Mapping, Sequence

# This module intentionally does not know about any specific PDF.  It only uses
# canonical field types, the IA/Docling physical order, positioned token content,
# and validators to decide whether a token belongs to a missing column that was
# visually merged into a neighboring band.

_UNIT_TOKENS = {
    'M','M²','M2','M³','M3','KG','UN','UND','H','HS','L','CJ','TB','GL','PÇ','PC',
    'PR','SC','T','RL','CX','MES','M3XKM','M2XKM','%'
}
_BANK_TOKENS = {
    'SINAPI','SICRO','SICRO3','PROPRIO','PRÓPRIO','ORSE','SEINFRA','SBC','SEDOP',
    'EMBASA','CPOS','DER','DNIT','ANP'
}


def _clean(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '').replace('\xa0', ' ')).strip()


def _norm(value: Any) -> str:
    s = _clean(value).upper()
    return (s.replace('Á','A').replace('À','A').replace('Â','A').replace('Ã','A')
             .replace('É','E').replace('Ê','E').replace('Í','I')
             .replace('Ó','O').replace('Ô','O').replace('Õ','O')
             .replace('Ú','U').replace('Ç','C'))


def looks_like_codigo(value: Any) -> bool:
    s = _clean(value)
    u = _norm(s)
    if not s or u in _BANK_TOKENS or looks_like_unit(s):
        return False
    # numeric SINAPI/SICRO-like codes, including zero-prefixed and slash variants
    if re.fullmatch(r'\d{2,}(?:/\d{1,4})?', s):
        return True
    # local/proprietary codes: COMP.EXEMPLO.1, CP-120, ABC 01, REF-S, etc.
    if re.search(r'\d', s) and re.fullmatch(r'[A-Za-zÁ-Úá-ú]{1,8}(?:[\s./_-]*[A-Za-z0-9Á-Úá-ú]+)+', s):
        return True
    return False


def looks_like_banco(value: Any, known_banks: Iterable[str] | None = None) -> bool:
    u = _norm(value)
    banks = set(_BANK_TOKENS)
    for b in list(known_banks or []):
        if b:
            banks.add(_norm(b))
    return u in banks


def looks_like_unit(value: Any) -> bool:
    u = _norm(value).replace('M2','M²').replace('M3','M³')
    return u in _UNIT_TOKENS or bool(re.fullmatch(r'[A-Z%]{1,6}(?:[²³])?', u) and u not in {'DE','DO','DA','EM','COM','PARA','E','TIPO'})


def looks_like_number(value: Any) -> bool:
    return bool(re.fullmatch(r'[-+]?\d[\d.,]*', _clean(value)))


def looks_like_money(value: Any) -> bool:
    s = _clean(value).replace('R$', '').strip()
    return bool(re.fullmatch(r'[-+]?\d[\d.,]*', s))


def validator_for(canonical: str, *, known_banks: Iterable[str] | None = None):
    c = str(canonical or '').strip().lower()
    if c in {'codigo', 'cod'}:
        return looks_like_codigo
    if c in {'banco', 'fonte'}:
        return lambda v: looks_like_banco(v, known_banks=known_banks)
    if c in {'und', 'unidade'}:
        return looks_like_unit
    if c in {'quant', 'quantidade'}:
        return looks_like_number
    if c in {'valor_unit', 'total', 'custo_unitario_sem_bdi', 'custo_unitario_com_bdi', 'custo_parcial', 'custo_total'}:
        return looks_like_money
    if c in {'descricao', 'especificacao', 'controle_linha', 'tipo'}:
        return lambda v: bool(_clean(v))
    return lambda v: bool(_clean(v))


@dataclass
class MergeResolution:
    missing_columns: List[str] = field(default_factory=list)
    classification_sources: Dict[str, List[str]] = field(default_factory=dict)
    detected: List[Dict[str, Any]] = field(default_factory=list)

    def classify(self, source_column: str, text: Any, *, known_banks: Iterable[str] | None = None) -> str | None:
        source = str(source_column or '').strip().lower()
        candidates = list(self.classification_sources.get(source) or [])
        if not candidates:
            return None
        for cand in candidates:
            if cand == source:
                continue
            if validator_for(cand, known_banks=known_banks)(text):
                return cand
        return None


def _canonical_order_index(expected_order: Sequence[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for idx, col in enumerate(expected_order or []):
        c = str(col or '').strip().lower()
        if c and c not in out:
            out[c] = idx
    return out


def build_merge_resolution(
    available_columns: Sequence[str],
    expected_order: Sequence[str],
    *,
    sample_words: Sequence[Mapping[str, Any]] | None = None,
    known_banks: Iterable[str] | None = None,
) -> MergeResolution:
    """Create a generic evidence-based plan for suspected merged columns.

    A plan is made only when an expected column is absent and an adjacent expected
    column is present.  If sample words are provided, they are used to confirm
    that tokens compatible with the missing column exist inside the neighboring
    band.  Without samples, the plan is still valid as a conservative
    classification-only fallback: a token is re-routed only when its own content
    validates for the missing field.
    """
    available = [str(c or '').strip().lower() for c in available_columns if str(c or '').strip()]
    expected = [str(c or '').strip().lower() for c in expected_order if str(c or '').strip()]
    order = _canonical_order_index(expected)
    missing = [c for c in expected if c not in available]
    res = MergeResolution(missing_columns=missing)
    if not missing or not expected:
        return res

    available_set = set(available)
    for miss in missing:
        if miss not in order:
            continue
        idx = order[miss]
        neighbor_candidates: List[str] = []
        # Prefer immediate right/left neighbors according to payload order.
        for j in range(idx + 1, len(expected)):
            if expected[j] in available_set:
                neighbor_candidates.append(expected[j]); break
        for j in range(idx - 1, -1, -1):
            if expected[j] in available_set:
                neighbor_candidates.append(expected[j]); break
        for source in neighbor_candidates:
            source = str(source or '').lower()
            if source == miss:
                continue
            confirmed = True
            evidence_count = 0
            if sample_words:
                validator = validator_for(miss, known_banks=known_banks)
                for w in sample_words:
                    if str(w.get('source_column') or w.get('column') or '').strip().lower() != source:
                        continue
                    if validator(w.get('text')):
                        evidence_count += 1
                confirmed = evidence_count > 0
            if not confirmed:
                continue
            values = res.classification_sources.setdefault(source, [])
            # Missing columns first so they get a chance before source column.
            if miss not in values:
                values.insert(0, miss)
            if source not in values:
                values.append(source)
            res.detected.append({
                'source_column': source,
                'created_columns': [miss, source],
                'method': 'token_evidence_classification' if sample_words else 'validator_classification_fallback',
                'confidence': 0.86 if sample_words else 0.68,
                'sample_rows_used': evidence_count,
                'reason': 'missing_expected_column_adjacent_to_available_column',
            })
            break
    return res
