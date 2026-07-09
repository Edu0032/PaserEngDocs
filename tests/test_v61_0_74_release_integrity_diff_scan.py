from pathlib import Path


def test_v61_0_74_diff_scan_is_occurrence_aware(tmp_path):
    import fitz
    from app.parser.light_reextraction_diff_scan import build_light_reextraction_diff_scan_file

    pdf = tmp_path / 'occurrences.pdf'
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), 'Insumo 12345 SINAPI SERVICO EXISTENTE Material UN 1,0000000 10,00 10,00')
    p2 = doc.new_page()
    p2.insert_text((72, 72), 'Insumo 12345 SINAPI SERVICO OUTRA OCORRENCIA Material UN 2,0000000 10,00 20,00')
    doc.save(pdf)
    doc.close()

    result = {
        'composicoes': {
            'principais': {
                'ABC|SINAPI': {
                    'pagina_inicio': 1,
                    'pagina_fim': 1,
                    'paginas': [1],
                    'principal': {'codigo': '99999', 'banco': 'SINAPI'},
                    'insumos': [
                        {'codigo': '12345', 'banco': 'SINAPI', 'descricao': 'SERVICO EXISTENTE', 'und': 'UN', 'quant': '1,0000000', 'valor_unit': '10,00', 'total': '10,00'}
                    ],
                }
            }
        }
    }
    report = build_light_reextraction_diff_scan_file(str(pdf), result, {'light_diff_scan_max_samples': 10})
    assert report['status'] == 'needs_review'
    assert report['potential_missing_occurrence_count'] == 1
    sample = report['potential_missing_lines'][0]
    assert sample['page'] == 2
    assert sample['codigo_norm'] == '12345'
    assert sample['match_reason'] == 'same_code_but_no_occurrence_context_match'


def test_v61_0_74_active_base_config_has_no_document_specific_examples():
    bad = {'74209/001', '00006079', 'COMP.JCO.3', 'CP - 120', 'ANP 01', '5503041', '2003373'}
    for rel in ['parser_browser/db/base_config.json', 'api_docling/db/base_config.json']:
        text = Path(rel).read_text(encoding='utf-8')
        assert not any(token in text for token in bad)
