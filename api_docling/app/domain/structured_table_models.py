from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StructuredCell(BaseModel):
    row_index: int
    col_index: int
    text: str = ''
    canonical_name: str = ''
    bbox: List[float] = Field(default_factory=list)
    row_span: int = 1
    col_span: int = 1
    confidence: float = 0.0
    page: Optional[int] = None
    is_header: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StructuredColumn(BaseModel):
    physical_index: int
    canonical_name: str = ''
    header_text: str = ''
    kind: str = ''
    x0: Optional[float] = None
    x1: Optional[float] = None
    width: Optional[float] = None
    confidence: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StructuredRow(BaseModel):
    row_index: int
    bbox: List[float] = Field(default_factory=list)
    page: Optional[int] = None
    cells: List[StructuredCell] = Field(default_factory=list)
    kind: str = ''
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def as_matrix_row(self, *, width: int | None = None) -> List[str]:
        ordered = sorted(self.cells, key=lambda cell: int(cell.col_index))
        if width is None:
            width = (max((cell.col_index for cell in ordered), default=-1) + 1) if ordered else 0
        row = ['' for _ in range(max(width, 0))]
        for cell in ordered:
            if 0 <= int(cell.col_index) < len(row):
                row[int(cell.col_index)] = str(cell.text or '')
        return row


class StructuredTable(BaseModel):
    table_id: str
    kind: str = 'generic'
    family: str = 'generic'
    page_start: int = 0
    page_end: int = 0
    bbox: List[float] = Field(default_factory=list)
    header_rows: List[int] = Field(default_factory=list)
    body_rows_start: Optional[int] = None
    column_schema: List[StructuredColumn] = Field(default_factory=list)
    rows: List[StructuredRow] = Field(default_factory=list)
    confidence: float = 0.0
    source: str = ''
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def as_matrix(self) -> List[List[str]]:
        width = max((col.physical_index for col in self.column_schema), default=-1) + 1
        if width <= 0:
            width = max((max((cell.col_index for cell in row.cells), default=-1) for row in self.rows), default=-1) + 1
        return [row.as_matrix_row(width=width) for row in sorted(self.rows, key=lambda entry: int(entry.row_index))]

    def column_map(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for col in self.column_schema:
            canonical = str(col.canonical_name or '').strip()
            if not canonical:
                continue
            out[canonical] = {
                'col_index': int(col.physical_index),
                'header_text': col.header_text,
                'score': float(col.confidence or self.confidence or 0.0),
                'kind': col.kind,
            }
        return out


class StructuredTableBundle(BaseModel):
    contract_version: str = '1.0'
    source: str = ''
    tables: List[StructuredTable] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def tables_by_page(self) -> Dict[int, List[Dict[str, Any]]]:
        out: Dict[int, List[Dict[str, Any]]] = {}
        for table in self.tables:
            for page in range(int(table.page_start or 0), int(table.page_end or 0) + 1):
                if page <= 0:
                    continue
                out.setdefault(page, []).append(table.model_dump(mode='python'))
        return out

    def summary(self) -> Dict[str, Any]:
        return {
            'contract_version': self.contract_version,
            'source': self.source,
            'table_count': len(self.tables),
            'kinds': sorted({str(table.kind or '') for table in self.tables if str(table.kind or '').strip()}),
            'families': sorted({str(table.family or '') for table in self.tables if str(table.family or '').strip()}),
        }
