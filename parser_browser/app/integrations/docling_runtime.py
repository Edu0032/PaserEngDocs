from __future__ import annotations

import io
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from pypdf import PdfReader

from app.core.pdf_session import PdfDocumentSession
from app.core.table_models import get_table_model
from app.domain.structured_table_models import (
    StructuredCell,
    StructuredColumn,
    StructuredRow,
    StructuredTable,
    StructuredTableBundle,
)
from app.integrations.docling_models import DoclingExtractionRequest
from app.parser.table_semantics import resolve_table_columns
from app.config.version import CONTRACT_VERSION


@dataclass(slots=True)
class EmbeddedDoclingConfig:
    enabled: bool = True
    do_cell_matching: bool = False
    table_mode: str = 'fast'
    do_ocr: bool = False


def get_embedded_docling_runtime_info() -> Dict[str, Any]:
    try:
        import docling  # type: ignore
        version = getattr(docling, '__version__', 'unknown')
        return {
            'available': True,
            'version': str(version),
            'provider': 'docling_python',
        }
    except Exception as exc:  # pragma: no cover - depends on optional install
        return {
            'available': False,
            'provider': 'docling_python',
            'reason': f'{type(exc).__name__}: {exc}',
        }


def _bbox_to_list(bbox: Any) -> List[float]:
    if bbox is None:
        return []
    if isinstance(bbox, (list, tuple)):
        try:
            return [float(x or 0) for x in bbox[:4]]
        except Exception:
            return []
    for names in (('l', 't', 'r', 'b'), ('x0', 'y0', 'x1', 'y1')):
        try:
            values = [getattr(bbox, name) for name in names]
            return [float(x or 0) for x in values]
        except Exception:
            continue
    for method_name in ('as_tuple', 'to_tuple'):
        try:
            values = getattr(bbox, method_name)()
            return [float(x or 0) for x in list(values)[:4]]
        except Exception:
            continue
    return []


def _flatten_cell_text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return ''


def _normalize_matrix_from_grid(grid: Any) -> List[List[str]]:
    rows: List[List[str]] = []
    for raw_row in list(grid or []):
        row: List[str] = []
        for cell in list(raw_row or []):
            row.append(_flatten_cell_text(getattr(cell, 'text', cell)))
        rows.append(row)
    return rows


def _table_item_bbox(table_item: Any, data: Any) -> List[float]:
    for source in (
        getattr(table_item, 'bbox', None),
        getattr(table_item, 'prov', None),
        getattr(data, 'table_bbox', None),
    ):
        if not source:
            continue
        if isinstance(source, list) and source and not isinstance(source[0], (int, float)):
            for entry in source:
                bbox = _bbox_to_list(getattr(entry, 'bbox', None) or entry)
                if bbox:
                    return bbox
        bbox = _bbox_to_list(source)
        if bbox:
            return bbox
    return []


def _header_rows_from_data(data: Any, matrix_rows: List[List[str]]) -> List[int]:
    header_rows = set()
    for raw_cell in list(getattr(data, 'table_cells', None) or []):
        try:
            if bool(getattr(raw_cell, 'column_header', False)):
                header_rows.add(int(getattr(raw_cell, 'start_row_offset_idx')))
        except Exception:
            continue
    if header_rows:
        return sorted(header_rows)
    return [0] if matrix_rows else []


def _resolve_model(req_kind: str, req_family: str, request: DoclingExtractionRequest) -> Dict[str, Any]:
    profile = dict(request.document_profile or {})
    if req_kind == 'orcamento_sintetico' or req_family == 'budget':
        return get_table_model(profile, 'orcamento_sintetico')
    if req_family == 'sicro' or req_kind == 'composicao_sicro':
        return get_table_model(profile, 'composicoes_sicro')
    return get_table_model(profile, 'composicoes_sinapi')


def _build_columns(
    *,
    data: Any,
    matrix_rows: List[List[str]],
    semantics: Dict[str, Any],
    header_rows: List[int],
) -> List[StructuredColumn]:
    col_boxes: Dict[int, List[float]] = {}
    try:
        raw_col_boxes = data.get_column_bounding_boxes(minimal=True)
        for idx, bbox in dict(raw_col_boxes or {}).items():
            col_boxes[int(idx)] = _bbox_to_list(bbox)
    except Exception:
        pass

    mapped_by_index: Dict[int, Tuple[str, Dict[str, Any]]] = {}
    for canonical, detail in dict(semantics.get('column_map') or {}).items():
        try:
            mapped_by_index[int(detail.get('col_index'))] = (str(canonical), dict(detail))
        except Exception:
            continue

    width_hint = max((len(row) for row in matrix_rows), default=0)
    column_count = max(
        width_hint,
        (max(col_boxes.keys()) + 1) if col_boxes else 0,
        (max(mapped_by_index.keys()) + 1) if mapped_by_index else 0,
    )

    columns: List[StructuredColumn] = []
    for idx in range(column_count):
        canonical_name, detail = mapped_by_index.get(idx, ('', {}))
        bbox = col_boxes.get(idx, [])
        header_text = ''
        if header_rows and matrix_rows:
            hi = int(header_rows[0])
            if 0 <= hi < len(matrix_rows) and idx < len(matrix_rows[hi]):
                header_text = str(matrix_rows[hi][idx] or '')
        columns.append(StructuredColumn(
            physical_index=idx,
            canonical_name=canonical_name,
            header_text=str(detail.get('header_text') or header_text or ''),
            kind='mapped' if canonical_name else 'unmapped',
            x0=(float(bbox[0]) if len(bbox) == 4 else None),
            x1=(float(bbox[2]) if len(bbox) == 4 else None),
            width=((float(bbox[2]) - float(bbox[0])) if len(bbox) == 4 else None),
            confidence=float(detail.get('score') or semantics.get('confidence') or 0.0),
        ))
    return columns


