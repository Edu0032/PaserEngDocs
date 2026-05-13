from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

SYSTEM_KEYS = {
    "_evidence", "_field_evidence", "_confidence", "_layout", "_recovery",
    "raw_trace", "multiengine", "fusion", "two_pass", "contract_audit",
}

SECTION_PUBLIC_KEYS = {
    "A": "equipamentos",
    "B": "mao_obra",
    "C": "materiais",
    "D": "atividades_auxiliares",
    "E": "tempos_fixos",
    "F": "momentos_transporte",
}

SECTION_NAMES = {
    "A": "Equipamentos",
    "B": "Mão de Obra",
    "C": "Materiais",
    "D": "Atividades Auxiliares",
    "E": "Tempos Fixos",
    "F": "Momentos de Transporte",
}


def _clean_obj(obj: Any) -> Any:
    if isinstance(obj, list):
        return [_clean_obj(x) for x in obj]
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if k in SYSTEM_KEYS or str(k).startswith("_"):
                continue
            out[k] = _clean_obj(v)
        return out
    return obj



def _friendly_row(row: Dict[str, Any], letter: str) -> Dict[str, Any]:
    # v61.0.23: clean view is non-destructive for SICRO domain columns.
    # It may add aliases, but never replaces/removes the original column that
    # the native engine extracted.
    out = _clean_obj(row)
    if letter in {"C", "D", "E", "F"} and "custo_horario" in out and "custo" not in out:
        out["custo"] = out.get("custo_horario")
    return out

def _section_rows(comp: Dict[str, Any], letter: str) -> List[Dict[str, Any]]:
    secoes = comp.get("secoes") or {}
    if letter in secoes:
        return secoes[letter].get("linhas") or []
    public = (comp.get("sicro") or {}).get(SECTION_PUBLIC_KEYS.get(letter, letter)) or []
    return public


def make_clean_readable(result: Dict[str, Any]) -> Dict[str, Any]:
    """Build a clean, human-readable JSON without system/debug evidence.

    The raw browser result remains the audit/debug artifact. This clean artifact is
    meant for visual inspection and for future Lovable previews: principal fields,
    A-F sections, summaries and validation status only.
    """
    metadata = result.get("metadata") or {}
    clean: Dict[str, Any] = {
        "metadata": {
            "version": metadata.get("version"),
            "pipeline_version": metadata.get("pipeline_version"),
            "mode": metadata.get("mode"),
            "page_range": metadata.get("page_range"),
            "total_composicoes": metadata.get("total_composicoes"),
            "total_issues": metadata.get("total_issues", 0),
            "total_contract_issues": metadata.get("total_contract_issues", 0),
            "text_integrity_ok": metadata.get("text_integrity_ok"),
            "text_warnings": metadata.get("text_warnings", 0),
            "text_repairs_applied": metadata.get("text_repairs_applied", 0),
            "text_audit_summary": metadata.get("text_audit_summary"),
            "document_consistency_ok": metadata.get("document_consistency_ok"),
            "document_consistency_warnings": metadata.get("document_consistency_warnings", 0),
            "document_consistency_issues": metadata.get("document_consistency_issues", 0),
            "synthetic_reference_count": metadata.get("synthetic_reference_count", 0),
            "confidence_avg": metadata.get("confidence_avg"),
            "confidence_min": metadata.get("confidence_min"),
            "actual_passes": metadata.get("actual_passes"),
            "selected_profile": metadata.get("selected_profile"),
        },
        "composicoes": [],
    }
    for key, comp in sorted((result.get("composicoes") or {}).items()):
        principal = _clean_obj(comp.get("principal") or {})
        principal.pop("validacao", None)
        item = {
            "chave": key,
            "paginas": comp.get("paginas") or [],
            "principal": principal,
            "secoes": {},
            "resumos": _clean_obj(comp.get("resumos") or {}),
            "validacao": _clean_obj(comp.get("validacao") or {}),
        }
        # row validations are verbose; keep only final status and issues in clean view.
        if isinstance(item["validacao"], dict):
            item["validacao"].pop("row_validations", None)
            item["validacao"].pop("issues_after_fusion", None)
        ti = comp.get("text_integrity") or {}
        if ti:
            item["text_integrity"] = {"ok": ti.get("ok", True), "repairs_count": len(ti.get("repairs_applied") or []), "warnings_count": len(ti.get("warnings") or [])}
        dc = comp.get("document_consistency") or {}
        if dc:
            item["document_consistency"] = _clean_obj(dc)
        for letter in "ABCDEF":
            rows = _section_rows(comp, letter)
            if not rows:
                continue
            item["secoes"][letter] = {
                "nome": SECTION_NAMES[letter],
                "public_key": SECTION_PUBLIC_KEYS[letter],
                "linhas": [_friendly_row(r, letter) for r in rows],
            }
            # Keep section total in the clean view when available.
            sec_data = (comp.get("secoes") or {}).get(letter) or {}
            if sec_data.get("total_reportado") is not None:
                item["secoes"][letter]["total_reportado"] = sec_data.get("total_reportado")
            if sec_data.get("validacao_total") is not None:
                item["secoes"][letter]["validacao_total"] = _clean_obj(sec_data.get("validacao_total"))
        clean["composicoes"].append(item)
    return clean


