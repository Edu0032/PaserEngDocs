from __future__ import annotations

from app.accuracy.debug_overlay import build_debug_overlay
from app.accuracy.metrics import compute_field_accuracy, generate_accuracy_report
from app.core.docling_cache import stable_docling_cache_key
from app.core.payload_contract import clean_table_hints_for_docling, payload_usage_report, split_lovable_document_and_runtime_payload
from app.parser.selective_reparse import build_weak_field_reparse_targets
from app.profile.docling_profile_calibrator import calibrate_docling_profile

VERSION = 'v61.0.39-deep-area-sweep-iterative-closure'


def test_payload_usage_counts_header_canonical_first_row_and_splits_runtime():
    payload = {
        'document': {'filename': 'x.pdf'},
        'ranges': {'budget': {'start': 2, 'end': 4}, 'compositions': {'start': 9, 'end': 20}},
        'seed_pages': {'budget': 2, 'composition': 9},
        'docling_api_url': 'http://localhost:8000/docling/extract-table-structure',
        'docling_timeout_ms': 120000,
        'tables': {'budget': {'observed_headers': [
            {'text': 'CÓDIGO', 'canonical': 'codigo', 'first_row_text': '74209/001'},
            {'text': 'ESPECIFICAÇÕES', 'canonical': 'descricao', 'sample_text': 'PLACA DE OBRA'},
        ]}},
    }
    split = split_lovable_document_and_runtime_payload(payload)
    assert 'docling_api_url' not in split['document_payload']
    assert split['runtime_config']['docling_api_url'].startswith('http')
    cleaned = clean_table_hints_for_docling(payload['tables'])
    usage = payload_usage_report(payload, cleaned)
    budget = usage['tables']['budget']
    assert budget['headers_used'] is True
    assert budget['canonical_mapping_used'] is True
    assert budget['first_row_samples_used'] is True
    assert budget['column_mapping_count'] == 2
    assert budget['first_row_sample_count'] == 2


def test_stable_docling_cache_key_ignores_json_order_and_changes_on_tables():
    key1 = stable_docling_cache_key(seed_text_sha256='abc', page_map={'1': 2}, tables={'budget': {'columns': [{'canonical': 'codigo'}, {'canonical': 'descricao'}]}}, crop_policy={'preserve_full_page': True}, parser_contract={'a': 1}, contract_version=VERSION)
    key2 = stable_docling_cache_key(seed_text_sha256='abc', page_map={'1': 2}, tables={'budget': {'columns': [{'canonical': 'codigo'}, {'canonical': 'descricao'}]}}, crop_policy={'preserve_full_page': True}, parser_contract={'a': 1}, contract_version=VERSION)
    key3 = stable_docling_cache_key(seed_text_sha256='abc', page_map={'1': 2}, tables={'budget': {'columns': [{'canonical': 'codigo'}]}}, crop_policy={'preserve_full_page': True}, parser_contract={'a': 1}, contract_version=VERSION)
    assert key1 == key2
    assert key1 != key3


def test_calibrated_profile_combines_docling_and_learned_pymupdf_bands():
    docling = {'budget': {'columns': [
        {'canonical': 'descricao', 'header': 'ESPECIFICAÇÕES', 'x0': 130.0, 'x1': 342.0, 'geometry_confidence': 0.8},
        {'canonical': 'und', 'header': 'UND', 'x0': 343.0, 'x1': 365.0, 'geometry_confidence': 0.96},
    ]}}
    learned = {'budget_profile': {'column_bands': {'descricao': {'x0_median': 132.0, 'x1_median': 345.0}}}}
    profile = calibrate_docling_profile(docling, document_learning_profile=learned)
    desc = profile['tables']['budget']['columns'][0]
    assert desc['geometry_source'] == 'docling+pymupdf_profile'
    assert desc['adjusted_by_pymupdf_profile'] is True
    assert profile['summary']['pymupdf_adjusted_columns'] == 1
    assert profile['tables']['budget']['profile_ready_for_recovery'] is True


def test_selective_reparse_targets_weak_budget_and_composition_fields():
    final = {
        'orcamento_sintetico': {'itens_raiz': [{'tipo': 'item', 'item': '1.1', 'codigo': '90777', 'fonte': 'SINAPI', 'especificacao': 'ENGENHEIRO CIVIL COM'}]},
        'composicoes': {'sinapi_like': {'principais': {'90777|SINAPI': {'pagina_inicio': 9, 'principal': {'codigo': '90777', 'banco': 'SINAPI', 'descricao': ''}}}}},
    }
    plan = build_weak_field_reparse_targets(final)
    assert plan['summary']['budget_targets'] == 1
    assert plan['summary']['composition_targets'] == 1
    assert all(t['action'] if 'action' in t else True for t in plan['profile_plan_targets'])


def test_accuracy_metrics_and_debug_overlay_are_useful_for_lovable_dashboard():
    expected = {'orcamento_sintetico': {'itens_raiz': [{'tipo': 'item', 'item': '1.1', 'codigo': '90777', 'fonte': 'SINAPI', 'especificacao': 'ENGENHEIRO CIVIL', 'und': 'H'}]}}
    actual = {'status': 'ok', 'orcamento_sintetico': {'itens_raiz': [{'tipo': 'item', 'item': '1.1', 'codigo': '90777', 'fonte': 'SINAPI', 'especificacao': 'ENGENHEIRO CIVIL', 'und': 'H'}]}, 'auditoria_final': {'quality_gate': {'ok': True, 'issues': []}}}
    metrics = compute_field_accuracy(actual, expected)
    assert metrics['overall_field_accuracy'] == 1.0
    report = generate_accuracy_report(VERSION, [{'name': 'golden_small_budget', 'actual': actual, 'expected': expected}])
    assert report['overall_field_accuracy'] == 1.0
    overlay = build_debug_overlay(actual, {'tables': {'budget': {'columns': [{'canonical': 'descricao', 'x0': 100, 'x1': 300}]}}}, {'patches': [], 'unresolved': []}, report)
    assert overlay['summary']['quality_gate_ok'] is True
    assert overlay['summary']['columns'] == 1
    assert overlay['summary']['accuracy'] == 1.0