def _build_rows_from_docling_data(
    *,
    page_no: int,
    data: Any,
    matrix_rows: List[List[str]],
    semantics: Dict[str, Any],
    header_rows: List[int],
) -> List[StructuredRow]:
    row_boxes: Dict[int, List[float]] = {}
    try:
        raw_row_boxes = data.get_row_bounding_boxes(minimal=True)
        for idx, bbox in dict(raw_row_boxes or {}).items():
            row_boxes[int(idx)] = _bbox_to_list(bbox)
    except Exception:
        pass

    canonical_by_index = {}
    for canonical, detail in dict(semantics.get('column_map') or {}).items():
        try:
            canonical_by_index[int(detail.get('col_index'))] = str(canonical)
        except Exception:
            continue

    cell_overrides: Dict[Tuple[int, int], StructuredCell] = {}
    for raw_cell in list(getattr(data, 'table_cells', None) or []):
        try:
            row_index = int(getattr(raw_cell, 'start_row_offset_idx'))
            col_index = int(getattr(raw_cell, 'start_col_offset_idx'))
        except Exception:
            continue
        bbox = _bbox_to_list(getattr(raw_cell, 'bbox', None))
        cell_overrides[(row_index, col_index)] = StructuredCell(
            row_index=row_index,
            col_index=col_index,
            text=_flatten_cell_text(getattr(raw_cell, 'text', '')),
            canonical_name=canonical_by_index.get(col_index, ''),
            bbox=bbox,
            row_span=max(int(getattr(raw_cell, 'row_span', 1) or 1), 1),
            col_span=max(int(getattr(raw_cell, 'col_span', 1) or 1), 1),
            confidence=float(semantics.get('confidence') or 0.0),
            page=page_no,
            is_header=bool(getattr(raw_cell, 'column_header', False)) or row_index in header_rows,
            metadata={
                'row_header': bool(getattr(raw_cell, 'row_header', False)),
                'row_section': bool(getattr(raw_cell, 'row_section', False)),
            },
        )

    rows: List[StructuredRow] = []
    for row_index, row_values in enumerate(matrix_rows):
        cells: List[StructuredCell] = []
        for col_index, value in enumerate(list(row_values or [])):
            override = cell_overrides.get((row_index, col_index))
            if override is not None:
                if not override.text and value:
                    override.text = str(value)
                if not override.canonical_name:
                    override.canonical_name = canonical_by_index.get(col_index, '')
                cells.append(override)
                continue
            cells.append(StructuredCell(
                row_index=row_index,
                col_index=col_index,
                text=str(value or ''),
                canonical_name=canonical_by_index.get(col_index, ''),
                bbox=[],
                row_span=1,
                col_span=1,
                confidence=float(semantics.get('confidence') or 0.0),
                page=page_no,
                is_header=row_index in header_rows,
            ))
        rows.append(StructuredRow(
            row_index=row_index,
            bbox=row_boxes.get(row_index, []),
            page=page_no,
            kind='header' if row_index in header_rows else 'body',
            metadata={},
            cells=cells,
        ))
    return rows


