import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'parser_browser'))

from app.parser.sicro import _parse_section_line
from app.parser.sicro_profile import identify_code_and_bank, classify_sicro_code
from app.core.output_compact import prune_runtime_only_fields


def _public_section_row(section, line):
    payload = {
        'composicoes': {
            'principais': {
                '1107892|SICRO': {
                    'principal': {'codigo': '1107892', 'banco': 'SICRO', 'descricao': 'Concreto', 'und': 'm³', 'quant': '1,0000000', 'valor_unit': '678,85', 'total': '678,85'},
                    'detalhes': {'sicro': {'secoes': {section: [line.model_dump()]}}},
                }
            }
        }
    }
    exported = prune_runtime_only_fields(payload)['composicoes']['sicro']
    block = (exported.get('principais') or {}).get('1107892|SICRO') or (exported.get('auxiliares_globais') or {})['1107892|SICRO']
    return block['secoes'][section]['linhas'][0]


def test_sicro_code_bank_inversion_is_detected_by_pattern():
    code, bank, evidence = identify_code_and_bank('SICRO3', 'M0030')
    assert code == 'M0030'
    assert bank == 'SICRO3'
    assert evidence['first_is_bank'] is True
    assert evidence['second_code_type'] == 'material'
    code, bank, evidence = identify_code_and_bank('E9010', 'SICRO3')
    assert code == 'E9010'
    assert bank == 'SICRO3'
    assert evidence['first_code_type'] == 'equipamento'


def test_sicro_code_patterns_cover_sections():
    assert classify_sicro_code('1107892') == 'composicao_principal'
    assert classify_sicro_code('E9010') == 'equipamento'
    assert classify_sicro_code('P9821') == 'mao_obra'
    assert classify_sicro_code('M0030') == 'material'


def test_sicro_material_preserves_preco_unitario_and_decimal_scale_as_public_text():
    line, target = _parse_section_line('C', 'Insumo SICRO3 M0030 Aditivo plastificante e retardador de pega 0,8464600 kg 9,3695 7,9309')
    assert target == 'insumo'
    row = _public_section_row('C', line)
    assert row['codigo'] == 'M0030'
    assert row['banco'] == 'SICRO'
    assert row['material'].startswith('Aditivo plastificante')
    assert row['quantidade'] == '0,8464600'
    assert row['preco_unitario'] == '9,3695'
    assert row.get('custo') == '7,9309'
    assert 'row_uid' not in row and 'tipo_status' not in row
    assert 'descricao' not in row
    assert 'valor_unit' not in row


def test_sicro_atividade_auxiliar_preserves_zeros():
    line, target = _parse_section_line('D', 'Atividade Auxiliar SICRO3 1109669 Argamassa de cimento e areia 1:3 0,0001000 m³ 644,2900 0,0644')
    assert target == 'auxiliar'
    row = _public_section_row('D', line)
    assert row['quantidade'] == '0,0001000'
    assert row['preco_unitario'] == '644,2900'
    assert row.get('custo') == '0,0644'


def test_sicro_tempo_fixo_keeps_two_codes_and_decimal_text():
    line, target = _parse_section_line('E', 'Tempo Fixo SICRO3 M0030 Carga, manobra e descarga de materiais 5914655 0,0008500 t 33,3400 0,0283')
    assert target == 'insumo'
    row = _public_section_row('E', line)
    assert row['codigo'] == '5914655'
    assert row['insumo'] == 'M0030'
    assert row['quantidade'] == '0,0008500'
    assert row['preco_unitario'] == '33,3400'
    assert row.get('custo') == '0,0283'
