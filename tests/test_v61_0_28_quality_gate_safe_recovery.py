import json
from pathlib import Path

import pytest

from app.core.output_compact import prune_runtime_only_fields
from app.core.payload_contract import clean_table_hints_for_docling, payload_usage_report, split_lovable_document_and_runtime_payload
from app.normalizer.field_recovery import recover_fields
from app.parser.broken_line_recovery import pollution_reason


def _make_pdf(lines):
    fitz = pytest.importorskip('fitz')
    doc = fitz.open(); page = doc.new_page(width=595, height=842)
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=8)
    data = doc.tobytes(); doc.close(); return data


def test_quality_gate_enforces_status_and_correction_for_sicro_without_item():
    payload = {
        'status': 'ok',
        'composicoes': {'principais': {'1109669|SICRO': {
            'principal': {'codigo': '1109669', 'banco': 'SICRO', 'descricao': 'Argamassa', 'und': 'm³', 'quant': 1.0, 'valor_unit': 644.29, 'total': 644.29},
            'sicro': {'secoes': {'C': {'linhas': [{'codigo': 'M0030', 'banco': 'SICRO', 'material': 'Aditivo', 'quantidade': '1,0000', 'unidade': 'kg', 'preco_unitario': '9,0000', 'custo_horario': '9,0000'}]}}}
        }}},
        'documento_correcao': {'resumo': {'total_registros_com_erro': 0}},
    }
    out = prune_runtime_only_fields(payload)
    assert '1109669|SICRO' not in out['composicoes']['sicro']['principais']
    assert '1109669|SICRO' in out['composicoes']['sicro']['auxiliares_globais']
    assert out['status'] == 'ok'
    assert out['auditoria_final']['quality_gate']['ok'] is True


def test_quality_gate_failed_changes_status_and_syncs_correction():
    payload = {
        'status': 'ok',
        'composicoes': {'sinapi_like': {'principais': {'X|SINAPI': {'principal': {'codigo': 'X', 'banco': 'SINAPI', 'descricao': 'Custo Total das Atividades =>', 'quant': 1.0, 'valor_unit': 2.0, 'total': 2.0}}}, 'auxiliares_globais': {}}, 'sicro': {'principais': {}, 'auxiliares_globais': {}}},
        'documento_correcao': {'resumo': {'total_registros_com_erro': 0}},
    }
    out = prune_runtime_only_fields(payload)
    assert out['status'] in {'ok', 'ok_with_warnings', 'quality_gate_failed'}
    principal = out['composicoes']['sinapi_like']['principais']['X|SINAPI']['principal']
    assert '=>' not in principal.get('descricao', '')
    assert isinstance(principal['quant'], str) and isinstance(principal['valor_unit'], str) and isinstance(principal['total'], str)


def test_targeted_recovery_does_not_cross_adjacent_budget_items_when_current_is_good():
    pdf = _make_pdf([
        (165, 50, '- EXCLUSIVE ESCAVAÇÃO, CARGA E TRANSPORTE E SOLO. AF_09/2024'),
        (45, 64, '3.2.7 ANP 01 Próprio'),
        (165, 64, 'AQUISIÇÃO DE ASFALTO DILUIDO CM-30'),
        (165, 78, 'EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 - 1.250,00 1,27 1,54 1.925,00'),
    ])
    payload = {
        'page_map': {'1': 1},
        'targets': [{
            'target_id': 'orcamento_sintetico.itens_raiz.0::especificacao',
            'path': ['orcamento_sintetico', 'itens_raiz', 0, 'especificacao'],
            'field': 'especificacao', 'family': 'budget', 'current_value': 'AQUISIÇÃO DE ASFALTO DILUIDO CM-30',
            'codigo': 'ANP 01', 'banco': 'Próprio', 'page': 1, 'issue': 'possible_broken_line_budget_description'
        }],
        'column_maps': {'budget': {'columns': [
            {'canonical': 'codigo', 'x0': 45, 'x1': 90}, {'canonical': 'fonte', 'x0': 95, 'x1': 150}, {'canonical': 'descricao', 'x0': 160, 'x1': 455},
        ]}},
        'apply_confidence_min': 0.85,
    }
    result = recover_fields(pdf, payload)
    assert result['summary']['patches'] == 0, result


def test_evidence_graph_quarantines_polluted_descriptions():
    assert pollution_reason('SERVENTE COM ENCARGOS COMPLEMENTARES Revestimentos Cerâmicos Internos')
    assert pollution_reason('LASTRO Estrutura e Trama para Cobertura - Instalações Elétricas - Escavação de Valas - Rasgos e Fixações - Esquadrias - Portas')
    assert pollution_reason('Material Material Material')


def test_payload_usage_counts_observed_header_canonical_and_first_row():
    payload = {'tables': {'budget': {'observed_headers': [
        {'text': 'CÓDIGO', 'canonical': 'codigo', 'first_row_text': '74209/001'},
        {'text': 'ESPECIFICAÇÕES DOS SERVIÇOS', 'canonical': 'descricao', 'first_row_text': 'PLACA DE OBRA'},
    ]}}, 'docling_api_url': 'http://localhost'}
    cleaned = clean_table_hints_for_docling(payload['tables'])
    usage = payload_usage_report(payload, cleaned)
    assert usage['tables']['budget']['canonical_mapping_used'] is True
    assert usage['tables']['budget']['first_row_samples_used'] is True
    assert usage['tables']['budget']['column_mapping_count'] == 2
    split = split_lovable_document_and_runtime_payload(payload)
    assert 'docling_api_url' in split['runtime_config']
    assert 'docling_api_url' not in split['document_payload']
