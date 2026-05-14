from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Tuple
import re


def _split_labels(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out: List[str] = []
        for item in value:
            out.extend(_split_labels(item))
        return out
    s = str(value).strip()
    if not s:
        return []
    return [part.strip() for part in re.split(r"[\n;]+", s) if part and part.strip()]


DEFAULT_TABLE_MODELS: Dict[str, Any] = {
    "orcamento_sintetico": {
        "kind": "budget",
        "header_rows_expected": 1,
        "columns": [
            {"canonical": "item_agregador", "labels": ["ITEM"]},
            {"canonical": "codigo", "labels": ["CÓDIGO", "CODIGO", "CÓD.", "COD.", "COD"]},
            {"canonical": "fonte", "labels": ["FONTE", "BANCO"]},
            {"canonical": "descricao", "labels": ["ESPECIFICAÇÕES DOS SERVIÇOS", "ESPECIFICACOES DOS SERVICOS", "DESCRIÇÃO", "DESCRICAO"]},
            {"canonical": "und", "labels": ["UND", "UNIDADE", "UNID", "UN"]},
            {"canonical": "quant", "labels": ["QUANT.", "QUANT", "QTD", "QUANTIDADE"]},
            {"canonical": "custo_unit_sem_bdi", "labels": ["S/ B.D.I", "S/ BDI"]},
            {"canonical": "custo_unit_com_bdi", "labels": ["C/ B.D.I", "C/ BDI"]},
            {"canonical": "custo_parcial", "labels": ["CUSTO PARCIAL", "PARCIAL", "TOTAL PARCIAL"]},
            {"canonical": "custo_total", "labels": ["CUSTO TOTAL", "TOTAL", "VALOR TOTAL"]},
        ],
    },
    "composicoes_sinapi": {
        "kind": "composition",
        "header_rows_expected": 1,
        "first_column_role": "controle_linha",
        "supports_blank_control_cells": True,
        "supports_auxiliares_globais_sem_item": True,
        "columns": [
            {"canonical": "controle_linha", "labels": ["", "ITEM", "COMPOSIÇÃO", "COMPOSICAO", "COMPOSIÇÃO AUXILIAR", "COMPOSICAO AUXILIAR", "AUXILIAR", "INSUMO"]},
            {"canonical": "codigo", "labels": ["CÓDIGO", "CODIGO", "CÓD.", "COD.", "CÓDIGO BANCO"]},
            {"canonical": "banco", "labels": ["BANCO", "FONTE"]},
            {"canonical": "descricao", "labels": ["DESCRIÇÃO", "DESCRICAO", "DESCRI"]},
            {"canonical": "tipo", "labels": ["TIPO"]},
            {"canonical": "und", "labels": ["UND", "UNIDADE", "UNID", "UN"]},
            {"canonical": "quant", "labels": ["QUANT.", "QUANT", "QTD", "QUANTIDADE"]},
            {"canonical": "valor_unit", "labels": ["VALOR UNIT", "VALOR UNITÁRIO", "VALOR UNITARIO", "PREÇO UNITÁRIO", "PRECO UNITARIO"]},
            {"canonical": "total", "labels": ["TOTAL", "CUSTO TOTAL"]},
        ],
    },
    "composicoes_sicro": {
        "kind": "composition_sicro",
        "header_rows_expected": 1,
        "first_column_role": "controle_linha",
        "supports_blank_control_cells": True,
        "supports_auxiliares_globais_sem_item": False,
        "fixed_sections": ["A", "B", "C", "D", "E", "F"],
        "columns": [
            {"canonical": "controle_linha", "labels": ["", "CÓDIGO", "CODIGO", "ITEM"]},
            {"canonical": "codigo", "labels": ["CÓDIGO", "CODIGO"]},
            {"canonical": "descricao", "labels": ["DESCRIÇÃO", "DESCRICAO"]},
            {"canonical": "und", "labels": ["UNIDADE", "UND"]},
            {"canonical": "quant", "labels": ["QUANTIDADE", "QUANT", "QTD"]},
            {"canonical": "valor_unit", "labels": ["CUSTO UNITÁRIO", "CUSTO UNITARIO", "CUSTO HORÁRIO", "CUSTO HORARIO"]},
            {"canonical": "total", "labels": ["CUSTO TOTAL", "TOTAL"]},
        ],
    },
}


def _normalize_column(col: Any) -> Dict[str, Any]:
    if not isinstance(col, dict):
        raise TypeError("Cada coluna do table_model deve ser um objeto.")
    canonical = str(col.get("canonical") or "").strip()
    if not canonical:
        raise TypeError("Cada coluna do table_model precisa de 'canonical'.")
    raw_labels = col.get("labels")
    labels = _split_labels(raw_labels)
    if isinstance(raw_labels, (list, tuple, set)) and any(str(item) == "" for item in raw_labels):
        labels = ["", *[lbl for lbl in labels if lbl != ""]]
    return {
        "canonical": canonical,
        "labels": labels,
        **{k: v for k, v in col.items() if k not in {"canonical", "labels"}},
    }


_MODEL_LIST_FIELDS = {"fixed_sections"}


def _normalize_model(model: Any, *, fallback: Dict[str, Any] | None = None) -> Dict[str, Any]:
    base = deepcopy(fallback or {})
    if model is None:
        model = {}
    if not isinstance(model, dict):
        raise TypeError("Cada table_model deve ser um objeto.")
    merged = {**base, **model}
    columns_raw = merged.get("columns")
    if not isinstance(columns_raw, list) or not columns_raw:
        merged["columns"] = [deepcopy(c) for c in (base.get("columns") or [])]
    else:
        merged["columns"] = [_normalize_column(c) for c in columns_raw]
    merged["kind"] = str(merged.get("kind") or base.get("kind") or "generic").strip() or "generic"
    merged["header_rows_expected"] = int(merged.get("header_rows_expected") or base.get("header_rows_expected") or 1)
    merged["first_column_role"] = str(merged.get("first_column_role") or base.get("first_column_role") or "").strip()
    merged["supports_blank_control_cells"] = bool(merged.get("supports_blank_control_cells", base.get("supports_blank_control_cells", False)))
    merged["supports_auxiliares_globais_sem_item"] = bool(merged.get("supports_auxiliares_globais_sem_item", base.get("supports_auxiliares_globais_sem_item", False)))
    for field in _MODEL_LIST_FIELDS:
        merged[field] = _split_labels(merged.get(field) or base.get(field) or [])
    return merged


_ALIASES = {
    "orcamento": "orcamento_sintetico",
    "budget": "orcamento_sintetico",
    "composicoes": "composicoes_sinapi",
    "composicoes_sinapi_like": "composicoes_sinapi",
    "sinapi_like": "composicoes_sinapi",
    "sicro": "composicoes_sicro",
}


def normalize_table_models(value: Any) -> Dict[str, Any]:
    if value is None:
        return deepcopy(DEFAULT_TABLE_MODELS)
    if not isinstance(value, dict):
        raise TypeError("table_models deve ser um objeto/dicionário.")
    out = deepcopy(DEFAULT_TABLE_MODELS)
    for raw_key, raw_model in value.items():
        key = _ALIASES.get(str(raw_key).strip(), str(raw_key).strip())
        fallback = out.get(key)
        out[key] = _normalize_model(raw_model, fallback=fallback)
    # normalizar defaults também para garantir consistência completa
    for key, model in list(out.items()):
        out[key] = _normalize_model(model, fallback=DEFAULT_TABLE_MODELS.get(key))
    return out


def summarize_table_models(value: Dict[str, Any] | None) -> Dict[str, Any]:
    models = normalize_table_models(value or {})
    summary: Dict[str, Any] = {}
    for key, model in models.items():
        summary[key] = {
            "kind": model.get("kind"),
            "first_column_role": model.get("first_column_role"),
            "supports_blank_control_cells": bool(model.get("supports_blank_control_cells")),
            "supports_auxiliares_globais_sem_item": bool(model.get("supports_auxiliares_globais_sem_item")),
            "columns": [col.get("canonical") for col in (model.get("columns") or [])],
        }
        if model.get("fixed_sections"):
            summary[key]["fixed_sections"] = list(model.get("fixed_sections") or [])
    return summary


def get_table_model(profile: Dict[str, Any] | None, key: str) -> Dict[str, Any]:
    profile = profile or {}
    models = normalize_table_models(profile.get("table_models"))
    resolved_key = _ALIASES.get(str(key).strip(), str(key).strip())
    if resolved_key in models:
        return deepcopy(models[resolved_key])
    return deepcopy(DEFAULT_TABLE_MODELS.get(resolved_key) or {})


def budget_header_aliases_from_profile(profile: Dict[str, Any] | None) -> Dict[str, List[str]]:
    model = get_table_model(profile, "orcamento_sintetico")
    aliases: Dict[str, List[str]] = {}
    for col in model.get("columns") or []:
        canonical = str(col.get("canonical") or "").strip()
        if not canonical:
            continue
        aliases[canonical] = _split_labels(col.get("labels"))
    return aliases
