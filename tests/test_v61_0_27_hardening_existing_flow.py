from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.payload_contract import clean_table_hints_for_docling, payload_usage_report, validate_lovable_payload_contract
from app.core.schemas import OrcamentoItem, OrcamentoSintetico
from app.parser.budget_math_validator import validate_budget_math
from tools.quality_safety_scan import scan_project


def test_safety_scan_finds_no_invisible_regex_or_profession_hardcode_in_app_code():
    findings = scan_project(ROOT)
    assert findings == []


def test_sicro_section_regex_uses_word_boundary_not_backspace():
    text = (ROOT / 'parser_browser/app/parser/sicro_section_patterns.py').read_text(encoding='utf-8')
    assert '\x08' not in text
    assert 're.compile(r"^A\\b"' in text
    assert 're.compile(r"^F\\b"' in text
    comp = (ROOT / 'parser_browser/app/parser/compositions.py').read_text(encoding='utf-8')
    assert 'from app.parser.sicro_section_patterns import SICRO_SECTION_REGEXES' in comp


def test_api_docling_deploy_has_only_docling_service_and_valid_requirements():
    req = (ROOT / 'api_docling/requirements.txt').read_text(encoding='utf-8')
    assert '-r requirements.txt' not in req
    assert 'docling' in req
    assert 'fastapi' in req
    render = (ROOT / 'api_docling/render.yaml').read_text(encoding='utf-8')
    assert 'api-pdf-normalizer' not in render
    assert 'requirements-normalizer' not in render
    assert 'uvicorn app.main:app' in render


def test_docling_payload_contract_keeps_header_canonical_mapping_but_removes_fixed_keys():
    payload = {
        'ranges': {'budget': {'start': 1, 'end': 1}, 'compositions': {'start': 2, 'end': 2}},
        'seed_pages': {'budget': 1, 'composition': 2},
        'tables': {
            'composition': {
                'columns': [
                    {'header': 'CÓDIGO', 'canonical': 'codigo', 'sample_text': '90777'},
                    {'header': 'DESCRIÇÃO', 'canonical': 'descricao', 'sample_text': 'ENGENHEIRO CIVIL'},
                ],
                'regex': 'SHOULD_NOT_GO_TO_DOCLING',
                'parser_policy': {'internal': True},
            }
        },
        'fixed_contract': {'crop_policy': {'internal': True}},
        'parser_contract': {'bypass_docling_cache': True},
    }
    validation = validate_lovable_payload_contract(payload)
    clean = clean_table_hints_for_docling(payload['tables'])
    assert validation['ok'] is True
    assert clean['composition']['columns'][0]['canonical'] == 'codigo'
    assert clean['composition']['columns'][0]['header'] == 'CÓDIGO'
    assert 'regex' not in clean['composition']
    usage = payload_usage_report(payload, clean)
    assert usage['fixed_keys_detected'] == ['fixed_contract', 'parser_contract']
    assert usage['fixed_keys_forwarded_to_docling'] == []
    assert usage['tables']['composition']['canonical_mapping_used'] is True
    assert usage['tables']['composition']['first_row_samples_used'] is True


def test_api_file_exposes_payload_validator_and_metadata_usage_report():
    text = (ROOT / 'api_docling/app/api.py').read_text(encoding='utf-8')
    assert "/docling/validate-payload" in text
    assert "payload_usage" in text
    assert "normalization_owned_by':'browser_local_pyodide" in text or 'normalization_owned_by\': \'browser_local_pyodide' in text
    assert "'fixed_contract':{'crop_policy'" not in text
    assert "'parser_contract':{'docling_is_primary_structure_source'" not in text


def test_budget_math_validator_marks_divergence_as_recheck_candidate_not_fatal_error():
    orc = OrcamentoSintetico(itens_raiz=[
        OrcamentoItem(tipo='item', item='1.1', codigo='93358', fonte='SINAPI', especificacao='ESCAVAÇÃO', und='M3', quant='2,00', custo_unitario_com_bdi='10,00', custo_parcial='21,50')
    ])
    result = validate_budget_math(orc, tolerance_abs=0.05)
    assert result['status'] == 'warning'
    assert result['summary']['warnings'] == 1
    assert result['warnings'][0]['action'] == 'targeted_recheck_candidate'


def test_browser_and_docling_share_payload_contract_module_verbatim():
    browser = (ROOT / 'parser_browser/app/core/payload_contract.py').read_text(encoding='utf-8')
    api = (ROOT / 'api_docling/app/core/payload_contract.py').read_text(encoding='utf-8')
    assert browser == api
