from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

from app.parser.sicro_engine import resolve_code_bank as _engine_resolve_code_bank, classify_code_token as _engine_classify_code_token, looks_like_bank as _engine_looks_like_bank, load_sicro_engine_config

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


SICRO_KNOWLEDGE_BASE: Dict[str, Any] = {
    "source_basis": [
        "DNIT - Manuais de Custos de Infraestrutura de Transportes/SICRO",
        "SICRO 2 legado mantido para contratos ativos",
    ],
    "units": {
        "fundamentais": ["h", "m", "m²", "m³", "kg", "t", "un", "und", "mês", "mes", "%"],
        "transporte": ["t.km", "tkm", "m³.km", "m3xkm", "m³xkm", "m3.km"],
        "produtividade": ["m³/h", "m2/h", "m²/h", "t/h", "km/h", "un/h"],
        "sicro_por_secao": {
            "A": ["h"],
            "B": ["h"],
            "C": ["kg", "t", "m", "m²", "m³", "l", "un"],
            "D": ["m", "m²", "m³", "kg", "t", "un", "h"],
            "E": ["t", "m³", "kg", "un"],
            "F": ["t.km", "tkm", "m³.km", "m3xkm", "m³xkm"],
        },
    },
    "method_variables": {
        "producao_equipe": {"aliases": ["Produção de Equipe", "Produção da Equipe", "Pr"], "kind": "summary_numeric"},
        "fic": {"aliases": ["Fator de Influencia da Chuva", "Fator de Influência da Chuva", "FIC"], "kind": "summary_factor"},
        "fit": {"aliases": ["Fator de Interferência do Tráfego", "FIT"], "kind": "summary_factor"},
        "custo_horario_execucao": {"aliases": ["Custo Horário de Execução"], "kind": "summary_money"},
        "custo_unitario_execucao": {"aliases": ["Custo Unitário de Execução"], "kind": "summary_money"},
        "valor_com_bdi": {"aliases": ["Valor com BDI"], "kind": "summary_money"},
    },
    "legacy_code_patterns": {
        "sicro2_alfanumerico_espacado": r"^\d\s+[A-Z]\s+\d{2}\s+\d{3}\s+\d{2}$",
        "sicro_atual_numerico_7": r"^\d{7}$",
        "equipamento": r"^E\d{3,5}$",
        "material": r"^M\d{3,5}$",
        "mao_obra": r"^P\d{3,5}$",
    },
    "transport_markers": ["DMT", "LN", "RP", "P", "t.km", "tkm", "m³.km", "m3xkm"],
    "row_type_aliases": {
        "P": "equipamento_produtivo",
        "I": "equipamento_improdutivo",
        "MO": "mao_obra",
        "MAT": "material",
        "AUX": "atividade_auxiliar",
    },
}


def normalize_token(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def looks_like_sicro_bank(value: Any) -> bool:
    return _engine_looks_like_bank(value)


def classify_sicro_code(code: Any) -> str:
    name = _engine_classify_code_token(code, load_sicro_engine_config())
    if name == "composicao_atual_7_digitos":
        return "composicao_principal"
    if name == "sicro2_legado_espacado":
        return "composicao_legada"
    return name


def identify_code_and_bank(first: Any, second: Any) -> Tuple[str, str, Dict[str, Any]]:
    """Identify code/bank even when their columns are inverted using the SICRO Engine."""
    return _engine_resolve_code_bank(first, second, load_sicro_engine_config())


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
        "knowledge_base": SICRO_KNOWLEDGE_BASE,
    }
