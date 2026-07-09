from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'parser_browser'))

from app.core.correction_report import build_correction_document
from app.browser.recovery_agent import rebuild_correction_document, apply_targeted_recovery_to_final_result

VERSION = 'v61.0.39-deep-area-sweep-iterative-closure'


def _valid_sicro_compositions():
    return {
        'principais': {
            '5503041|SICRO': {
                'item': '3.1.4',
                'pagina_inicio': 10,
                'pagina_fim': 10,
                'paginas': [10],
                'principal': {
                    'codigo': '5503041', 'banco': 'SICRO3', 'descricao': 'Compactação de aterros',
                    'und': 'm³', 'quant': '1,0000000', 'valor_unit': '6,05', 'total': '6,05'
                },
                'sicro': {
                    'secoes': {
                        'A': {'linhas': [{
                            'codigo': 'E9010', 'banco': 'SICRO3', 'equipamento': 'Balança plataforma digital',
                            'quantidade': '1,0000000',
                            'utilizacao': {'operativa': '1,00', 'improdutiva': '0,00'},
                            'custo_operacional': {'operativa': '1,2680', 'improdutiva': '0,8518'},
                            'custo_horario': '1,2680'
                        }]}
                    },
                    'validacao': {'ok': True}
                }
            }
        },
        'auxiliares_globais': {}
    }


def _nested(compositions):
    return {
        'sinapi_like': {'principais': {}, 'auxiliares_globais': {}},
        'sicro': compositions,
    }


def _problem_keys(doc):
    return {entry.get('chave') for entry in doc.get('composicoes_com_problema') or []}


def test_correction_from_synthetic_sicro_has_no_false_missing_fields():
    doc, _ = build_correction_document(_valid_sicro_compositions(), version=VERSION)
    assert doc['resumo']['total_registros_com_erro'] == 0
    assert doc['resumo']['total_blocos_com_campos_vazios'] == 0
    assert '5503041|SICRO' not in _problem_keys(doc)


def test_correction_builder_accepts_nested_v61_0_23_family_contract():
    doc, _ = build_correction_document(_nested(_valid_sicro_compositions()), version=VERSION)
    assert doc['resumo']['total_registros_com_erro'] == 0
    assert '5503041|SICRO' not in _problem_keys(doc)


def test_rebuild_correction_uses_final_result_and_filters_sicro_valid_blocks():
    final_result = {'composicoes': _nested(_valid_sicro_compositions()), 'documento_correcao': {'resumo': {'total_registros_com_erro': 14}}}
    doc = rebuild_correction_document(final_result, version=VERSION)
    assert doc['resumo']['total_registros_com_erro'] == 0
    assert not any(str(k or '').endswith('|SICRO') for k in _problem_keys(doc))
    assert doc.get('audit', {}).get('correction_preliminary_resumo') is None


def test_correction_report_source_has_sicro_aware_guard():
    source = (ROOT / 'parser_browser/app/core/correction_report.py').read_text(encoding='utf-8')
    assert '_sicro_correction_status' in source
    assert 'sicro_native_validated' in source
    assert 'if not sicro_contract_ok' in source


def test_targeted_recovery_rebuilds_final_correction_without_sicro_false_positives():
    prelim, _ = build_correction_document(_valid_sicro_compositions(), version=VERSION)
    final = {
        'composicoes': _nested(_valid_sicro_compositions()),
        'documento_correcao': prelim,
        'validacao': {'ocorrencias': [{'codigo': 'campos_vazios', 'severidade': 'erro', 'categoria': 'composicoes'}], 'resumo': {'total_erros': 1, 'tem_erros': True}},
    }
    result = apply_targeted_recovery_to_final_result(final, {'attempted': True, 'patches': []}, version=VERSION)
    doc = result['documento_correcao']
    assert doc['resumo']['total_registros_com_erro'] == 0
    assert doc['resumo']['total_blocos_com_campos_vazios'] == 0
    assert not any(str(k or '').endswith('|SICRO') for k in _problem_keys(doc))
    assert result['validacao']['resumo']['total_erros'] == 0
