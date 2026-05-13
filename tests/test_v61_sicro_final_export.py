import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'parser_browser'))

from app.core.output_compact import prune_runtime_only_fields


def test_final_export_preserves_sicro_columns_and_splits_family_contract():
    payload = {
        'composicoes': {
            'principais': {
                '1107892|SICRO': {
                    'item': '3.1.4',
                    'principal': {
                        'codigo': '1107892', 'banco': 'SICRO3', 'descricao': 'Concreto fck = 20 MPa',
                        'tipo': 'Composição', 'natureza': '', 'und': 'm³', 'quant': '1,0000000',
                        'valor_unit': '678,85', 'total': '678,85', 'banco_coluna': 'SICRO3'
                    },
                    'composicoes_auxiliares': [{'codigo': 'fake'}],
                    'insumos': [{'codigo': 'fake'}],
                    'detalhes': {
                        'docling_assistance': {'columns_used': ['valor_unit', 'descricao']},
                        'sicro': {
                            'secoes': {
                                'A': [{
                                    'codigo': 'E9010', 'banco': 'SICRO3', 'descricao': 'Balança plataforma digital',
                                    'tipo_status': '', 'row_uid': '', 'block_uid': '', 'quant': 1, 'valor_unit': 1.268,
                                    'total': 1.268, 'banco_coluna': 'SICRO3',
                                    'detalhes': {'numeric_source': {
                                        'quant': {'source_text': '1,0000000'},
                                        'utilizacao_operativa': {'source_text': '1,00'},
                                        'utilizacao_improdutiva': {'source_text': '0,00'},
                                        'custo_operacional_operativa': {'source_text': '1,2680'},
                                        'custo_operacional_improdutiva': {'source_text': '0,8518'},
                                        'custo_horario': {'source_text': '1,2680'},
                                    }}
                                }]
                            }
                        }
                    }
                }
            }
        },
        'documento_correcao': {'resumo': {'total_registros_com_erro': 0, 'total_divergencias_matematicas': 0}},
        'validacao': {'ocorrencias': [{'codigo': 'old_error'}], 'resumo': {'total_erros': 4, 'tem_erros': True}}
    }
    out = prune_runtime_only_fields(payload)
    assert set(out['composicoes']) >= {'sinapi_like', 'sicro'}
    block = out['composicoes']['sicro']['principais']['1107892|SICRO']
    principal = block['principal']
    assert principal['codigo'] == '1107892'
    assert principal['banco'] == 'SICRO3'
    assert principal['banco_canonico'] == 'SICRO'
    assert principal['tipo'] == 'Composição'
    assert principal['descricao'] == 'Concreto fck = 20 MPa'
    assert principal['und'] == 'm³'
    assert principal['quant'] == '1,0000000'
    assert principal['valor_unit'] == '678,85'
    assert principal['total'] == '678,85'
    assert principal['servico'] == 'Concreto fck = 20 MPa'
    assert principal['unidade'] == 'm³'
    assert principal['quantidade'] == '1,0000000'
    assert principal['custo_unitario'] == '678,85'
    assert principal['custo_total'] == '678,85'
    assert 'composicoes_auxiliares' not in block and 'insumos' not in block
    assert 'detalhes' not in block
    assert set(block['sicro']) == {'secoes'}
    eq = block['sicro']['secoes']['A']['linhas'][0]
    assert eq['descricao'] == 'Balança plataforma digital'
    assert eq['equipamento'] == 'Balança plataforma digital'
    assert eq['quantidade'] == '1,0000000'
    assert eq['valor_unit'] == '1,268'
    assert eq['total'] == '1,268'
    assert eq['custo_operacional']['operativa'] == '1,2680'
    assert eq['custo_horario'] == '1,2680'
    text = str(block)
    for forbidden in ('row_uid', 'tipo_status', 'block_uid', 'numeric_source'):
        assert forbidden not in text
    assert out['auditoria_final']['quality_gate']['ok'] is True
    assert out['validacao']['resumo']['total_erros'] == 0
    assert out['validacao']['resumo']['tem_erros'] is False
    assert out['validacao']['ocorrencias'] == []
