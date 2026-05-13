import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'parser_browser'))

from app.browser.service import _as_options
from app.config.knowledge_base import match_code_pattern
from app.intake.request_models import ParseDocumentRequestModel
from app.parser.sinapi_profile_recheck import _pollution_reason


def _cfg():
    return json.loads((ROOT / 'parser_browser' / 'db' / 'base_config.json').read_text(encoding='utf-8'))


def test_lightweight_lovable_payload_is_adapted_to_browser_options():
    payload = {
        'base_id': 'misto',
        'document': {'filename': 'orcamento.pdf', 'obra_nome': 'Obra teste'},
        'ranges': {'budget': {'start': 2, 'end': 4}, 'compositions': {'start': 9, 'end': 139}},
        'seed_pages': {'budget': 2, 'composition': 9},
        'document_hints': {'families_detected': ['sinapi_like', 'sicro'], 'custom_bank_ids': []},
        'observed_tables': {'composition_sinapi_like': {'headers_observed': ['Código', 'Banco'], 'first_row_samples': [{'canonical': 'codigo', 'text': '90777'}]}},
    }
    opts = _as_options(payload)
    assert opts.orcamento_inicio == 2 and opts.orcamento_fim == 4
    assert opts.composicoes_inicio == 9 and opts.composicoes_fim == 139
    assert opts.filename == 'orcamento.pdf'
    assert opts.docling_seed_pages == {'budget_header_page': 2, 'composition_schema_page': 9}
    assert opts.tables['composition']['first_row_samples'][0]['text'] == '90777'
    assert opts.ai_hints['page_family_hints']['families_detected'] == ['sinapi_like', 'sicro']


def test_request_model_accepts_v61_0_23_light_payload_shape():
    req = ParseDocumentRequestModel.model_validate({
        'base_id': 'misto',
        'document': {'filename': 'orcamento.pdf'},
        'ranges': {'budget': {'start': 2, 'end': 4}, 'compositions': {'start': 9, 'end': 139}},
        'seed_pages': {'budget': 2, 'composition': 9},
        'document_hints': {'families_detected': ['sicro']},
        'observed_tables': {'budget': {'headers_observed': ['ITEM'], 'first_row_samples': [{'canonical': 'codigo', 'text': '74209/001'}]}},
    })
    assert req.ranges['budget'].start == 2
    assert req.docling_seed_pages.composition_schema_page == 9
    assert req.tables['budget']['first_row_samples'][0]['text'] == '74209/001'
    assert req.browser_options()['metadata_extraida_ia']['table_hints']['budget']['observed_headers'] == ['ITEM']


def test_sinapi_code_regex_accepts_slash_and_dash_without_matching_money():
    cfg = _cfg()
    assert 'sinapi_composition' in match_code_pattern(cfg, '74209/001', family='sinapi_like')
    assert 'sinapi_composition' in match_code_pattern(cfg, '103672-01', family='sinapi_like')
    assert 'sinapi_composition' not in match_code_pattern(cfg, '6,05', family='sinapi_like')
    assert 'sinapi_composition' not in match_code_pattern(cfg, '1.234,56', family='sinapi_like')


def test_sinapi_recheck_pollution_vetoes_summary_and_numeric_noise():
    assert _pollution_reason('Custo Total das Atividades => 123,45')
    assert _pollution_reason('Material Material Material Material')
    assert _pollution_reason('644,2900 678,8500 41,4200 74,1700 99,0000')
    assert not _pollution_reason('ENGENHEIRO CIVIL DE OBRA JUNIOR COM ENCARGOS COMPLEMENTARES')
