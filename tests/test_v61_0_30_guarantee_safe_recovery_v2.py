from __future__ import annotations

import pytest

from app.core.output_compact import prune_runtime_only_fields
from app.core.schemas import BlocoComposicao, Composicoes, LinhaComposicao, OrcamentoItem, OrcamentoSintetico
from app.normalizer.field_recovery import recover_fields
from app.parser.budget_composition_reconcile import reconcile_budget_against_compositions
from app.parser.page_line_graph import build_page_line_graph, line_barrier_reason


def _make_pdf(lines):
    fitz = pytest.importorskip('fitz')
    doc = fitz.open(); page = doc.new_page(width=640, height=240)
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=9)
    data = doc.tobytes(); doc.close(); return data


def test_cross_table_reconcile_runs_first_and_repairs_composition_from_budget_when_safe():
    full = 'ESCAVAÇÃO MANUAL DE VALA COM PROFUNDIDADE MENOR OU IGUAL A 1,30 M. AF_09/2024'
    orc = OrcamentoSintetico(itens_raiz=[
        OrcamentoItem(tipo='item', item='4.1.1.1', codigo='93358', fonte='SINAPI', especificacao=full, und='m³')
    ])
    comp = Composicoes(principais={
        '93358|SINAPI': BlocoComposicao(
            item='4.1.1.1',
            principal=LinhaComposicao(codigo='93358', banco='SINAPI', descricao='ESCAVAÇÃO MANUAL DE VALA COM', und=''),
        )
    })
    _, changes, ocorrencias = reconcile_budget_against_compositions(orc, comp)
    assert comp.principais['93358|SINAPI'].principal.descricao == full
    assert comp.principais['93358|SINAPI'].principal.und == 'm³'
    assert any(c['tipo'] == 'composicao_descricao_reconciliada_orcamento' for c in changes)
    assert any(o['etapa'] == 'cross_table_reconcile_first_pass' for o in ocorrencias)


def test_page_line_graph_marks_budget_financial_and_item_boundaries():
    lines = [
        {'text': '3.2.7 ANP 01 Próprio AQUISIÇÃO DE ASFALTO DILUIDO CM-30 t', 'words': []},
        {'text': 'EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 - 1.250,00 1,27 1,54 1.925,00', 'words': []},
        {'text': 'fragmento solto limpo', 'words': []},
    ]
    assert line_barrier_reason(lines[0], family='budget') == 'budget_item_boundary'
    assert line_barrier_reason(lines[1], family='budget') == 'financial_values_boundary'
    graph = build_page_line_graph(lines, family='budget')
    assert graph['barrier_count'] == 2
    assert graph['floating_fragment_count'] == 1


def test_recovery_uses_learned_document_profile_when_column_maps_are_absent():
    pdf = _make_pdf([
        (45, 50, '1.1 90777 SINAPI'),
        (165, 50, 'ENGENHEIRO CIVIL DE OBRA JUNIOR COM'),
        (165, 63, 'ENCARGOS COMPLEMENTARES'),
    ])
    payload = {
        'page_map': {'1': 1},
        'targets': [{
            'target_id': 'orcamento_sintetico.itens_raiz.0::especificacao',
            'path': ['orcamento_sintetico', 'itens_raiz', 0, 'especificacao'],
            'field': 'especificacao', 'family': 'budget', 'table_family': 'budget',
            'current_value': 'ENGENHEIRO CIVIL DE OBRA JUNIOR COM',
            'codigo': '90777', 'banco': 'SINAPI', 'page': 1,
            'issue': 'possible_truncated_budget_description',
        }],
        'document_learning_profile': {
            'budget_profile': {'column_bands': {'descricao': {'x0_median': 160, 'x1_median': 455}}}
        },
        'apply_confidence_min': 0.85,
    }
    result = recover_fields(pdf, payload)
    assert result['summary']['patches'] == 1, result
    patch = result['patches'][0]
    assert patch['value'].endswith('ENCARGOS COMPLEMENTARES')
    assert patch['evidence']['descricao_band']['x0'] == 160
    assert patch['evidence']['page_line_graph_summary']['line_count'] >= 2


def test_recovery_rejects_long_candidate_when_current_is_already_good_even_if_issue_says_broken():
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
        'description_registry': {'ANP01|PRÓPRIO': {'descricao': 'AQUISIÇÃO DE ASFALTO DILUIDO CM-30', 'confirmed': True}},
        'apply_confidence_min': 0.85,
    }
    result = recover_fields(pdf, payload)
    assert result['summary']['patches'] == 0, result
    assert result['unresolved'][0]['reason'] in {'no_op_same_value', 'low_confidence_or_no_improvement'}


def test_guarantee_layer_formats_budget_public_numbers_and_flags_unsynced_gate():
    final = {
        'status': 'ok',
        'orcamento_sintetico': {'total': 1000.5, 'itens_raiz': [
            {'tipo': 'item', 'item': '1.1', 'codigo': 'X1', 'fonte': 'SINAPI', 'especificacao': 'SERVIÇO LIMPO', 'quant': 1.0, 'custo_unitario_com_bdi': 20.5, 'custo_parcial': 20.5}
        ]},
        'composicoes': {'sinapi_like': {'principais': {}, 'auxiliares_globais': {}}, 'sicro': {'principais': {}, 'auxiliares_globais': {}}},
        'documento_correcao': {'resumo': {'total_registros_com_erro': 0}},
    }
    out = prune_runtime_only_fields(final)
    item = out['orcamento_sintetico']['itens_raiz'][0]
    assert isinstance(out['orcamento_sintetico']['total'], str)
    assert isinstance(item['quant'], str)
    assert isinstance(item['custo_unitario_com_bdi'], str)
    assert out['auditoria_final']['quality_gate']['ok'] is True
