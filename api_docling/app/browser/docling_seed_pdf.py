from __future__ import annotations

import io
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

from pypdf import PdfReader, PdfWriter


class DoclingSeedPdfError(RuntimeError):
    def __init__(self, message: str, *, code: str = "docling_seed_pdf_error", detail: Any = None):
        super().__init__(message)
        self.code = code
        self.detail = detail


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _coerce_page(value: Any, *, default: int = 0) -> int:
    try:
        return int(value or default or 0)
    except Exception:
        return int(default or 0)


def _seed_pages_from_payload(payload: Dict[str, Any]) -> Tuple[int, int]:
    payload = _as_dict(payload)
    seeds = _as_dict(payload.get("docling_seed_pages"))
    ranges = _as_dict(payload.get("ranges"))
    budget_range = _as_dict(ranges.get("budget") or ranges.get("orcamento"))
    composition_range = _as_dict(ranges.get("compositions") or ranges.get("composicoes") or ranges.get("composition"))
    budget_page = _coerce_page(seeds.get("budget_header_page") or seeds.get("budget") or seeds.get("orcamento") or budget_range.get("start"))
    composition_page = _coerce_page(seeds.get("composition_schema_page") or seeds.get("composition") or seeds.get("compositions") or seeds.get("composicoes") or composition_range.get("start"))
    return budget_page, composition_page


def _policy(payload: Dict[str, Any]) -> Dict[str, Any]:
    policy = _as_dict(payload.get("docling_seed_pdf_policy"))
    return {
        "enabled": bool(policy.get("enabled", True)),
        "extract_in_pyodide": bool(policy.get("extract_in_pyodide", True)),
        "send_full_pdf_to_docling": bool(policy.get("send_full_pdf_to_docling", False)),
        "allow_full_pdf_fallback": bool(policy.get("allow_full_pdf_fallback", False)),
        "preserve_full_page": bool(policy.get("preserve_full_page", True)),
        "deduplicate_pages": bool(policy.get("deduplicate_pages", True)),
    }