def make_clean_summary_markdown(result: Dict[str, Any]) -> str:
    clean = make_clean_readable(result)
    lines = ["# Resultado SICRO limpo", ""]
    md = clean.get("metadata") or {}
    lines.append(f"- Composições: {md.get('total_composicoes')}")
    lines.append(f"- Issues: {md.get('total_issues')}")
    lines.append(f"- Contract issues: {md.get('total_contract_issues')}")
    lines.append(f"- Texto OK: {md.get('text_integrity_ok')}")
    lines.append(f"- Alertas de texto: {md.get('text_warnings')}")
    lines.append(f"- Reparos de texto: {md.get('text_repairs_applied')}")
    lines.append(f"- Consistência documental OK: {md.get('document_consistency_ok')}")
    lines.append(f"- Avisos documentais: {md.get('document_consistency_warnings')}")
    lines.append(f"- Passagens: {md.get('actual_passes')}")
    lines.append("")
    for comp in clean.get("composicoes") or []:
        p = comp.get("principal") or {}
        sections = {k: len((v or {}).get("linhas") or []) for k, v in (comp.get("secoes") or {}).items()}
        lines.append(f"## {p.get('codigo')} | {p.get('banco')}")
        lines.append(f"- Serviço: {p.get('servico')}")
        lines.append(f"- Unidade: {p.get('unidade')} | Valor unitário: {p.get('custo_unitario')} | Total: {p.get('custo_total')}")
        lines.append(f"- Seções: {sections}")
        lines.append(f"- Validação OK: {(comp.get('validacao') or {}).get('ok')}")
        lines.append("")
    return "\n".join(lines)


def make_clean_audit(result: Dict[str, Any]) -> Dict[str, Any]:
    """Small audit artifact for text/math/contract checks without raw bboxes."""
    metadata = result.get("metadata") or {}
    comps = result.get("composicoes") or {}
    items: List[Dict[str, Any]] = []
    for key, comp in sorted(comps.items()):
        p = comp.get("principal") or {}; ti = comp.get("text_integrity") or {}; val = comp.get("validacao") or {}
        items.append({
            "chave": key, "codigo": p.get("codigo"), "banco": p.get("banco"),
            "matematica_ok": val.get("ok", True), "texto_ok": val.get("texto_ok", ti.get("ok", True)),
            "text_repairs_count": len(ti.get("repairs_applied") or val.get("text_repairs_applied") or []),
            "text_warnings_count": len(ti.get("warnings") or val.get("text_warnings") or []),
            "text_repairs": _clean_obj(ti.get("repairs_applied") or val.get("text_repairs_applied") or []),
            "text_warnings": _clean_obj(ti.get("warnings") or val.get("text_warnings") or []),
            "document_consistency": _clean_obj(comp.get("document_consistency") or {}),
        })
    return {"metadata": {"version": metadata.get("version"), "pipeline_version": metadata.get("pipeline_version"), "total_composicoes": metadata.get("total_composicoes"), "total_issues": metadata.get("total_issues", 0), "total_contract_issues": metadata.get("total_contract_issues", 0), "text_integrity_ok": metadata.get("text_integrity_ok"), "text_warnings": metadata.get("text_warnings", 0), "text_repairs_applied": metadata.get("text_repairs_applied", 0), "text_audit_summary": metadata.get("text_audit_summary"), "document_consistency_ok": metadata.get("document_consistency_ok"), "document_consistency_warnings": metadata.get("document_consistency_warnings", 0), "document_consistency_issues": metadata.get("document_consistency_issues", 0), "synthetic_reference_count": metadata.get("synthetic_reference_count", 0)}, "document_consistency": _clean_obj(result.get("document_consistency") or {}), "composicoes": items}
