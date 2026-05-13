from __future__ import annotations

import json
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from .sicro_audit import audit_extraction_contract
from .sicro_engine import SicroEngine, load_config
from .sicro_twopass import SicroTwoPassPipeline
from .sicro_clean import make_clean_readable, make_clean_summary_markdown, make_clean_audit
from .sicro_text_integrity import make_text_audit_report
from .sicro_words_cache import clear_global_words_cache, words_cache_report


def _is_js_nullish(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text in {"", "None", "none", "null", "undefined", "JsNull"} or text.lower() in {"auto", "nan"}


def _optional_int(value: Any, default: int | None = None) -> int | None:
    if _is_js_nullish(value):
        return default
    try:
        return int(float(str(value)))
    except Exception:
        return default


def _optional_bool(value: Any, default: bool = False) -> bool:
    if _is_js_nullish(value):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "sim", "yes", "y"}


def result_signature(result: Dict[str, Any]) -> Dict[str, Any]:
    """Build a stable semantic signature for CPython x Pyodide parity.

    We intentionally do not compare raw bboxes byte-for-byte because different
    engines/browsers can produce tiny float differences. We compare the important
    SICRO semantics: composition codes, section counts, issue counts and row math.
    """
    comps = result.get("composicoes") or {}
    items: Dict[str, Any] = {}
    for comp_key, comp in sorted(comps.items()):
        sections = comp.get("secoes") or {}
        section_counts = {sec: len((data or {}).get("linhas") or []) for sec, data in sorted(sections.items())}
        principal = comp.get("principal") or {}
        row_math = []
        for sec, data in sorted(sections.items()):
            for row in (data or {}).get("linhas") or []:
                val = row.get("validacao") or {}
                row_math.append({
                    "section": sec,
                    "code": row.get("codigo") or row.get("insumo") or "",
                    "ok": bool(val.get("ok", True)),
                    "calculated": val.get("calculated"),
                    "expected": val.get("expected"),
                })
        items[comp_key] = {
            "codigo": principal.get("codigo"),
            "banco": principal.get("banco"),
            "unidade": principal.get("unidade"),
            "custo_unitario": principal.get("custo_unitario"),
            "sections": section_counts,
            "validacao_ok": bool((comp.get("validacao") or {}).get("ok", False)),
            "row_math": row_math,
        }
    return {
        "composition_count": len(comps),
        "composition_keys": sorted(comps.keys()),
        "metadata": {
            "total_issues": (result.get("metadata") or {}).get("total_issues", 0),
            "total_contract_issues": (result.get("metadata") or {}).get("total_contract_issues", 0),
            "mode": (result.get("metadata") or {}).get("mode"),
            "selected_profile": (result.get("metadata") or {}).get("selected_profile"),
            "text_integrity_ok": (result.get("metadata") or {}).get("text_integrity_ok"),
            "text_warnings": (result.get("metadata") or {}).get("text_warnings", 0),
        },
        "compositions": items,
    }


def extract_sicro_from_pdf_file(
    pdf_path: str | Path,
    start_page: int,
    end_page: int,
    config_path: str | Path | None = None,
    max_passes: int = 3,
    force_passes: int | None = None,
    keep_raw_trace: bool = False,
) -> Dict[str, Any]:
    started = time.perf_counter()
    clear_global_words_cache()
    root = Path(__file__).resolve().parents[1]
    cfg_path = Path(config_path) if config_path else root / "config" / "base_config.json"
    config = load_config(cfg_path)
    engine = SicroEngine(config)
    max_passes = _optional_int(max_passes, 3) or 3
    force_passes = _optional_int(force_passes, None)
    return_raw_trace = _optional_bool(keep_raw_trace, False)
    # Keep raw trace internally for text-integrity repair; optionally strip it from the returned raw artifact.
    pipeline = SicroTwoPassPipeline(engine=engine, keep_raw_trace=True, max_passes=max_passes, force_passes=force_passes)
    result = pipeline.extract(pdf_path, int(start_page), int(end_page))
    if not return_raw_trace:
        for comp in (result.get("composicoes") or {}).values():
            comp.pop("raw_trace", None)
    contract = audit_extraction_contract(result)
    result["contract_audit"] = {"ok": not contract, "issues": contract}
    result.setdefault("metadata", {})["total_contract_issues"] = len(contract)
    return {
        "ok": not result.get("issues") and not contract,
        "environment": detect_environment(),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "words_cache": words_cache_report(),
        "result": result,
        "clean_result": make_clean_readable(result),
        "clean_audit": make_clean_audit(result),
        "text_audit": make_text_audit_report(result),
        "clean_summary_md": make_clean_summary_markdown(result),
        "signature": result_signature(result),
    }


def detect_environment() -> Dict[str, Any]:
    is_pyodide = "pyodide" in sys.modules or platform.system().lower() == "emscripten"
    try:
        import pymupdf as fitz  # type: ignore
        module_name = "pymupdf"
    except Exception:
        try:
            import fitz  # type: ignore
            module_name = "fitz"
        except Exception:
            fitz = None  # type: ignore
            module_name = "unavailable"
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "is_pyodide": bool(is_pyodide),
        "pymupdf_module": module_name,
        "pymupdf_version": getattr(fitz, "version", None) if fitz else None,
    }


def compare_signatures(local_sig: Dict[str, Any], browser_sig: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    if local_sig.get("composition_keys") != browser_sig.get("composition_keys"):
        issues.append({"type": "composition_keys", "local": local_sig.get("composition_keys"), "browser": browser_sig.get("composition_keys")})
    for key in sorted(set(local_sig.get("compositions", {})) | set(browser_sig.get("compositions", {}))):
        a = (local_sig.get("compositions") or {}).get(key) or {}
        b = (browser_sig.get("compositions") or {}).get(key) or {}
        if a.get("sections") != b.get("sections"):
            issues.append({"type": "section_counts", "composition": key, "local": a.get("sections"), "browser": b.get("sections")})
        if a.get("validacao_ok") != b.get("validacao_ok"):
            issues.append({"type": "validation_status", "composition": key, "local": a.get("validacao_ok"), "browser": b.get("validacao_ok")})
    return {"ok": not issues, "issues": issues, "local_count": local_sig.get("composition_count"), "browser_count": browser_sig.get("composition_count")}