def build_docling_seed_pdf_bytes(pdf_bytes: bytes, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = _as_dict(payload)
    policy = _policy(payload)
    if not policy["enabled"] or policy["send_full_pdf_to_docling"]:
        if not policy["send_full_pdf_to_docling"]:
            raise DoclingSeedPdfError(
                "A política atual desativou a extração seed, mas também não permite enviar PDF completo ao Docling.",
                code="docling_seed_pdf_disabled",
                detail={"policy": policy},
            )
        return {
            "pdf_bytes": pdf_bytes,
            "docling_seed_pdf": {
                "enabled": False,
                "is_seed_pdf": False,
                "source_pdf_was_reduced": False,
                "page_map": {},
                "roles": {},
                "original_pages": [],
                "policy": policy,
                "warning": "full_pdf_allowed_by_policy",
            },
        }

    if not pdf_bytes:
        raise DoclingSeedPdfError("PDF vazio recebido para extração seed.", code="empty_pdf")

    budget_page, composition_page = _seed_pages_from_payload(payload)
    if budget_page < 1 or composition_page < 1:
        raise DoclingSeedPdfError(
            "docling_seed_pages inválido ou ausente. Informe budget/budget_header_page e composition/composition_schema_page.",
            code="invalid_docling_seed_pages",
            detail={"budget_page": budget_page, "composition_page": composition_page},
        )

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception as exc:
        raise DoclingSeedPdfError(
            f"Falha ao ler PDF original para extrair páginas seed: {exc}",
            code="seed_pdf_read_failed",
            detail={"exception_type": exc.__class__.__name__},
        ) from exc

    total_pages = len(reader.pages)
    requested: List[Tuple[str, int]] = [("budget_header_page", budget_page), ("composition_schema_page", composition_page)]
    for role, page_no in requested:
        if page_no < 1 or page_no > total_pages:
            raise DoclingSeedPdfError(
                f"Página seed fora do intervalo: {role}={page_no}, total={total_pages}.",
                code="docling_seed_page_out_of_range",
                detail={"role": role, "page": page_no, "total_pages": total_pages},
            )

    writer = PdfWriter()
    local_to_original: Dict[str, int] = {}
    roles: Dict[str, str] = {}
    seen: Dict[int, int] = {}
    ordered_pages: List[int] = []

    for role, original_page in requested:
        if policy["deduplicate_pages"] and original_page in seen:
            local_page = seen[original_page]
            roles[str(local_page)] = ",".join([x for x in [roles.get(str(local_page), ""), role] if x])
            continue
        writer.add_page(reader.pages[original_page - 1])
        local_page = len(local_to_original) + 1
        seen[original_page] = local_page
        local_to_original[str(local_page)] = int(original_page)
        roles[str(local_page)] = role
        ordered_pages.append(int(original_page))

    out = io.BytesIO()
    writer.write(out)
    seed_bytes = out.getvalue()
    return {
        "pdf_bytes": seed_bytes,
        "docling_seed_pdf": {
            "enabled": True,
            "is_seed_pdf": True,
            "source_pdf_was_reduced": True,
            "page_map": local_to_original,
            "roles": roles,
            "original_pages": ordered_pages,
            "original_page_count": total_pages,
            "local_page_count": len(local_to_original),
            "original_size_bytes": len(pdf_bytes),
            "seed_size_bytes": len(seed_bytes),
            "policy": policy,
        },
    }


def build_docling_seed_pdf_file(pdf_path: str, payload: Dict[str, Any] | None = None, *, output_path: str | None = None) -> Dict[str, Any]:
    started = time.perf_counter()
    source = Path(pdf_path)
    if not source.exists():
        raise DoclingSeedPdfError("Arquivo PDF não encontrado para extração seed.", code="pdf_path_not_found", detail={"pdf_path": pdf_path})
    result = build_docling_seed_pdf_bytes(source.read_bytes(), payload or {})
    seed_bytes = result.pop("pdf_bytes")
    if output_path is None:
        output_path = f"/tmp/docling-seed-{uuid.uuid4().hex}.pdf"
    Path(output_path).write_bytes(seed_bytes)
    meta = dict(result.get("docling_seed_pdf") or {})
    meta["seed_pdf_path"] = output_path
    meta["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return {"status": "ok", "seed_pdf_path": output_path, "docling_seed_pdf": meta}


def build_docling_seed_pdf_file_json(pdf_path: str, payload_json: str) -> str:
    try:
        payload = json.loads(payload_json) if payload_json else {}
        return json.dumps(build_docling_seed_pdf_file(pdf_path, payload), ensure_ascii=False)
    except DoclingSeedPdfError as exc:
        return json.dumps({"status": "error", "error": {"code": exc.code, "message": str(exc), "detail": exc.detail}}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "error": {"code": "docling_seed_pdf_internal_error", "message": str(exc), "detail": {"exception_type": exc.__class__.__name__}}}, ensure_ascii=False)


def build_selected_pages_pdf_file(pdf_path: str, payload: Dict[str, Any] | None = None, *, output_path: str | None = None) -> Dict[str, Any]:
    """Build a focused mini-PDF from arbitrary original pages.

    Used by Normalizer targeted recovery. The original PDF remains local in Pyodide;
    only the requested problematic pages are sent to the server API.
    """
    started = time.perf_counter()
    payload = _as_dict(payload)
    pages_raw = payload.get("pages") or payload.get("original_pages") or []
    if not isinstance(pages_raw, list) or not pages_raw:
        raise DoclingSeedPdfError("Lista de páginas para mini-PDF direcionado ausente.", code="selected_pages_missing")
    source = Path(pdf_path)
    if not source.exists():
        raise DoclingSeedPdfError("Arquivo PDF não encontrado para extração direcionada.", code="pdf_path_not_found", detail={"pdf_path": pdf_path})
    try:
        reader = PdfReader(str(source))
    except Exception as exc:
        raise DoclingSeedPdfError(f"Falha ao ler PDF original para páginas direcionadas: {exc}", code="targeted_pdf_read_failed", detail={"exception_type": exc.__class__.__name__}) from exc
    total_pages = len(reader.pages)
    ordered: List[int] = []
    for raw in pages_raw:
        page_no = _coerce_page(raw)
        if page_no < 1 or page_no > total_pages:
            raise DoclingSeedPdfError("Página direcionada fora do intervalo.", code="targeted_page_out_of_range", detail={"page": page_no, "total_pages": total_pages})
        if page_no not in ordered:
            ordered.append(page_no)
    max_pages = int(payload.get("max_pages") or 12)
    if len(ordered) > max_pages:
        raise DoclingSeedPdfError("Mini-PDF direcionado excede o limite de páginas.", code="targeted_too_many_pages", detail={"requested": ordered, "max_pages": max_pages})
    writer = PdfWriter()
    page_map: Dict[str, int] = {}
    roles: Dict[str, str] = {}
    for local_idx, page_no in enumerate(ordered, start=1):
        writer.add_page(reader.pages[page_no - 1])
        page_map[str(local_idx)] = int(page_no)
        roles[str(local_idx)] = "targeted_recovery_page"
    if output_path is None:
        output_path = f"/tmp/normalizer-targeted-{uuid.uuid4().hex}.pdf"
    out = io.BytesIO()
    writer.write(out)
    data = out.getvalue()
    Path(output_path).write_bytes(data)
    return {
        "status": "ok",
        "targeted_pdf_path": output_path,
        "targeted_recovery_pdf": {
            "enabled": True,
            "is_seed_pdf": True,
            "source_pdf_was_reduced": True,
            "page_map": page_map,
            "roles": roles,
            "original_pages": ordered,
            "original_page_count": total_pages,
            "local_page_count": len(ordered),
            "original_size_bytes": source.stat().st_size,
            "seed_size_bytes": len(data),
            "policy": {"purpose": "normalizer_targeted_recovery", "send_full_pdf": False, "max_pages": max_pages},
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        },
    }


def build_selected_pages_pdf_file_json(pdf_path: str, payload_json: str) -> str:
    try:
        payload = json.loads(payload_json) if payload_json else {}
        return json.dumps(build_selected_pages_pdf_file(pdf_path, payload), ensure_ascii=False)
    except DoclingSeedPdfError as exc:
        return json.dumps({"status": "error", "error": {"code": exc.code, "message": str(exc), "detail": exc.detail}}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "error": {"code": "targeted_seed_pdf_internal_error", "message": str(exc), "detail": {"exception_type": exc.__class__.__name__}}}, ensure_ascii=False)
