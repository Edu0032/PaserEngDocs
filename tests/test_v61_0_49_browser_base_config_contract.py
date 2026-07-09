from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from app.config.loader import load_raw_config_with_fragments


def _extract_default_payload_from_demo() -> dict:
    html = Path('parser_browser/browser/demo/index.html').read_text(encoding='utf-8')
    m = re.search(r'const DEFAULT_PAYLOAD = (\{.*?\n\});', html, re.S)
    assert m, 'DEFAULT_PAYLOAD não encontrado no HTML demo'
    return json.loads(m.group(1))


def test_v49_base_config_contract_declares_payload_document_only_boundary():
    cfg = load_raw_config_with_fragments()
    contract = cfg['lovable_contract']
    assert contract['payload_scope'] == 'document_only'
    forbidden = set(contract['forbidden_payload_fields'])
    assert {'docling_api_url', 'docling_timeout_ms', 'runtime', 'performance', 'parser_contract', 'base_id'} <= forbidden
    assert cfg['browser_mode']['source_archive_must_include_db'] is True


def test_v49_demo_payload_contains_document_data_not_runtime_controls():
    payload = _extract_default_payload_from_demo()
    forbidden = {
        'docling_api_url', 'docling_api_key', 'docling_api_key_header', 'docling_timeout_ms',
        'normalizer_timeout_ms', 'normalizer_enabled', 'normalizer_mode', 'docling_seed_pdf_policy',
        'bypass_cache', 'clear_docling_cache_before_run', 'targeted_recovery_max_pages_per_batch',
        'request_timeout_ms', 'runtime', 'performance', 'output_options', 'parser_contract', 'base_id'
    }
    assert not (forbidden & set(payload)), f'Campos de runtime vazaram para o payload: {forbidden & set(payload)}'
    assert payload['ranges']['budget']['start'] == 2
    assert payload['docling_seed_pages']['composition'] == 9
    assert payload['tables']['budget']['observed_headers']
    assert payload['tables']['composition']['observed_headers']


def test_v49_pyodide_source_archive_contains_base_config_db():
    zip_path = Path('parser_browser/browser/pyodide/api_pdf_pyodide_src.zip')
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    assert 'db/base_config.json' in names
    assert 'db/base_config.d/95_payload_runtime_boundary.json' in names
    assert any(name.startswith('app/config/') for name in names)


def test_v49_demo_exposes_evidence_and_enrichment_tabs():
    html = Path('parser_browser/browser/demo/index.html').read_text(encoding='utf-8')
    assert 'data-tab="evidence"' in html
    assert 'data-tab="enrichment"' in html
    assert 'evidenceOut' in html
    assert 'enrichmentOut' in html
    assert 'HTML v61.0.59 carregado' in html
