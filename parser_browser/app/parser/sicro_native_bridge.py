from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from app.core.schemas import BlocoComposicao, Composicoes, LinhaComposicao

SICRO_NATIVE_VERSION = "v61.0.20-sicro-audit-confidence-boundary"
MONOREPO_SICRO_BRIDGE_VERSION = "v61.0.75-correction-output-contract-and-review-index"


def _as_float_ptbr(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(".", "").replace(",", ".")
    try:
        return float(text)
    except Exception:
        return None


def _canon_bank(bank: Any) -> str:
    s = str(bank or "").strip().upper().replace(" ", "")
    if s in {"SICRO", "SICRO2", "SICRO3", "DNIT"}:
        return "SICRO"
    return str(bank or "").strip().upper()


def _key(code: Any, bank: Any = "SICRO") -> str:
    c = str(code or "").strip().upper().replace(" ", "")
    b = _canon_bank(bank)
    return f"{c}|{b}" if c and b else ""


def _section_public_key(sec: str) -> str:
    return {
        "A": "equipamentos",
        "B": "mao_obra",
        "C": "materiais",
        "D": "atividades_auxiliares",
        "E": "tempos_fixos",
        "F": "momentos_transporte",
    }.get(str(sec or "").upper(), str(sec or ""))




def _clean_row_for_monorepo(sec: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """Keep native SICRO rows clean before integration.

    v61.0.57: do not add friendly/generic aliases in the bridge.  We still keep
    raw native/fallback text fields so the public exporter can map them to the
    proper SICRO section vocabulary using a strict whitelist.
    """
    out = dict(row or {})
    # Keep section rows native/read-only.  Do not carry generic SINAPI-like
    # aliases or previous cascade markers into the public SICRO payload.
    forbidden = {
        "_evidence", "_field_evidence", "_confidence", "raw_trace",
        "_layout_debug", "banco_canonico", "_cascaded_from",
        "sicro_section_totals", "valor_unit", "total", "quant", "und",
        "natureza", "tipo", "banco_coluna",
    }
    # Keep descricao only as last-resort input for older native rows that did
    # not yet rename the section label; public export will not emit descricao.
    for k in forbidden:
        out.pop(k, None)
    return out


def _compact_clean_sicro(clean_comp: Dict[str, Any]) -> Dict[str, Any]:
    sections = dict(clean_comp.get("secoes") or {})
    out: Dict[str, Any] = {}
    principal = clean_comp.get("principal")
    if isinstance(principal, dict) and principal:
        # Keep the native SICRO principal as read-only source of truth for the
        # public export. Later generic/cascade stages must not overwrite these
        # printed SICRO values.
        out["principal"] = dict(principal)
    canonical_sections: Dict[str, Any] = {}
    for sec, sec_data in sections.items():
        public_key = _section_public_key(str(sec))
        rows = [_clean_row_for_monorepo(str(sec), r) for r in list((sec_data or {}).get("linhas") or []) if isinstance(r, dict)]
        if not rows:
            continue
        canonical_sections[str(sec)] = {
            "nome": (sec_data or {}).get("nome") or public_key,
            "public_key": public_key,
            "linhas": rows,
            **({"total_reportado": (sec_data or {}).get("total_reportado")} if (sec_data or {}).get("total_reportado") not in (None, "") else {}),
            **({"validacao_total": (sec_data or {}).get("validacao_total")} if (sec_data or {}).get("validacao_total") else {}),
        }
    # v61.0.20: keep a single non-redundant canonical section tree.
    out["secoes"] = canonical_sections
    if clean_comp.get("resumos"):
        out["resumos"] = clean_comp.get("resumos")
    if clean_comp.get("validacao"):
        out["validacao"] = clean_comp.get("validacao")
    return out




def _line_from_clean_principal(clean_comp: Dict[str, Any]) -> LinhaComposicao | None:
    p = dict(clean_comp.get("principal") or {})
    code = str(p.get("codigo") or "").strip()
    if not code:
        return None
    original_bank = str(p.get("banco") or "SICRO").strip() or "SICRO"
    bank_canon = _canon_bank(original_bank)
    desc = str(p.get("servico") or p.get("descricao") or "").strip()
    und = str(p.get("unidade") or p.get("und") or "").strip()
    quant_src = p.get("quantidade") if p.get("quantidade") not in (None, "") else p.get("quant")
    vu_src = p.get("custo_unitario") if p.get("custo_unitario") not in (None, "") else p.get("valor_unit")
    total_src = p.get("custo_total") if p.get("custo_total") not in (None, "") else p.get("total")
    return LinhaComposicao(
        codigo=code,
        banco=original_bank,
        descricao=desc,
        natureza="",
        tipo=str(p.get("tipo") or "Composição"),
        und=und,
        quant=_as_float_ptbr(quant_src),
        valor_unit=_as_float_ptbr(vu_src),
        total=_as_float_ptbr(total_src),
        banco_coluna=original_bank,
        detalhes={
            "sicro_native_version": SICRO_NATIVE_VERSION,
            "source": "sicro_native_clean_principal",
            "banco_canonico": bank_canon,
            "sicro_principal_original": p,
            "numeric_source": {
                "quant": {"source_text": str(quant_src)} if quant_src not in (None, "") else {},
                "valor_unit": {"source_text": str(vu_src)} if vu_src not in (None, "") else {},
                "total": {"source_text": str(total_src)} if total_src not in (None, "") else {},
            },
        },
    )


def _build_block_from_clean(clean_comp: Dict[str, Any], existing: BlocoComposicao | None = None) -> BlocoComposicao | None:
    principal = _line_from_clean_principal(clean_comp)
    if principal is None:
        return None
    # Official SICRO classification rule: only the item emitted by the native
    # SICRO engine counts.  Never inherit an item from an existing/budget-created
    # legacy block, because that promotes auxiliary/global SICRO blocks to
    # principals and pollutes the final contract.
    item = str((clean_comp.get("principal") or {}).get("item") or clean_comp.get("item") or "").strip()
    pages = [int(p) for p in list(clean_comp.get("paginas") or []) if str(p).isdigit()]
    details = dict(getattr(existing, "detalhes", {}) or {}) if existing is not None else {}
    sicro_payload = _compact_clean_sicro(clean_comp)
    details["sicro"] = sicro_payload
    details["sicro_native"] = {
        "version": SICRO_NATIVE_VERSION,
        "bridge_version": MONOREPO_SICRO_BRIDGE_VERSION,
        "source": "sicro_only_v61_0_20",
        "text_integrity_ok": ((clean_comp.get("metadata") or {}).get("text_integrity_ok") if isinstance(clean_comp.get("metadata"), dict) else None),
    }
    details["origens_extracao"] = sorted(set(list(details.get("origens_extracao") or []) + ["sicro_native_v61_0_20"]))
    details["pagina_inicio"] = min(pages) if pages else details.get("pagina_inicio")
    details["pagina_fim"] = max(pages) if pages else details.get("pagina_fim")
    details["paginas"] = pages or list(details.get("paginas") or [])
    details["status_completude"] = "completo" if all([principal.codigo, principal.banco, principal.descricao, principal.und, principal.quant is not None, principal.valor_unit is not None, principal.total is not None]) else "pendente_revisao"
    details["math_status"] = {
        "status": "sicro_native_validated",
        "strict_sum_validation": False,
        "principal_total": principal.total,
        "native_validation_ok": bool((clean_comp.get("validacao") or {}).get("ok", True)),
    }
    return BlocoComposicao(
        item=item,
        principal=principal,
        composicoes_auxiliares=[],
        insumos=[],
        pagina_inicio=min(pages) if pages else None,
        pagina_fim=max(pages) if pages else None,
        paginas=pages,
        detalhes=details,
    )


def _iter_existing_sicro_keys(comp: Composicoes) -> Iterable[str]:
    for collection in (comp.principais or {}, comp.auxiliares_globais or {}):
        for key in collection.keys():
            if "|" in key and _canon_bank(key.split("|", 1)[1]) == "SICRO":
                yield _key(key.split("|", 1)[0], "SICRO")


def run_sicro_native_for_compositions(pdf_bytes: bytes, start_page: int, end_page: int) -> Dict[str, Any]:
    """Run the final SICRO-only v61.0.20 engine from the monorepo/Pyodide bundle."""
    try:
        from app.sicro_only.sicro_browser_adapter import extract_sicro_from_pdf_file
    except Exception as exc:
        return {"ok": False, "error": {"code": "sicro_native_import_failed", "message": str(exc)}}
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        cfg_path = Path(__file__).resolve().parents[2] / "db" / "sicro_base_config_v61_0_20.json"
        return extract_sicro_from_pdf_file(tmp_path, int(start_page), int(end_page), config_path=cfg_path, keep_raw_trace=False)
    except Exception as exc:
        return {"ok": False, "error": {"code": "sicro_native_failed", "message": str(exc), "type": exc.__class__.__name__}}
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)  # type: ignore[name-defined]
        except Exception:
            pass



def _native_has_item(clean_comp: Dict[str, Any], block: BlocoComposicao | None = None) -> bool:
    """Classify SICRO strictly by the item emitted by the native v20 engine.

    User rule / public contract: SICRO with item = principal; SICRO without
    item = global auxiliary.  Do not use a legacy/existing block item, nor
    whether the code happened to appear in the synthetic budget, because that
    reintroduces the misclassification that put auxiliary SICRO blocks under
    principals.
    """
    p = dict(clean_comp.get("principal") or {})
    item = str(p.get("item") or clean_comp.get("item") or "").strip()
    return bool(item)

def merge_sicro_native_into_composicoes(comp: Composicoes, native_payload: Dict[str, Any]) -> Tuple[Composicoes, Dict[str, Any]]:
    """Prefer v61.0.20 native SICRO blocks over legacy SICRO blocks.

    This keeps SINAPI/PRÓPRIO untouched and replaces/creates only SICRO keys.
    """
    audit: Dict[str, Any] = {
        "enabled": True,
        "version": SICRO_NATIVE_VERSION,
        "ok": bool(native_payload.get("ok")),
        "replaced": [],
        "created_auxiliares": [],
        "created_principais": [],
        "errors": [],
    }
    if not native_payload or not native_payload.get("result"):
        audit["errors"].append(native_payload.get("error") or {"code": "sicro_native_empty"})
        return comp, audit
    clean = native_payload.get("clean_result") or {}
    clean_comps = list(clean.get("composicoes") or []) if isinstance(clean, dict) else []
    if not clean_comps:
        audit["errors"].append({"code": "sicro_native_no_clean_compositions"})
        return comp, audit
    audit["native_clean_keys"] = []

    existing_principals = {_key(k.split("|", 1)[0], "SICRO") for k in comp.principais.keys() if "|" in k and _canon_bank(k.split("|", 1)[1]) == "SICRO"}
    existing_aux = {_key(k.split("|", 1)[0], "SICRO") for k in comp.auxiliares_globais.keys() if "|" in k and _canon_bank(k.split("|", 1)[1]) == "SICRO"}

    for cc in clean_comps:
        p = dict(cc.get("principal") or {})
        key = _key(p.get("codigo"), p.get("banco") or "SICRO")
        if not key:
            continue
        audit["native_clean_keys"].append(key)
        old = (comp.principais.get(key) or comp.auxiliares_globais.get(key))
        block = _build_block_from_clean(cc, old)
        if block is None:
            continue
        # v61.0.23: classification is controlled by the native composition item.
        # If the SICRO composition has an item number, it is principal; if not,
        # it is an auxiliary global.  Do not depend on whether the budget parser
        # happened to pre-create the key.
        if _native_has_item(cc, block):
            comp.principais[key] = block
            comp.auxiliares_globais.pop(key, None)
            if key in existing_principals or old is not None:
                audit["replaced"].append(key)
            else:
                audit["created_principais"].append(key)
        else:
            if key in existing_aux or old is not None:
                audit["replaced"].append(key)
            else:
                audit["created_auxiliares"].append(key)
            comp.auxiliares_globais[key] = block
            comp.principais.pop(key, None)
    meta = dict((native_payload.get("result") or {}).get("metadata") or {})
    audit.update({
        "native_total_composicoes": int(meta.get("total_composicoes") or len(clean_comps)),
        "text_integrity_ok": bool(meta.get("text_integrity_ok", True)),
        "text_warnings": int(meta.get("text_warnings") or 0),
        "text_repairs_applied": int(meta.get("text_repairs_applied") or 0),
        "confidence_avg": meta.get("confidence_avg"),
        "confidence_min": meta.get("confidence_min"),
    })
    return comp, audit
