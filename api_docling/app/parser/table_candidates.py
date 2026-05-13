from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.core.document_profile import profile_column_labels, profile_financial_labels
from app.core.table_models import budget_header_aliases_from_profile, get_table_model
from app.core.base_rules import header_cfg, line_has_header_markers
from app.parser.template_selector import score_template


def _score_candidate(model: Dict[str, Any], *, family: str, profile: Dict[str, Any] | None = None, semantics: Dict[str, Any] | None = None) -> Dict[str, float]:
    profile = profile or {}
    semantics = semantics or {}
    rows = list(model.get("rows") or [])
    if not rows:
        return {"score": 0.0, "geometry": 0.0, "semantic": 0.0, "content": 0.0}

    header_cfg_budget = header_cfg(
        {"table_headers": {"aliases": budget_header_aliases_from_profile(profile), "required": ["item_agregador", "codigo", "fonte"], "min_similarity": 0.7}},
        key="table_headers",
        default_aliases=budget_header_aliases_from_profile(profile),
        default_required=["item_agregador", "codigo", "fonte"],
        default_similarity=0.7,
    )
    known_labels = [x.upper() for x in profile_column_labels(profile) + profile_financial_labels(profile)]

    header_hits = 0.0
    content_hits = 0.0
    preview_rows = rows[: min(6, len(rows))]
    for idx, row in enumerate(preview_rows):
        joined = " ".join(str(c or "") for c in row)
        if family == "budget":
            if line_has_header_markers(joined, header_cfg_budget, required_keys=["item_agregador", "codigo"]):
                header_hits += 1.0
        else:
            if idx == 0 and semantics.get("matched"):
                header_hits += 1.0
        if known_labels:
            content_hits += min(sum(1 for lbl in known_labels if lbl and lbl in joined.upper()), 4) * 0.15

    geometry = float(model.get("row_count") or 0) * 0.04 + float(model.get("col_count") or 0) * 0.12
    semantic = float(semantics.get("confidence") or 0.0) * 4.0
    strategy = str(model.get("strategy") or "")
    strategy_bonus = 0.35 if strategy == "lines_strict" else (0.25 if strategy == "lines" else 0.0)
    score = round(header_hits * 1.8 + content_hits + geometry + semantic + strategy_bonus, 3)
    return {
        "score": score,
        "geometry": round(geometry, 3),
        "semantic": round(semantic, 3),
        "content": round(header_hits * 1.8 + content_hits + strategy_bonus, 3),
    }


def _candidate_from_structured_table(
    table: Dict[str, Any],
    *,
    page_no: int,
    family: str,
    non_table_panels: List[Dict[str, Any]] | None = None,
    selection_policy: Dict[str, Any] | None = None,
) -> Dict[str, Any] | None:
    score, status, reasons = score_template(
        table,
        kind=family,
        non_table_panels=non_table_panels,
        selection_policy=selection_policy,
    )
    if status == 'rejected':
        return None
    rows_raw = []
    for raw_row in list(table.get('rows') or []):
        cells = sorted(list(raw_row.get('cells') or []), key=lambda cell: int(cell.get('col_index') or 0))
        width = max((int(cell.get('col_index') or 0) for cell in cells), default=-1) + 1
        row = ['' for _ in range(max(width, 0))]
        for cell in cells:
            idx = int(cell.get('col_index') or 0)
            if 0 <= idx < len(row):
                row[idx] = str(cell.get('text') or '')
        rows_raw.append(row)
    column_map = {}
    for col in list(table.get('column_schema') or []):
        canonical = str(col.get('canonical_name') or '').strip()
        if not canonical:
            continue
        column_map[canonical] = {
            'col_index': int(col.get('physical_index') or 0),
            'header_text': str(col.get('header_text') or ''),
            'score': float(col.get('confidence') or table.get('confidence') or 0.0),
        }
    semantic = {
        'matched': bool(column_map),
        'header_index': (list(table.get('header_rows') or [0]) or [0])[0] if rows_raw else None,
        'column_map': column_map,
        'confidence': float(table.get('confidence') or 0.0),
        'table_kind': str(table.get('kind') or family or 'generic'),
        'first_column_role': 'controle_linha' if family != 'budget' else '',
        'supports_blank_control_cells': True,
        'supports_auxiliares_globais_sem_item': True,
        'selection_reasons': reasons,
    }
    return {
        'strategy': 'external_structured',
        'candidate_id': str(table.get('table_id') or f'p{page_no}:external'),
        'page_no': page_no,
        'family': family,
        'bbox': list(table.get('bbox') or []),
        'row_count': len(rows_raw),
        'col_count': max((len(r) for r in rows_raw), default=0),
        'rows': rows_raw,
        'semantic': semantic,
        'scores': {'score': score, 'geometry': 1.0, 'semantic': float(table.get('confidence') or 0.0), 'content': 1.0},
        'confidence': score,
        'source': str(table.get('source') or 'external_structured'),
    }


def build_table_candidates(
    session: Any,
    page_no: int,
    *,
    family: str,
    profile: Dict[str, Any] | None = None,
    strategies: Iterable[str] | None = None,
    bank_hint: str = "",
    non_table_panels: List[Dict[str, Any]] | None = None,
    selection_policy: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """Gera candidatos de estrutura tabular a partir de múltiplas estratégias."""
    profile = profile or {}
    if not hasattr(session, "get_pymupdf_tables"):
        return []

    strategies = list(strategies or ("lines_strict", "lines", "text"))
    if family == "budget":
        table_model = get_table_model(profile, "orcamento_sintetico")
    elif family == "sicro":
        table_model = get_table_model(profile, "composicoes_sicro")
    else:
        from app.parser.table_semantics import resolve_table_family
        table_model = resolve_table_family(profile, bank_hint=bank_hint)

    out: List[Dict[str, Any]] = []
    if hasattr(session, 'get_structured_tables'):
        structured = list(session.get_structured_tables(page_no, family=family) or [])
        for table in structured:
            candidate = _candidate_from_structured_table(
                table,
                page_no=page_no,
                family=family,
                non_table_panels=non_table_panels,
                selection_policy=selection_policy,
            )
            if candidate is not None:
                out.append(candidate)
    for strategy in strategies:
        try:
            raw_models = list(session.get_pymupdf_tables(page_no, strategy=strategy) or [])
        except Exception:
            raw_models = []
        for idx, raw_model in enumerate(raw_models):
            rows = list(raw_model.get("rows") or [])
            if not rows:
                continue
            from app.parser.table_semantics import analyze_rows_with_model
            semantics = analyze_rows_with_model(rows, model=table_model)
            scores = _score_candidate(raw_model, family=family, profile=profile, semantics=semantics)
            out.append({
                **raw_model,
                "candidate_id": f"p{page_no}:{strategy}:{idx}",
                "page_no": page_no,
                "family": family,
                "semantic": semantics,
                "scores": scores,
                "confidence": scores["score"],
            })
    out.sort(key=lambda item: (float(item.get("confidence") or 0.0), float((item.get("semantic") or {}).get("confidence") or 0.0)), reverse=True)
    return out
