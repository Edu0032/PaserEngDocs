from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.pdf_session import PdfDocumentSession
from app.core.schemas import Composicoes, LinhaComposicao, LinhaInsumo, OrcamentoSintetico
from app.parser.table_candidates import build_table_candidates
from app.parser.table_fusion import collect_row_candidates, fuse_table_candidates
from app.parser.table_semantics import mapped_cell
from app.parser.table_structure import augment_orcamento_with_table_structure
from app.parser.unit_resolution import is_valid_unit_token, looks_like_dimension_context, resolve_unit_candidates


@dataclass
class ValidationStats:
    pages_inspected: int = 0
    pages_with_candidates: int = 0
    line_candidates_used: int = 0
    lines_refined: int = 0
    unit_updates: int = 0
    description_updates: int = 0
    quant_updates: int = 0
    value_updates: int = 0
    total_updates: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "pages_inspected": self.pages_inspected,
            "pages_with_candidates": self.pages_with_candidates,
            "line_candidates_used": self.line_candidates_used,
            "lines_refined": self.lines_refined,
            "unit_updates": self.unit_updates,
            "description_updates": self.description_updates,
            "quant_updates": self.quant_updates,
            "value_updates": self.value_updates,
            "total_updates": self.total_updates,
        }


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _normalize_space(text: Any) -> str:
    return " ".join(str(text or "").replace("\u00a0", " ").split()).strip()


def _is_better_description(current: str, candidate: str) -> bool:
    cur = _normalize_space(current)
    cand = _normalize_space(candidate)
    if not cand or len(cand) < 12:
        return False
    if not cur:
        return True
    if cand == cur:
        return False
    if len(cand) > len(cur) and (cur in cand or cand.startswith(cur) or cand.endswith(cur)):
        return True
    # Prefer candidate if current looks obviously truncated.
    if len(cur) < 40 and len(cand) >= len(cur) + 10:
        return True
    return False


def _row_candidates_for_line(indexed: Dict[int, List[Dict[str, Any]]], *, codigo: str, banco: str = "", item: str = "") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    banco = str(banco or "").strip().upper()
    for page_no, candidates in indexed.items():
        rows = collect_row_candidates(candidates, item=str(item or ""), codigo=str(codigo or ""))
        for row in rows:
            sem = dict(row.get("semantic") or {})
            mapped_bank = str(mapped_cell(list(row.get("row") or []), sem, "banco") or "").strip().upper()
            if banco and mapped_bank and banco != mapped_bank:
                continue
            row["page_no"] = page_no
            out.append(row)
    out.sort(key=lambda entry: float(entry.get("score") or 0.0), reverse=True)
    return out


def _collect_unit_candidates_from_rows(row_matches: List[Dict[str, Any]], *, specification: str, current_unit: str) -> Dict[str, Any]:
    unit_candidates: List[Dict[str, Any]] = []
    for match in row_matches:
        row = [str(c or "").strip() for c in (match.get("row") or [])]
        sem = dict(match.get("semantic") or {})
        mapped = mapped_cell(row, sem, "und")
        if mapped:
            unit_candidates.append({
                "unit": mapped,
                "score": float(match.get("score") or 0.0),
                "mapped": True,
                "strategy": match.get("strategy"),
                "page_no": match.get("page_no"),
            })
        for token in row:
            token = str(token or "").strip()
            if is_valid_unit_token(token):
                unit_candidates.append({
                    "unit": token,
                    "score": float(match.get("score") or 0.0) * 0.2,
                    "mapped": False,
                    "strategy": match.get("strategy"),
                    "page_no": match.get("page_no"),
                })
    return resolve_unit_candidates(current_unit, unit_candidates, specification=specification)


