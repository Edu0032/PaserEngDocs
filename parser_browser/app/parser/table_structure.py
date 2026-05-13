from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.document_profile import profile_column_labels, profile_financial_labels
from app.core.pdf_session import PdfDocumentSession
from app.core.schemas import OrcamentoItem, OrcamentoSintetico
from app.parser.table_candidates import build_table_candidates
from app.parser.table_fusion import collect_row_candidates, fuse_candidates_to_matrix, fuse_table_candidates
from app.parser.table_semantics import mapped_cell
from app.parser.unit_resolution import is_valid_unit_token, looks_like_dimension_context, resolve_unit_candidates


def _strip_known_residuals(text: str, *, extra: Iterable[str] = ()) -> str:
    s = re.sub(r"\s+", " ", str(text or "").replace("\xa0", " ")).strip()
    patterns = [
        r"\bCUSTO\s+TOTAL\b",
        r"\bVALOR\s+COM\s+BDI\b\s*=>?",
        r"\bPRE[ÇC]O\s+UNIT[ÁA]RIO\b",
        r"\bCOMPOSI[ÇC][ÕO]ES?\s+ANAL[ÍI]TICAS?\b",
        r"\bCOMPOSI[ÇC][ÕO]ES?\s+PRINCIPAIS\b",
    ]
    for phrase in extra or []:
        if phrase:
            patterns.append(re.escape(str(phrase).strip()))
    for pat in patterns:
        s = re.sub(pat, " ", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip(" -,:;")


def _iter_leaf_items(nodes: Iterable[OrcamentoItem]) -> Iterable[OrcamentoItem]:
    for node in nodes or []:
        filhos = getattr(node, "filhos", None) or []
        if str(getattr(node, "tipo", "")).lower() == "item":
            yield node
        if filhos:
            yield from _iter_leaf_items(filhos)


def _extract_table_models(session: PdfDocumentSession, page_no: int, *, profile: Dict[str, Any] | None = None) -> List[dict]:
    profile = profile or {}
    if not hasattr(session, "get_pymupdf_tables"):
        return []
    candidates = build_table_candidates(session, page_no, family="budget", profile=profile)
    if not candidates:
        return []
    fused = fuse_table_candidates(candidates)
    out: List[dict] = []
    for cand in candidates:
        model = {
            **cand,
            "fusion": fused,
        }
        out.append(model)
    # injeta uma variante fundida para que o restante do parser possa aproveitar a melhor grade
    best_rows = fuse_candidates_to_matrix(candidates)
    if best_rows:
        out.insert(0, {
            "candidate_id": fused.get("best_candidate_id") or f"p{page_no}:fusion",
            "strategy": "fusion",
            "page_no": page_no,
            "bbox": fused.get("best_bbox") or [],
            "row_count": len(best_rows),
            "col_count": max((len(r) for r in best_rows), default=0),
            "rows": best_rows,
            "semantic": {
                "matched": fused.get("matched"),
                "confidence": fused.get("confidence"),
                "table_kind": fused.get("table_kind"),
                "column_map": dict(fused.get("column_map") or {}),
            },
            "confidence": fused.get("confidence"),
            "scores": {"score": fused.get("confidence", 0.0)},
            "fusion": fused,
        })
    out.sort(key=lambda m: (float(m.get("confidence") or 0.0), int(m.get("row_count") or 0), int(m.get("col_count") or 0)), reverse=True)
    return out


def pymupdf_tables_as_matrices(session: PdfDocumentSession, page_no: int, *, runtime: dict | None = None) -> List[List[List[str]]]:
    profile = dict(((runtime or {}).get("document_profile") or {})) if isinstance(runtime, dict) else {}
    models = _extract_table_models(session, page_no, profile=profile)
    return [list(model.get("rows") or []) for model in models if model.get("rows")]


def _row_description_candidate(row: List[str], *, item: str, codigo: str, fonte: str, semantics: Dict[str, Any] | None = None) -> str:
    mapped = mapped_cell(row, semantics, "descricao")
    if mapped:
        return _strip_known_residuals(mapped)
    cells = [str(c or "").strip() for c in row if str(c or "").strip()]
    desc_cells: List[str] = []
    passed_code = False
    skips = {str(item or "").strip(), str(codigo or "").strip(), str(fonte or "").strip()}
    for cell in cells:
        if not passed_code:
            if cell == str(codigo or "").strip():
                passed_code = True
            continue
        if cell in skips:
            continue
        if is_valid_unit_token(cell):
            break
        if re.fullmatch(r"\d+(?:,\d+)?", cell):
            break
        desc_cells.append(cell)
    return _strip_known_residuals(" ".join(desc_cells).strip())


def _should_replace_description(current: str, candidate: str) -> bool:
    current = _strip_known_residuals(current)
    candidate = _strip_known_residuals(candidate)
    if not candidate or len(candidate) < 12:
        return False
    if not current:
        return True
    if current == candidate:
        return False
    if len(candidate) > len(current) and (current in candidate or candidate.endswith(current) or candidate.startswith(current)):
        return True
    return False


def _build_budget_row_index(session: PdfDocumentSession, *, page_range: Tuple[int, int], profile: Dict[str, Any] | None = None) -> Dict[str, List[dict]]:
    start, end = page_range
    indexed: Dict[str, List[dict]] = {}
    for page_no in range(start, end + 1):
        candidates = _extract_table_models(session, page_no, profile=profile)
        indexed[str(page_no)] = list(candidates)
    return indexed


def _budget_row_candidates(indexed_rows: Dict[str, List[dict]], *, item: str, codigo: str) -> List[dict]:
    out: List[dict] = []
    for page_key, candidates in indexed_rows.items():
        out.extend(collect_row_candidates(candidates, item=item, codigo=codigo))
    out.sort(key=lambda entry: float(entry.get("score") or 0.0), reverse=True)
    return out


def _collect_unit_candidates(row_matches: List[dict], *, specification: str = "") -> Dict[str, Any]:
    unit_candidates: List[dict] = []
    for match in row_matches:
        row = [str(c or "").strip() for c in (match.get("row") or [])]
        semantics = dict(match.get("semantic") or {})
        mapped = mapped_cell(row, semantics, "und")
        if mapped:
            unit_candidates.append({
                "unit": mapped,
                "score": float(match.get("score") or 0.0),
                "mapped": True,
                "strategy": match.get("strategy"),
                "page_no": match.get("page_no"),
            })
        # fallback fraco: varre toda a linha, mas com baixa prioridade
        for token in row:
            token = str(token or "").strip()
            if is_valid_unit_token(token):
                unit_candidates.append({
                    "unit": token,
                    "score": float(match.get("score") or 0.0) * 0.35,
                    "mapped": False,
                    "strategy": match.get("strategy"),
                    "page_no": match.get("page_no"),
                })
    return resolve_unit_candidates("", unit_candidates, specification=specification)


def _best_description_candidate(row_matches: List[dict], *, item: str, codigo: str, fonte: str) -> Tuple[str, Dict[str, Any] | None]:
    best_desc = ""
    best_meta: Dict[str, Any] | None = None
    for match in row_matches:
        row = [str(c or "").strip() for c in (match.get("row") or [])]
        desc = _row_description_candidate(row, item=item, codigo=codigo, fonte=fonte, semantics=dict(match.get("semantic") or {}))
        if len(desc) > len(best_desc):
            best_desc = desc
            best_meta = match
    return best_desc, best_meta


def augment_orcamento_with_table_structure(
    orcamento: OrcamentoSintetico,
    *,
    pdf_session: PdfDocumentSession,
    page_range: Tuple[int, int],
    context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    context = context or {}
    if context.get("header_profile_enabled") is False:
        profile = {}
    else:
        profile = dict(context.get("document_profile") or {})
    applied: List[dict] = []
    header_noise = profile_column_labels(profile) + profile_financial_labels(profile) + list(profile.get("frases_institucionais_para_ignorar") or []) if str(context.get("noise_cleanup_mode") or "contextual") != "off" else []
    indexed_rows = _build_budget_row_index(pdf_session, page_range=page_range, profile=profile)
    for item_node in _iter_leaf_items(orcamento.itens_raiz):
        specification = str(getattr(item_node, "especificacao", "") or "")
        cleaned = _strip_known_residuals(specification, extra=header_noise)
        if cleaned != specification:
            item_node.especificacao = cleaned
            applied.append({
                "tipo": "especificacao_limpa",
                "item": item_node.item,
                "codigo": item_node.codigo,
                "antes": specification,
                "depois": cleaned,
            })
            specification = cleaned
        if not getattr(item_node, "item", "") or not getattr(item_node, "codigo", ""):
            continue
        row_matches = _budget_row_candidates(indexed_rows, item=str(item_node.item), codigo=str(item_node.codigo))
        if not row_matches:
            continue
        unit_resolution = _collect_unit_candidates(row_matches, specification=specification)
        candidate_unit = str(unit_resolution.get("unit_final") or "").strip()
        current_unit = str(getattr(item_node, "und", "") or "").strip()
        if candidate_unit and candidate_unit != current_unit and (not current_unit or current_unit.upper() in {"CM", "MM"} or looks_like_dimension_context(specification)):
            item_node.und = candidate_unit
            applied.append({
                "tipo": "unidade_corrigida_por_fusao_tabela",
                "item": item_node.item,
                "codigo": item_node.codigo,
                "pagina": row_matches[0].get("page_no"),
                "antes": current_unit,
                "depois": candidate_unit,
                "strategies": sorted({str(m.get('strategy') or '') for m in row_matches if m.get('strategy')}),
                "confidence": max(float(m.get("score") or 0.0) for m in row_matches[:3]) if row_matches else 0.0,
                "unit_resolution": unit_resolution,
            })
        desc_candidate, desc_meta = _best_description_candidate(row_matches, item=str(item_node.item), codigo=str(item_node.codigo), fonte=str(getattr(item_node, "fonte", "") or ""))
        if _should_replace_description(str(getattr(item_node, "especificacao", "") or ""), desc_candidate):
            before_desc = str(getattr(item_node, "especificacao", "") or "")
            item_node.especificacao = desc_candidate
            applied.append({
                "tipo": "especificacao_refinada_por_fusao_tabela",
                "item": item_node.item,
                "codigo": item_node.codigo,
                "pagina": desc_meta.get("page_no") if desc_meta else None,
                "antes": before_desc,
                "depois": desc_candidate,
            })

    if not orcamento.descricao:
        orcamento.descricao = str(context.get("obra_nome") or "").strip()
    return {
        "enabled": True,
        "applied_changes": applied,
        "pages": {"inicio": page_range[0], "fim": page_range[1]},
    }
