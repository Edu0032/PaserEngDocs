import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'parser_browser'))

from app.domain.structured_table_models import StructuredColumn, StructuredTable, StructuredTableBundle
from app.integrations.docling_clean_adapter import build_clean_docling_payload_from_bundle


def test_docling_clean_payload_uses_first_row_samples_from_lovable_payload():
    bundle = StructuredTableBundle(
        contract_version='test',
        source='docling_test',
        tables=[StructuredTable(
            table_id='composition:seed',
            kind='composicao_sinapi_like',
            family='sinapi_like',
            page_start=9,
            page_end=9,
            bbox=[],
            header_rows=[0],
            body_rows_start=1,
            column_schema=[
                StructuredColumn(physical_index=0, canonical_name='codigo', header_text='Código', x0=10, x1=60, width=50, confidence=0.9),
                StructuredColumn(physical_index=1, canonical_name='banco', header_text='Banco', x0=60, x1=100, width=40, confidence=0.9),
            ],
            rows=[],
            confidence=0.9,
            source='docling_test',
            metadata={},
        )],
        metadata={},
    )
    source_payload = {
        'tables': {
            'composition': {
                'observed_headers': ['Código', 'Banco'],
                'first_row_samples': [
                    {'sample_text': '90777'},
                    {'sample_text': 'SINAPI'},
                ],
            }
        }
    }
    clean = build_clean_docling_payload_from_bundle(bundle, source_payload=source_payload, version='test')
    cols = clean['tables']['composition']['columns']
    assert cols[0]['sample_text'] == '90777'
    assert cols[0]['content_text'] == '90777'
    assert cols[1]['sample_text'] == 'SINAPI'
