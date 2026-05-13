from app.normalizer.sicro_section_maps import build_sicro_section_maps


def test_normalizer_builds_sicro_section_maps_from_geometry_lines():
    pages={1:{'lines':[{'text':'A Código Banco Equipamentos Quantidade Utilização Custo Operacional Custo Horário','words':[{'text':'A','x0':10,'y0':10,'x1':12,'y1':12}]},{'text':'F Banco Insumo Momento de Transporte Quantidade Unidade Custo Horário LN RP P','words':[{'text':'F','x0':10,'y0':50,'x1':12,'y1':52}]}]}}
    maps=build_sicro_section_maps(pages)
    assert 'A' in maps and 'F' in maps
    assert maps['A']['columns'][0]['canonical']=='controle_linha'
    assert any(c['canonical']=='momento_transporte' for c in maps['F']['columns'])
