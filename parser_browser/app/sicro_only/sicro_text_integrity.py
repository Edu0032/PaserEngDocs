from __future__ import annotations

"""Text integrity and description repair for SICRO extraction.

Pyodide-safe post-processing: repairs wrapped/truncated technical text using
reference descriptions and raw PyMuPDF trace. It never changes numeric fields.
"""

import re
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .sicro_engine import clean, key, normalize_code

TEXT_FIELD_BY_SECTION = {
    "A": "equipamento", "B": "mao_obra", "C": "material",
    "D": "atividade_auxiliar", "E": "tempo_fixo", "F": "momento_transporte",
}
SUMMARY_STOP_KEYS = (
    "CUSTO TOTAL", "CUSTO HORARIO", "CUSTO HORÁRIO", "MO SEM LS", "VALOR DO BDI", "VALOR COM BDI",
    "CODIGO BANCO DESCRICAO", "CÓDIGO BANCO DESCRIÇÃO", "DERACRE PAGINA", "SEDUR PAGINA", "RIO BRANCO",
)


def _norm_code(value: Any) -> str:
    return normalize_code(str(value or ""))


def has_suspicious_text_end(value: Any) -> bool:
    txt = clean(value)
    if not txt:
        return False
    k = key(txt)
    if k.endswith((" COM", " CARGA COM", " CARGA E", " DE", " DA", " DO", " DAS", " DOS", " EM", " PARA", " POR", " E")):
        return True
    if txt.endswith("-"):
        return True
    if "CAMINHAO CARROCERIA COM" in k and "CAPACIDADE" not in k:
        return True
    if "CARGA COM" in k and "CARREGADEIRA" not in k and "BASCULANTE" in k:
        return True
    return False


def _score_text(value: str) -> float:
    value = clean(value)
    if not value:
        return 0.0
    score = min(0.55, len(value.split()) * 0.018) + min(0.20, len(value) * 0.0015)
    if has_suspicious_text_end(value):
        score -= 0.30
    if re.search(r"\b\d+(?:,\d+)?\s*(?:m³|m2|m²|t|kg|kW|l)\b", value, flags=re.I):
        score += 0.08
    return max(0.0, min(1.0, score))


def _strip_after_summary_noise(text: str) -> str:
    out = clean(text)
    if not out:
        return out
    positions: List[int] = []
    for marker in SUMMARY_STOP_KEYS:
        m = re.search(re.escape(marker).replace("\\ ", r"\s+"), out, flags=re.I)
        if m and m.start() > 0:
            positions.append(m.start())
    if positions:
        out = out[: min(positions)]
    return clean(re.sub(r"\s+=>\s*$", "", out))



