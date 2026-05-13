import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'parser_browser'))

from app.parser.sicro import _parse_section_line
from app.core.output_compact import prune_runtime_only_fields


def _public_block():
    rows = {}
    lines = {
        'A': 'Insumo E9010 SICRO3 Balança plataforma digital 1,0000000 1,00 0,00 1,2680 0,8518 1,2680',
        'C1': 'Insumo SICRO3 M0030 Aditivo plastificante e retardador de pega 0,8464600 kg 9,3695 7,9309',
        'C2': 'Insumo SICRO3 M0082 Areia média 0,6330000 m³ 89,0000 56,3370',
        'C3': 'Insumo SICRO3 M0191 Brita 1 0,3675400 m³ 326,1030 119,8576',
        'C4': 'Insumo SICRO3 M0192 Brita 2 0,3675400 m³ 326,1030 119,8576',
        'C5': 'Insumo SICRO3 M0424 Cimento Portland CP II - 32 280,0000000 kg 0,5900 165,2000',
    }
    rows['A'] = [_parse_section_line('A', lines['A'])[0].model_dump()]
    rows['C'] = [_parse_section_line('C', lines[f'C{i}'])[0].model_dump() for i in range(1, 6)]
    payload = {
        'composicoes': {
            'principais': {
                '1107892|SICRO': {
                    'item': '7.1.1',
                    'principal': {'codigo': '1107892', 'banco': 'SICRO3', 'descricao': 'Concreto fck = 20 MPa', 'tipo': 'Composição', 'und': 'm³', 'quant': '1,0000000', 'valor_unit': '678,85', 'total': '678,85'},
                    'paginas': [72, 73],
                    'detalhes': {'sicro': {'secoes': rows, 'validacao': {'ok': True}}},
                }
            }
        },
        'documento_correcao': {'resumo': {'total_registros_com_erro': 0, 'total_divergencias_matematicas': 0}},
    }
    return prune_runtime_only_fields(payload)['composicoes']['sicro']['principais']['1107892|SICRO']


def test_sicro_sections_are_public_contract_and_not_sinapi_like():
    block = _public_block()
    secoes = block['sicro']['secoes']
    assert set(secoes) >= {'A', 'C'}
    first_equipment = secoes['A']['linhas'][0]
    assert first_equipment['equipamento'].startswith('Balança plataforma')
    assert first_equipment['descricao'].startswith('Balança plataforma')
    assert first_equipment['custo_horario'] == '1,2680'
    assert first_equipment['custo_operacional']['operativa'] == '1,2680'
    assert 'composicoes_auxiliares' not in block and 'insumos' not in block


def test_sicro_material_rows_do_not_merge_multiple_materials():
    materials = _public_block()['sicro']['secoes']['C']['linhas']
    codes = [r['codigo'] for r in materials]
    assert codes[:5] == ['M0030', 'M0082', 'M0191', 'M0192', 'M0424']
    m0191 = next(r for r in materials if r['codigo'] == 'M0191')
    assert m0191['material'] == 'Brita 1'
    assert m0191['quantidade'] == '0,3675400'
    assert m0191['custo_horario'] == '119,8576'
    assert 'M0192' not in m0191['material']


def test_sicro_page_span_and_no_runtime_fields_in_sections():
    block = _public_block()
    assert block['pagina_inicio'] == 72
    assert block['pagina_fim'] == 73
    assert block['paginas'] == [72, 73]
    text = str(block['sicro'])
    for forbidden in ('row_uid', 'tipo_status', 'block_uid', 'page_hint', 'row_index_in_block', 'numeric_source'):
        assert forbidden not in text