def _best_description_from_rows(row_matches: List[Dict[str, Any]], *, current: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    best = ""
    best_meta: Optional[Dict[str, Any]] = None
    for match in row_matches:
        row = [str(c or "").strip() for c in (match.get("row") or [])]
        sem = dict(match.get("semantic") or {})
        desc = _normalize_space(mapped_cell(row, sem, "descricao"))
        if not desc:
            # fallback: longest cell often is description
            cells = [c for c in row if c]
            desc = max(cells, key=len) if cells else ""
            desc = _normalize_space(desc)
        if _is_better_description(best or current, desc):
            best = desc
            best_meta = match
    return best, best_meta


def _mapped_number(row: List[str], sem: Dict[str, Any], canonical: str) -> float | None:
    raw = str(mapped_cell(row, sem, canonical) or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(raw) if raw else None
    except Exception:
        return None


def _refine_line(line: LinhaComposicao | LinhaInsumo, *, row_matches: List[Dict[str, Any]], stats: ValidationStats) -> LinhaComposicao | LinhaInsumo:
    if not row_matches:
        return line
    stats.line_candidates_used += len(row_matches)
    changed = False
    current_desc = str(getattr(line, "descricao", "") or "")
    best_desc, _ = _best_description_from_rows(row_matches, current=current_desc)
    if _is_better_description(current_desc, best_desc):
        line.descricao = best_desc
        stats.description_updates += 1
        changed = True

    current_unit = str(getattr(line, "und", "") or "")
    unit_resolution = _collect_unit_candidates_from_rows(row_matches, specification=str(getattr(line, "descricao", "") or current_desc or ""), current_unit=current_unit)
    final_unit = str(unit_resolution.get("unit_final") or "").strip()
    if final_unit and final_unit != current_unit:
        line.und = final_unit
        stats.unit_updates += 1
        changed = True
        line.detalhes.setdefault("multi_validator", {})["unit_resolution"] = unit_resolution

    # numeric backfill / validation from best mapped row
    best_match = row_matches[0]
    row = [str(c or "").strip() for c in (best_match.get("row") or [])]
    sem = dict(best_match.get("semantic") or {})
    for attr, canonical, counter_name in (
        ("quant", "quant", "quant_updates"),
        ("valor_unit", "valor_unit", "value_updates"),
        ("total", "total", "total_updates"),
    ):
        current_val = _safe_float(getattr(line, attr, None))
        candidate_val = _mapped_number(row, sem, canonical)
        if candidate_val is None:
            continue
        if current_val is None or abs(current_val - candidate_val) > 0.0001:
            # prefer candidate when current missing or line carries suspicious dimensional unit from description
            if current_val is None or looks_like_dimension_context(str(getattr(line, "descricao", "") or "")):
                setattr(line, attr, candidate_val)
                setattr(stats, counter_name, getattr(stats, counter_name) + 1)
                changed = True

    if changed:
        stats.lines_refined += 1
        mv = line.detalhes.setdefault("multi_validator", {})
        mv["enabled"] = True
        mv["source"] = "mandatory_table_cross_validation"
        mv["row_match_count"] = len(row_matches)
        mv["best_strategy"] = best_match.get("strategy")
        mv["best_score"] = float(best_match.get("score") or 0.0)
    return line


def _iter_blocks(comp: Composicoes) -> Iterable[Tuple[str, Any]]:
    for collection_name in ("principais", "auxiliares_globais"):
        collection = getattr(comp, collection_name, {}) or {}
        for key, block in collection.items():
            yield key, block


def _index_composition_candidates(session: PdfDocumentSession, *, page_range: Tuple[int, int], profile: Dict[str, Any] | None = None) -> Tuple[Dict[int, List[Dict[str, Any]]], ValidationStats]:
    start, end = page_range
    indexed: Dict[int, List[Dict[str, Any]]] = {}
    stats = ValidationStats()
    for page_no in range(start, end + 1):
        stats.pages_inspected += 1
        candidates = build_table_candidates(session, page_no, family="composition", profile=profile or {})
        if candidates:
            stats.pages_with_candidates += 1
            indexed[page_no] = candidates
    return indexed, stats


def augment_compositions_with_multi_validation(
    comp: Composicoes,
    *,
    pdf_session: PdfDocumentSession,
    page_range: Tuple[int, int],
    context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    context = context or {}
    profile = dict(context.get("document_profile") or {}) if context.get("header_profile_enabled", True) else {}
    indexed, stats = _index_composition_candidates(pdf_session, page_range=page_range, profile=profile)

    for key, block in _iter_blocks(comp):
        item_ref = str(getattr(block, "item", "") or "")
        principal = getattr(block, "principal", None)
        if principal is not None:
            principal_matches = _row_candidates_for_line(indexed, codigo=str(principal.codigo or ""), banco=str(principal.banco or ""), item=item_ref)
            _refine_line(principal, row_matches=principal_matches, stats=stats)
        for aux in list(getattr(block, "composicoes_auxiliares", []) or []):
            row_matches = _row_candidates_for_line(indexed, codigo=str(aux.codigo or ""), banco=str(aux.banco or ""), item=item_ref)
            _refine_line(aux, row_matches=row_matches, stats=stats)
        for ins in list(getattr(block, "insumos", []) or []):
            row_matches = _row_candidates_for_line(indexed, codigo=str(ins.codigo or ""), banco=str(ins.banco or ""), item=item_ref)
            _refine_line(ins, row_matches=row_matches, stats=stats)
        detalhes = getattr(block, "detalhes", {}) or {}
        detalhes["multi_validator"] = {
            "enabled": True,
            "pages_with_candidates": stats.pages_with_candidates,
        }
        block.detalhes = detalhes

    return {
        "enabled": True,
        "mode": "mandatory",
        "stats": stats.as_dict(),
        "pages": {"inicio": page_range[0], "fim": page_range[1]},
    }


def augment_budget_with_multi_validation(
    orcamento: OrcamentoSintetico,
    *,
    pdf_session: PdfDocumentSession,
    page_range: Tuple[int, int],
    context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    meta = augment_orcamento_with_table_structure(orcamento, pdf_session=pdf_session, page_range=page_range, context=context)
    meta["mode"] = "mandatory"
    meta["validator"] = "multi_reference_table_validation"
    return meta