def clean_trace_boundaries(result: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """Cut raw trace event text at summary/header/footer boundaries.

    The final materializer was already protected against summary noise, but the
    raw debug artifact could still show huge lines mixing row text, totals,
    footer and next-header labels. This cleaner keeps raw_trace useful and lowers
    the chance that a future repair consumes footer numbers as text.
    """
    changes = 0
    for comp in (result.get("composicoes") or {}).values():
        for ev in comp.get("raw_trace") or []:
            txt = ev.get("text")
            if not txt:
                continue
            cleaned = _strip_after_summary_noise(str(txt))
            if cleaned and cleaned != clean(txt):
                ev.setdefault("text_original", txt)
                ev["text"] = cleaned
                ev["boundary_cleaned"] = True
                changes += 1
    result.setdefault("metadata", {})["trace_boundary_cleaned_count"] = changes
    return result, changes

def build_reference_registry(result: Dict[str, Any]) -> Dict[str, Any]:
    by_code: Dict[str, Dict[str, Any]] = {}
    material_by_code: Dict[str, str] = {}
    for comp_key, comp in (result.get("composicoes") or {}).items():
        p = comp.get("principal") or {}
        code = _norm_code(p.get("codigo")); bank = clean(p.get("banco")); desc = clean(p.get("servico"))
        if code and desc:
            item = {"codigo": code, "banco": bank, "servico": desc, "source": "principal", "composition_key": comp_key}
            by_code[code] = item
            if bank:
                by_code[f"{code}|{bank}"] = item
        for row in (((comp.get("secoes") or {}).get("C") or {}).get("linhas") or []):
            mcode = _norm_code(row.get("codigo")); mdesc = clean(row.get("material"))
            if mcode and mdesc and len(mdesc) > len(material_by_code.get(mcode, "")):
                material_by_code[mcode] = mdesc
    return {"by_code": by_code, "material_by_code": material_by_code}


def _trace_events(comp: Dict[str, Any], event: str) -> List[Dict[str, Any]]:
    return [ev for ev in (comp.get("raw_trace") or []) if ev.get("event") == event and ev.get("text")]


def _find_trace_for_row(comp: Dict[str, Any], event: str, row: Dict[str, Any], code_fields: Iterable[str]) -> Optional[str]:
    wanted = [_norm_code(row.get(f)) for f in code_fields]
    wanted = [w for w in wanted if w]
    if not wanted:
        return None
    for mode_all in (True, False):
        for ev in _trace_events(comp, event):
            txt = clean(ev.get("text")); flat = re.sub(r"\s+", "", txt).upper()
            checks = [w.replace(" ", "").upper() in flat for w in wanted]
            if (all(checks) if mode_all else any(checks)):
                return txt
    return None


def _extract_e_desc_from_trace(trace: str) -> Optional[str]:
    text = clean(trace)
    m = re.match(r"^Tempo\s+Fixo\s+SICRO\s*(?:2|3)?\s+M\s*\d{3,5}\s+(?P<body>.+)$", text, flags=re.I)
    if not m:
        return None
    body = m.group("body")
    code = re.search(r"(?<![,.\d])\d{7}(?![,.\d])", body)
    if not code:
        return None
    desc1 = clean(body[:code.start()])
    rest = body[code.end():]
    tail = re.match(r"\s*[-–—]?\s*\d+(?:\.\d{3})*,\d+\s+\S{1,8}\s+\d+(?:\.\d{3})*,\d+\s+\d+(?:\.\d{3})*,\d+\s*(?P<cont>.*)$", rest)
    cont = _strip_after_summary_noise(tail.group("cont")) if tail else ""
    return clean(f"{desc1} {cont}") if cont else (desc1 or None)


def _extract_f_desc_from_trace(trace: str) -> Optional[str]:
    text = clean(trace.replace("Momento de Transporte", "Momento de"))
    m = re.match(r"^(?:Momento\s+de\s+)?SICRO\s*(?:2|3)?\s+M\s*\d{3,5}\s+(?P<body>.+)$", text, flags=re.I)
    if not m:
        return None
    body = m.group("body")
    first_code = re.search(r"(?<![,.\d])\d{7}(?![,.\d])", body)
    if not first_code:
        return None
    prefix = body[:first_code.start()]
    qtys = list(re.finditer(r"\d+(?:\.\d{3})*,\d+\s+tkm\b", prefix, flags=re.I))
    if not qtys:
        return None
    desc = clean(prefix[:qtys[-1].start()])
    rest = body[first_code.start():]
    cont = ""
    mt = re.search(r"\bTransporte\b\s+(?P<cont>.+)$", rest, flags=re.I)
    if mt:
        tail = mt.group("cont")
        stops = []
        for pat in (r"\b\d+,\d{3}\b", r"\bR\$\b", r"\bCusto\s+total\b", r"\bMO\s+sem\s+LS\b", r"\bCódigo\s+Banco\b"):
            sm = re.search(pat, tail, flags=re.I)
            if sm: stops.append(sm.start())
        if stops:
            tail = tail[:min(stops)]
        cont = _strip_after_summary_noise(tail)
    if cont and cont not in desc:
        desc = clean(f"{desc} {cont}")
    return desc or None


def _choose(current: str, candidates: List[Tuple[str, str]]) -> Tuple[str, str, bool]:
    current = clean(current)
    best_value, best_source, best_score = current, "current", _score_text(current)
    for source, value in candidates:
        value = clean(value)
        if not value:
            continue
        score = _score_text(value)
        if current and current in value:
            score += 0.20
        ck, vk = key(current), key(value)
        if ck and vk.startswith(ck[:min(len(ck), 30)]):
            score += 0.12
        if has_suspicious_text_end(current) and not has_suspicious_text_end(value):
            score += 0.35
        if len(value) > len(current) + 8:
            score += 0.10
        if score > best_score:
            best_value, best_source, best_score = value, source, score
    return best_value, best_source, best_value != current


def _repair_row(comp: Dict[str, Any], section: str, row: Dict[str, Any], registry: Dict[str, Any], repairs: List[Dict[str, Any]], warnings: List[Dict[str, Any]]) -> None:
    field = TEXT_FIELD_BY_SECTION.get(section)
    if not field or field not in row:
        return
    current = clean(row.get(field))
    candidates: List[Tuple[str, str]] = []
    if section == "E":
        ref = (registry.get("by_code") or {}).get(_norm_code(row.get("codigo")))
        if ref and ref.get("servico"):
            candidates.append(("reference_registry", ref["servico"]))
        trace = _find_trace_for_row(comp, "row_E", row, ["insumo", "codigo"])
        if trace:
            desc = _extract_e_desc_from_trace(trace)
            if desc: candidates.append(("raw_trace_reflow", desc))
    elif section == "F":
        trace = _find_trace_for_row(comp, "row_F", row, ["insumo"])
        if trace:
            desc = _extract_f_desc_from_trace(trace)
            if desc: candidates.append(("raw_trace_reflow", desc))
    selected, source, changed = _choose(current, candidates)
    if changed:
        row[field] = selected
        row.setdefault("_text_repair", []).append({"field": field, "source": source, "before": current, "after": selected})
        repairs.append({"composition": (comp.get("principal") or {}).get("codigo"), "section": section, "row_code": row.get("codigo") or row.get("insumo"), "field": field, "source": source, "before": current, "after": selected})
    if has_suspicious_text_end(clean(row.get(field))):
        warnings.append({"composition": (comp.get("principal") or {}).get("codigo"), "section": section, "row_code": row.get("codigo") or row.get("insumo"), "field": field, "type": "text_maybe_incomplete", "value": clean(row.get(field))})


def repair_text_integrity(result: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(result)
    out, boundary_cleaned = clean_trace_boundaries(out)
    registry = build_reference_registry(out)
    repairs: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    for comp in (out.get("composicoes") or {}).values():
        r0, w0 = len(repairs), len(warnings)
        for section, data in (comp.get("secoes") or {}).items():
            for row in (data or {}).get("linhas") or []:
                _repair_row(comp, section, row, registry, repairs, warnings)
        public = comp.setdefault("sicro", {})
        for section, data in (comp.get("secoes") or {}).items():
            pk = (data or {}).get("public_key")
            if pk: public[pk] = (data or {}).get("linhas") or []
        comp["text_integrity"] = {"ok": len(warnings) == w0, "repairs_applied": repairs[r0:], "warnings": warnings[w0:]}
        comp.setdefault("validacao", {})["texto_ok"] = len(warnings) == w0
        comp["validacao"]["text_warnings"] = warnings[w0:]
        comp["validacao"]["text_repairs_applied"] = repairs[r0:]
    out.setdefault("metadata", {})["text_repairs_applied"] = len(repairs)
    out["metadata"]["text_warnings"] = len(warnings)
    out["metadata"]["text_integrity_ok"] = not warnings
    repair_sources: Dict[str, int] = {}
    for repair in repairs:
        repair_sources[str(repair.get("source") or "unknown")] = repair_sources.get(str(repair.get("source") or "unknown"), 0) + 1
    text_audit_summary = {
        "text_integrity_ok": not warnings,
        "warnings_open": len(warnings),
        "repairs_total": len(repairs),
        "repairs_by_source": repair_sources,
        "trace_boundary_cleaned": boundary_cleaned,
        "suspicious_endings": len(warnings),
        "lost_units_detected": 0,
    }
    out["metadata"]["text_audit_summary"] = text_audit_summary
    out["text_integrity"] = {"ok": not warnings, "repairs_applied": repairs, "warnings": warnings, "summary": text_audit_summary}
    return out


def make_text_audit_report(result: Dict[str, Any]) -> Dict[str, Any]:
    meta = result.get("metadata") or {}; audit = result.get("text_integrity") or {}
    return {
        "version": meta.get("version"),
        "pipeline_version": meta.get("pipeline_version"),
        "composition_count": meta.get("total_composicoes"),
        "math_issues": meta.get("total_issues", 0),
        "contract_issues": meta.get("total_contract_issues", 0),
        "text_integrity_ok": meta.get("text_integrity_ok", audit.get("ok")),
        "text_repairs_applied": meta.get("text_repairs_applied", len(audit.get("repairs_applied") or [])),
        "text_warnings": meta.get("text_warnings", len(audit.get("warnings") or [])),
        "summary": meta.get("text_audit_summary") or audit.get("summary") or {},
        "repairs": audit.get("repairs_applied") or [],
        "warnings": audit.get("warnings") or []
    }
