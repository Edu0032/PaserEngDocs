from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

from app.parser.column_merge_resolver import looks_like_money, looks_like_number, looks_like_unit

_AF_RE = re.compile(r"\bAF_\d{2}/\d{4}(?:_[A-Z]+)?\b", re.IGNORECASE)
_CONTEXT_PATTERNS = [
    r"\bB\.\s*D\.\s*I\.?\b.*$",
    r"\b\d{1,2},\d{2}%\b.*$",
    r"\bN[aã]o\s+Desonerado\s*:\b.*$",
    r"\bEncargos\s+Sociais\b.*$",
    r"\bData[-\s]?base\b.*$",
    r"\bTipo\s+[A-Z]{2,}\s*-\s+.*$",
    r"\b(?:MO\s+sem\s+LS|MO\s+com\s+LS|Valor\s+do\s+BDI|Valor\s+com\s+BDI)\b.*$",
]
_CATEGORY_AFTER_SERVICE_RE = re.compile(
    r"\s+(?:Material|M[aã]o de Obra|Equipamento|Servi[cç]o|Tipo)\s+(?:Tipo\s+)?[A-Z].*$",
    re.IGNORECASE,
)
_REPEATED_CATEGORY_HINTS_BASE = [
    "Instalações", "Instalacoes", "Esquadrias", "Rasgos", "Louças", "Loucas",
    "Chapisco", "Pintura", "Lastro", "Cobertura", "Valas", "Telhamento",
    "Massa Única", "Massa Unica",
]


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace("\xa0", " ")).strip()

def _iter_nested_values(obj: Any, keys: Iterable[str]) -> Iterable[str]:
    if not isinstance(obj, dict):
        return []
    out: List[str] = []
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, (list, tuple, set)):
            out.extend(str(v) for v in value if str(v or "").strip())
        elif isinstance(value, dict):
            out.extend(str(v) for v in value.values() if isinstance(v, str) and v.strip())
    return out


def build_description_noise_terms(context: dict | None = None, config: dict | None = None) -> List[str]:
    """Build document-specific description noise from payload/config, not hardcode."""
    context = context or {}
    config = config or {}
    terms: List[str] = []
    metadata = {}
    for key in ("metadata_extraida_ia", "metadata", "document_metadata", "obra"):
        if isinstance(context.get(key), dict):
            metadata.update(context.get(key) or {})
        if isinstance(config.get(key), dict):
            metadata.update(config.get(key) or {})
    terms.extend(_iter_nested_values(metadata, [
        "orgao_nome", "prefeitura_nome", "contratante_nome", "obra_nome",
        "obra_localizacao", "municipio", "endereco", "data_base_sinapi",
        "data_base_sicro", "objeto", "convenio",
    ]))
    ai_hints = context.get("ai_hints") or config.get("ai_hints") or {}
    header_footer = ai_hints.get("header_footer_profile") if isinstance(ai_hints, dict) else {}
    noise_profile = ai_hints.get("noise_profile") if isinstance(ai_hints, dict) else {}
    for source in (header_footer or {}, noise_profile or {}):
        terms.extend(_iter_nested_values(source, [
            "recurring_headers", "recurring_footers", "budget_headers", "budget_footers",
            "composition_headers", "composition_footers", "extra_noise_keywords",
            "category_pollution_terms",
        ]))
    dg_cfg = config.get("description_guard") if isinstance(config, dict) else {}
    if isinstance(dg_cfg, dict):
        terms.extend(_iter_nested_values(dg_cfg, ["extra_noise_terms", "extra_noise_keywords"]))
    seen = set()
    clean_terms: List[str] = []
    for term in terms:
        term_s = _clean(term)
        if len(term_s) < 3:
            continue
        key = term_s.casefold()
        if key not in seen:
            seen.add(key)
            clean_terms.append(term_s)
    return clean_terms