def extract_structures_with_embedded_docling(
    pdf_bytes: bytes,
    extraction_request: DoclingExtractionRequest,
    *,
    config: EmbeddedDoclingConfig | None = None,
) -> StructuredTableBundle:
    cfg = config or EmbeddedDoclingConfig()
    timing: Dict[str, float] = {'total_start_ms': time.perf_counter() * 1000.0}
    try:
        import_start = time.perf_counter()
        from docling.datamodel.base_models import InputFormat  # type: ignore
        from docling.document_converter import DocumentConverter, PdfFormatOption  # type: ignore
        from docling.datamodel.pipeline_options import PdfPipelineOptions  # type: ignore
        timing['runtime_import_ms'] = round((time.perf_counter() - import_start) * 1000.0, 2)
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(f'Docling Python não está instalado neste ambiente: {exc}') from exc

    pipeline_options = PdfPipelineOptions(do_table_structure=True)
    # OCR is intentionally disabled for this project. The pipeline only uses
    # embedded text and table structure extraction.
    try:
        pipeline_options.do_ocr = bool(cfg.do_ocr)
    except Exception:
        pass
    # Important: do NOT set pipeline_options.ocr_options = None.
    # Some Docling versions instantiate the OCR model factory even when do_ocr=False,
    # and the factory expects a valid options object with a `.kind` attribute.
    # OCR remains disabled by do_ocr=False; ocr_options is kept only as a valid
    # configuration object required by Docling internals.
    try:
        if hasattr(pipeline_options, "ocr_options") and getattr(pipeline_options, "ocr_options", None) is None:
            from docling.datamodel import pipeline_options as _docling_pipeline_options  # type: ignore
            for _ocr_cls_name in ("EasyOcrOptions", "TesseractOcrOptions", "TesseractCliOcrOptions", "OcrMacOptions"):
                _ocr_cls = getattr(_docling_pipeline_options, _ocr_cls_name, None)
                if _ocr_cls is None:
                    continue
                try:
                    pipeline_options.ocr_options = _ocr_cls()
                    break
                except Exception:
                    continue
    except Exception:
        pass
    try:
        pipeline_options.table_structure_options.do_cell_matching = bool(cfg.do_cell_matching)
    except Exception:
        pass
    try:
        if str(cfg.table_mode or '').strip().lower() == 'accurate':
            from docling.datamodel.pipeline_options import TableFormerMode  # type: ignore
            pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
    except Exception:
        pass

    converter_start = time.perf_counter()
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )
    timing['converter_init_ms'] = round((time.perf_counter() - converter_start) * 1000.0, 2)

    tables: List[StructuredTable] = []
    with PdfDocumentSession(pdf_bytes) as session:
        page_count = session.page_count
        for req in extraction_request.requests:
            page_no = int(req.page)
            if page_no < 1 or page_no > page_count:
                continue
            page_pdf = session.slice_bytes(page_no, page_no)
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp.write(page_pdf)
                tmp_path = tmp.name
            try:
                convert_start = time.perf_counter()
                conv_res = converter.convert(tmp_path)
                timing[f'convert_page_{page_no}_ms'] = round((time.perf_counter() - convert_start) * 1000.0, 2)
                document = getattr(conv_res, 'document', None)
                page_tables = list(getattr(document, 'tables', None) or [])
                model = _resolve_model(req.kind_hint, req.family_hint or '', extraction_request)
                for table_ix, table_item in enumerate(page_tables):
                    data = getattr(table_item, 'data', None)
                    matrix_rows = _normalize_matrix_from_grid(getattr(data, 'grid', None))
                    if not matrix_rows:
                        try:
                            table_df = table_item.export_to_dataframe(doc=document)
                            matrix_rows = [list(map(_flatten_cell_text, table_df.columns.tolist()))]
                            for _, row in table_df.iterrows():
                                matrix_rows.append([_flatten_cell_text(v) for v in row.tolist()])
                        except Exception:
                            matrix_rows = []
                    if not matrix_rows:
                        continue
                    semantics = resolve_table_columns(matrix_rows, model=model)
                    header_rows = _header_rows_from_data(data, matrix_rows)
                    columns = _build_columns(data=data, matrix_rows=matrix_rows, semantics=semantics, header_rows=header_rows)
                    rows = _build_rows_from_docling_data(page_no=page_no, data=data, matrix_rows=matrix_rows, semantics=semantics, header_rows=header_rows)
                    tables.append(StructuredTable(
                        table_id=req.table_id or f'{req.kind_hint}:p{page_no}:t{table_ix}',
                        kind=req.kind_hint,
                        family=req.family_hint or ('budget' if req.kind_hint == 'orcamento_sintetico' else 'sinapi_like'),
                        page_start=page_no,
                        page_end=page_no,
                        bbox=_table_item_bbox(table_item, data),
                        header_rows=header_rows,
                        body_rows_start=(max(header_rows) + 1) if header_rows else 0,
                        column_schema=columns,
                        rows=rows,
                        confidence=float(semantics.get('confidence') or 0.8),
                        source='docling_python',
                        metadata={
                            'table_index': table_ix,
                            'num_rows': len(matrix_rows),
                            'num_cols': max((len(r) for r in matrix_rows), default=0),
                        },
                    ))
            finally:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    timing['total_ms'] = round((time.perf_counter() * 1000.0) - timing.get('total_start_ms', 0.0), 2)
    timing.pop('total_start_ms', None)
    return StructuredTableBundle(
        contract_version=CONTRACT_VERSION,
        source='docling_python',
        tables=tables,
        metadata={
            'request_count': len(extraction_request.requests),
            'matched_tables': len(tables),
            'runtime': get_embedded_docling_runtime_info(),
            'timing': timing,
        },
    )
