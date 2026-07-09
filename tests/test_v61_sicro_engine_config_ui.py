import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'parser_browser'))

from app.parser.sicro_engine import (
    classify_code_token,
    classify_unit,
    infer_section_from_header,
    numeric_profile,
    resolve_code_bank,
    validate_public_sicro_row,
)

CFG = json.loads((ROOT / 'parser_browser' / 'db' / 'base_config.json').read_text(encoding='utf-8'))


def test_base_config_has_ui_editable_knowledge_tree():
    assert CFG['_schema_version'] == 'v61.0.39-deep-area-sweep-iterative-closure'
    assert 'config_ui' in CFG
    assert 'knowledge_bases' in CFG
    assert {'banks', 'units', 'numeric_profiles', 'sicro'}.issubset(CFG['knowledge_bases'])
    groups = {g['id'] for g in CFG['config_ui']['editable_groups']}
    assert {'banks', 'units', 'numeric_profiles', 'sicro_sections', 'sicro_codes', 'sicro_method', 'output'}.issubset(groups)


def test_sicro_code_bank_resolution_is_content_based():
    code, bank, ev = resolve_code_bank('SICRO3', 'M0030', CFG['knowledge_bases']['sicro'])
    assert code == 'M0030'
    assert bank == 'SICRO3'
    assert ev['first_is_bank'] is True
    code, bank, ev = resolve_code_bank('E9010', 'SICRO3', CFG['knowledge_bases']['sicro'])
    assert code == 'E9010'
    assert bank == 'SICRO3'


def test_sicro_classifiers_cover_units_codes_and_sections():
    assert classify_code_token('E9010', CFG['knowledge_bases']['sicro']) == 'equipamento'
    assert classify_code_token('P9821', CFG['knowledge_bases']['sicro']) == 'mao_obra'
    assert classify_code_token('M0030', CFG['knowledge_bases']['sicro']) == 'material'
    assert classify_code_token('5914655', CFG['knowledge_bases']['sicro']) == 'composicao_atual_7_digitos'
    assert classify_code_token('2 S 01 100 00', CFG['knowledge_bases']['sicro']) == 'sicro2_legado_espacado'
    assert classify_unit('t.km', CFG['knowledge_bases']['sicro']) == 'transport'
    assert numeric_profile('1,2680') == 'cost_4'
    assert numeric_profile('0,0008500') == 'quantity_high_precision'
    assert infer_section_from_header('F Banco Insumo Momento de Transporte DMT LN RP P') == 'F'


def test_public_sicro_row_validation_blocks_float_pollution():
    row = {
        'codigo': 'E9010',
        'banco': 'SICRO',
        'equipamento': 'Balança plataforma digital',
        'quantidade': '1,0000000',
        'utilizacao': {'operativa': '1,00', 'improdutiva': '0,00'},
        'custo_operacional': {'operativa': '1,2680', 'improdutiva': '0,8518'},
        'custo_horario': '1,2680',
    }
    assert validate_public_sicro_row('A', row, CFG['knowledge_bases']['sicro'])['ok'] is True
    polluted = dict(row)
    polluted['custo_horario'] = 1.268
    result = validate_public_sicro_row('A', polluted, CFG['knowledge_bases']['sicro'])
    assert result['ok'] is False
    assert any('float_public_value' in w for w in result['warnings'])