def _to_float_ptbr(text: Any) -> float | None:
    s = _clean(text).replace("R$", "").strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def strip_noise_from_description(text: Any, *, pollution_terms: Iterable[str] | None = None, context: dict | None = None, config: dict | None = None) -> Tuple[str, List[str]]:
    """Remove text that cannot belong to a composition description.

    The most important guard is AF_XX/YYYY: SINAPI descriptions normally end
    there. If text continues with type/category/header fragments, keep only the
    service description. This is intentionally conservative: it only cuts after
    AF markers or strong document-context/type markers.
    """
    s = _clean(text)
    removed: List[str] = []
    if not s:
        return "", removed

    # Remove explicit recurring header/footer terms wherever they appear.
    dynamic_terms = list(pollution_terms or []) + build_description_noise_terms(context=context, config=config)
    for term in dynamic_terms:
        term_s = _clean(term)
        if not term_s:
            continue
        new = re.sub(re.escape(term_s) + r"\s*[:\-.]*\s*", " ", s, flags=re.IGNORECASE)
        if new != s:
            removed.append(term_s)
            s = _clean(new)

    # Context lines must never be appended to descriptions.
    for pat in _CONTEXT_PATTERNS:
        m = re.search(pat, s, flags=re.IGNORECASE)
        if m:
            removed.append(s[m.start():].strip())
            s = s[:m.start()].rstrip(" -,:;")

    # If a service description has a SINAPI AF marker, keep through the last AF marker.
    # This fixes category/type/header pollution appended after valid descriptions.
    matches = list(_AF_RE.finditer(s))
    if matches:
        last = matches[-1]
        tail = s[last.end():].strip()
        if tail:
            # Cut when the tail is clearly a type/category/header concatenation.
            if any(h.lower() in tail.lower() for h in _REPEATED_CATEGORY_HINTS_BASE) or re.search(r"\b(Tipo|SINAPI|N[aã]o Desonerado|BDI|B\.D\.I\.)\b", tail, flags=re.I):
                removed.append(tail)
                s = s[:last.end()].rstrip(" -,:;")

    # Remove any explicit type/category suffix after financial repair.
    m = _CATEGORY_AFTER_SERVICE_RE.search(s)
    if m and (not matches or m.start() > matches[-1].end()):
        removed.append(s[m.start():].strip())
        s = s[:m.start()].rstrip(" -,:;")

    return _clean(s), removed


def repair_financial_tail(line: Any, *, pollution_terms: Iterable[str] | None = None) -> Dict[str, Any]:
    """Extract unit/quantity/value/total that were appended to descricao.

    This is applied only when one or more financial fields are missing, so it
    cannot overwrite already reliable structured values.
    """
    desc = _clean(getattr(line, "descricao", ""))
    changed = False
    removed: List[str] = []
    if not desc:
        return {"changed": False, "removed": []}

    # Pattern: <description> <UND> <QUANT> <VALOR_UNIT> <TOTAL> [type/noise]
    # Example: OPERADOR ... H 0,0083100 22,92 0,19 Mão de Obra
    pattern = re.compile(
        r"^(?P<desc>.+?)\s+(?P<und>[A-Za-z%²³]{1,8})\s+(?P<quant>[-+]?\d[\d.,]*)\s+(?P<valor>[-+]?\d[\d.,]*)\s+(?P<total>[-+]?\d[\d.,]*)(?:\s+(?P<tail>.+))?$"
    )
    m = pattern.match(desc)
    if m and looks_like_unit(m.group("und")) and looks_like_number(m.group("quant")) and looks_like_money(m.group("valor")) and looks_like_money(m.group("total")):
        needs = any(getattr(line, f, None) in (None, "") for f in ("und", "quant", "valor_unit", "total"))
        if needs:
            line.descricao = _clean(m.group("desc"))
            if getattr(line, "und", "") in (None, ""):
                line.und = _clean(m.group("und"))
            if getattr(line, "quant", None) in (None, ""):
                line.quant = _to_float_ptbr(m.group("quant"))
            if getattr(line, "valor_unit", None) in (None, ""):
                line.valor_unit = _to_float_ptbr(m.group("valor"))
            if getattr(line, "total", None) in (None, ""):
                line.total = _to_float_ptbr(m.group("total"))
            if m.group("tail"):
                removed.append(_clean(m.group("tail")))
            changed = True

    cleaned, noise = strip_noise_from_description(getattr(line, "descricao", ""), pollution_terms=pollution_terms)
    if cleaned != getattr(line, "descricao", ""):
        line.descricao = cleaned
        removed.extend(noise)
        changed = True

    if changed:
        details = dict(getattr(line, "detalhes", {}) or {})
        guard = dict(details.get("description_guard") or {})
        guard["financial_tail_repaired"] = bool(m)
        guard.setdefault("removed_fragments", [])
        guard["removed_fragments"].extend([r for r in removed if r])
        details["description_guard"] = guard
        line.detalhes = details
    return {"changed": changed, "removed": removed}
