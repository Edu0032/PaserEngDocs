from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

SICRO_BANK_RE = re.compile(r"\b(?:SICRO\s*3?|DNIT)\b", re.IGNORECASE)
SICRO_CODE_PATTERNS = {
    "composicao_principal": re.compile(r"^\d{7}$"),
    "atividade_auxiliar": re.compile(r"^\d{7}$"),
    "equipamento": re.compile(r"^E\d{3,5}$", re.IGNORECASE),
    "mao_obra": re.compile(r"^P\d{3,5}$", re.IGNORECASE),
    "material": re.compile(r"^M\d{3,5}$", re.IGNORECASE),
    "tempo_fixo_servico": re.compile(r"^\d{7}$"),
    "transporte_servico": re.compile(r"^\d{7}$"),
}

SICRO_SECTIONS: Dict[str, Dict[str, Any]] = {
    "A": {
        "name": "equipamentos",
        "row_type": "equipamento",
        "description_headers": ["Equipamentos"],
        "code_fields": ["codigo"],
        "code_patterns": ["equipamento"],
        "columns": ["tipo_linha", "codigo", "banco", "descricao", "quant", "utilizacao_operativa", "utilizacao_improdutiva", "custo_operacional_operativa", "custo_operacional_improdutiva", "custo_horario"],
        "units": ["h"],
    },
    "B": {
        "name": "mao_obra",
        "row_type": "mao_obra",
        "description_headers": ["Mão de Obra", "Mao de Obra"],
        "code_fields": ["codigo"],
        "code_patterns": ["mao_obra"],
        "columns": ["tipo_linha", "codigo", "banco", "descricao", "quant", "salario_hora", "custo_horario"],
        "units": ["h"],
    },
    "C": {
        "name": "material",
        "row_type": "material",
        "description_headers": ["Material"],
        "code_fields": ["codigo"],
        "code_patterns": ["material"],
        "columns": ["tipo_linha", "banco", "codigo", "descricao", "quant", "und", "preco_unitario", "custo_horario"],
        "units": ["kg", "t", "m", "m²", "m³", "l", "un"],
    },
    "D": {
        "name": "atividades_auxiliares",
        "row_type": "atividade_auxiliar",
        "description_headers": ["Atividades Auxiliares"],
        "code_fields": ["codigo"],
        "code_patterns": ["atividade_auxiliar"],
        "columns": ["tipo_linha", "banco", "codigo", "descricao", "quant", "und", "preco_unitario", "custo_horario"],
        "units": ["m", "m²", "m³", "kg", "t", "un", "h"],
    },
    "E": {
        "name": "tempo_fixo",
        "row_type": "tempo_fixo",
        "description_headers": ["Tempos Fixos"],
        "code_fields": ["insumo", "codigo"],
        "code_patterns": ["material", "tempo_fixo_servico"],
        "columns": ["tipo_linha", "banco", "insumo", "descricao", "codigo", "quant", "und", "preco_unitario", "custo_horario"],
        "units": ["t", "m³", "kg", "un"],
    },
    "F": {
        "name": "momento_transporte",
        "row_type": "momento_transporte",
        "description_headers": ["Momento de Transporte"],
        "code_fields": ["insumo"],
        "code_patterns": ["material"],
        "columns": ["tipo_linha", "banco", "insumo", "descricao", "quant", "und", "dmt_ln", "dmt_rp", "dmt_p", "custo_horario"],
        "units": ["tkm"],
        "grouped_columns": ["LN", "RP", "P"],
    },
}

BANK_ALIASES = {"SICRO": "SICRO", "SICRO3": "SICRO", "SICRO 3": "SICRO", "DNIT": "SICRO"}


def normalize_token(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def looks_like_sicro_bank(value: Any) -> bool:
    return bool(SICRO_BANK_RE.search(normalize_token(value)))


def classify_sicro_code(code: Any) -> str:
    text = normalize_token(code).replace(" ", "")
    for name, pattern in SICRO_CODE_PATTERNS.items():
        if pattern.fullmatch(text):
            return name
    return ""


def identify_code_and_bank(first: Any, second: Any) -> Tuple[str, str, Dict[str, Any]]:
    """Identify code/bank even when their columns are inverted.

    SICRO tables may present ``Código | Banco`` in sections A/B and ``Banco | Código``
    in C/D/E/F. We rely on the bank token and code patterns instead of hardcoding the
    visual order.
    """
    a = normalize_token(first)
    b = normalize_token(second)
    a_bank = looks_like_sicro_bank(a)
    b_bank = looks_like_sicro_bank(b)
    a_code = classify_sicro_code(a)
    b_code = classify_sicro_code(b)
    evidence = {"first": a, "second": b, "first_is_bank": a_bank, "second_is_bank": b_bank, "first_code_type": a_code, "second_code_type": b_code}
    if a_bank and b_code:
        return b, a, evidence
    if b_bank and a_code:
        return a, b, evidence
    if b_bank:
        return a, b, evidence
    if a_bank:
        return b, a, evidence
    return a, b, evidence


def section_by_description_header(header: Any) -> str:
    raw = normalize_token(header).lower()
    for section, meta in SICRO_SECTIONS.items():
        if any(h.lower() in raw for h in meta.get("description_headers", [])):
            return section
    return ""


def sicro_config_payload() -> Dict[str, Any]:
    return {
        "bank_aliases": BANK_ALIASES,
        "code_patterns": {k: v.pattern for k, v in SICRO_CODE_PATTERNS.items()},
        "sections": SICRO_SECTIONS,
        "fixed_section_order": ["A", "B", "C", "D", "E", "F"],
    }
