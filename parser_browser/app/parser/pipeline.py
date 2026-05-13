from __future__ import annotations

from typing import Dict, Tuple

from app.core.pdf_session import PdfDocumentSession
from app.parser.staged import merge_staged_results, parse_budget_stage, parse_compositions_stage


def parse_document(
    pdf_bytes: bytes,
    ranges: Dict[str, Tuple[int, int]],
    config: dict,
    context: dict | None = None,
) -> dict:
    """Pipeline principal do parser de documento misto."""
    context = context or {}
    with PdfDocumentSession(pdf_bytes) as session:
        if context.get("structured_tables"):
            session.set_structured_tables(context.get("structured_tables"))
        budget_stage = parse_budget_stage(pdf_bytes=pdf_bytes, ranges=ranges, config=config, context=context, pdf_session=session)
        compositions_stage = parse_compositions_stage(pdf_bytes=pdf_bytes, ranges=ranges, config=config, context=context, pdf_session=session)
    return merge_staged_results(budget_stage, compositions_stage, config=config, context=context)
