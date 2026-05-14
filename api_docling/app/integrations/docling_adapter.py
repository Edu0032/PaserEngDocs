from __future__ import annotations

from typing import Any, Dict, List

from app.domain.structured_table_models import StructuredCell, StructuredColumn, StructuredRow, StructuredTable, StructuredTableBundle


def adapt_docling_payload(payload: Dict[str, Any] | StructuredTableBundle | None) -> StructuredTableBundle:
    if isinstance(payload, StructuredTableBundle):
        return payload
    payload = dict(payload or {})
    tables: List[StructuredTable] = []
    for raw_table in list(payload.get('tables') or []):
        rows: List[StructuredRow] = []
        for raw_row in list(raw_table.get('rows') or []):
            cells = [StructuredCell(**cell) for cell in list(raw_row.get('cells') or [])]
            rows.append(StructuredRow(
                row_index=int(raw_row.get('row_index') or 0),
                bbox=list(raw_row.get('bbox') or []),
                page=raw_row.get('page'),
                kind=str(raw_row.get('kind') or ''),
                metadata=dict(raw_row.get('metadata') or {}),
                cells=cells,
            ))
        columns = [StructuredColumn(**col) for col in list(raw_table.get('column_schema') or [])]
        tables.append(StructuredTable(
            table_id=str(raw_table.get('table_id') or raw_table.get('template_id') or ''),
            kind=str(raw_table.get('kind') or 'generic'),
            family=str(raw_table.get('family') or raw_table.get('kind') or 'generic'),
            page_start=int(raw_table.get('page_start') or raw_table.get('seed_page') or 0),
            page_end=int(raw_table.get('page_end') or raw_table.get('page_start') or raw_table.get('seed_page') or 0),
            bbox=list(raw_table.get('bbox') or []),
            header_rows=[int(x) for x in list(raw_table.get('header_rows') or [])],
            body_rows_start=raw_table.get('body_rows_start'),
            column_schema=columns,
            rows=rows,
            confidence=float(raw_table.get('confidence') or 0.0),
            source=str(raw_table.get('source') or payload.get('source') or ''),
            metadata=dict(raw_table.get('metadata') or {}),
        ))
    return StructuredTableBundle(
        contract_version=str(payload.get('contract_version') or '1.1'),
        source=str(payload.get('source') or ''),
        tables=tables,
        metadata=dict(payload.get('metadata') or {}),
    )


def structured_bundle_to_context(bundle: StructuredTableBundle) -> Dict[str, Any]:
    tables = [table.model_dump(mode='python') for table in bundle.tables]
    templates = []
    for table in bundle.tables:
        templates.append({
            'template_id': table.table_id,
            'kind': table.kind,
            'family': table.family,
            'seed_page': table.page_start,
            'header_rows': list(table.header_rows or []),
            'body_rows_start': table.body_rows_start,
            'confidence': float(table.confidence or 0.0),
            'grouped_headers': list(((table.metadata or {}).get('grouped_headers') or [])),
            'column_schema': [
                {
                    'physical_index': int(col.physical_index),
                    'canonical_name': str(col.canonical_name or ''),
                    'header_text': str(col.header_text or ''),
                    'kind': str(col.kind or ''),
                    'x0': col.x0,
                    'x1': col.x1,
                    'width': col.width,
                    'confidence': float(col.confidence or 0.0),
                    'metadata': dict(col.metadata or {}),
                }
                for col in table.column_schema
            ],
        })
    return {
        'contract_version': bundle.contract_version,
        'source': bundle.source,
        'tables': tables,
        'templates': templates,
        'metadata': dict(bundle.metadata or {}),
    }
