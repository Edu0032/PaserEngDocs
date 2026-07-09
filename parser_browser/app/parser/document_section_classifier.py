from __future__ import annotations

"""Document section classifier for physical evidence tuning (v61.0.46).

The parser should not treat every code+banco occurrence as the same kind of
proof.  In DERACRE-like PDFs the same code can appear in the synthetic budget,
calculation memory, analytic compositions, schedule, BDI and ABC curve.  This
module gives the Physical Evidence Index a small, safe section-aware policy:
structured table evidence is strong inside real budget/composition sections;
calculation memory is useful mainly for quantities/context; ABC/BDI/schedule are
mostly diagnostic and should not overwrite public price fields.
"""

import re
import unicodedata
from typing import Any, Dict, Iterable, List

VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _clean(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.upper()


def classify_document_section(page_text: str, *, page_num: int | None = None, in_declared_range: bool = False) -> Dict[str, Any]:
    """Classify one page into a budget-document section.

    The classifier is intentionally conservative and keyword-driven so it works
    in Pyodide without ML dependencies.  Unknown pages are still usable as raw
    evidence but with lower public-write permissions.
    """
    raw = _clean(page_text)
    text = _norm(raw)
    section = "unknown"
    confidence = 0.35
    if "ANEXO 1" in text and "ORCAMENTO SINTETICO" in text:
        section, confidence = "orcamento_sintetico", 0.98
    elif "ANEXO 2" in text and "MEMORIA DE CALCULO" in text:
        section, confidence = "memoria_calculo", 0.98
    elif "ANEXO 3" in text and ("COMPOSICOES" in text or "COMPOSICAO" in text):
        section, confidence = "composicoes_analiticas", 0.98
    elif "ANEXO 4" in text and "CRONOGRAMA" in text:
        section, confidence = "cronograma_fisico_financeiro", 0.98
    elif "ANEXO 5" in text and "BDI" in text:
        section, confidence = "composicao_bdi", 0.98
    elif "CURVA ABC" in text or "ANEXO 7" in text:
        section, confidence = "curva_abc", 0.96
    elif "CODIGO BANCO DESCRICAO UND QUANT" in text and "VALOR UNIT" in text and "COMPOSICAO" in text:
        section, confidence = "composicoes_analiticas", 0.90
    elif "ITEM CODIGO FONTE ESPECIFICACOES DOS SERVICOS" in text and "CUSTO UNITARIO" in text:
        section, confidence = "orcamento_sintetico", 0.92
    elif in_declared_range:
        section, confidence = "declared_range_unknown_layout", 0.62
    return {
        "version": VERSION,
        "page": page_num,
        "section": section,
        "confidence": confidence,
        "raw_title_hint": _title_hint(raw),
    }


def _title_hint(raw: str) -> str:
    for line in [ln.strip() for ln in raw.splitlines() if ln.strip()]:
        n = _norm(line)
        if "ANEXO" in n or "ORCAMENTO SINTETICO" in n or "MEMORIA DE CALCULO" in n or "CURVA ABC" in n:
            return line[:180]
    return ""


_SECTION_ALLOWED_FIELDS = {
    "orcamento_sintetico": {"descricao", "especificacao", "und", "quant", "custo_unitario_sem_bdi", "custo_unitario_com_bdi", "custo_parcial", "custo_total"},
    "composicoes_analiticas": {"descricao", "especificacao", "und", "quant", "valor_unit", "total"},
    # Calculation memory can confirm identity, description, unit and measured
    # quantity. It must not overwrite prices/totals because its columns are
    # coefficients/dimensions/partial quantities, not budget prices.
    "memoria_calculo": {"descricao", "especificacao", "und", "quant"},
    # ABC/schedule/BDI are diagnostic: they can help locate a code but should not
    # write public fields automatically.
    "curva_abc": set(),
    "cronograma_fisico_financeiro": set(),
    "composicao_bdi": set(),
    "declared_range_unknown_layout": {"descricao", "especificacao", "und", "quant", "valor_unit", "total", "custo_unitario_sem_bdi", "custo_unitario_com_bdi", "custo_parcial", "custo_total"},
    "unknown": {"descricao", "especificacao", "und"},
}


def section_evidence_policy(section: str, *, source_zone: str = "") -> Dict[str, Any]:
    section = str(section or "unknown")
    allowed = set(_SECTION_ALLOWED_FIELDS.get(section, _SECTION_ALLOWED_FIELDS["unknown"]))
    if section == "orcamento_sintetico":
        weight = 1.00
        policy = "budget_fields_authoritative"
    elif section == "composicoes_analiticas":
        weight = 0.98
        policy = "composition_fields_authoritative"
    elif section == "memoria_calculo":
        weight = 0.78
        policy = "quantity_and_context_only"
    elif section in {"curva_abc", "cronograma_fisico_financeiro", "composicao_bdi"}:
        weight = 0.35
        policy = "diagnostic_context_only"
    elif section == "declared_range_unknown_layout":
        weight = 0.90
        policy = "declared_range_structured_fallback"
    else:
        weight = 0.55
        policy = "raw_context_only"
    return {
        "section": section,
        "source_zone": source_zone,
        "policy": policy,
        "weight": weight,
        "repair_allowed_fields": sorted(allowed),
        "diagnostic_only": not bool(allowed),
    }


def field_allowed_by_section(field: str, section: str) -> bool:
    return str(field or "") in _SECTION_ALLOWED_FIELDS.get(str(section or "unknown"), _SECTION_ALLOWED_FIELDS["unknown"])


def summarize_section_counts(page_sections: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for rec in page_sections or []:
        sec = str((rec or {}).get("section") or "unknown")
        counts[sec] = counts.get(sec, 0) + 1
    return counts
