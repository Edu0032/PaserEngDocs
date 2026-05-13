import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'parser_browser'))
from app.core.output_compact import prune_runtime_only_fields

def test_sicro_span_gap_guard_removes_intrusive_seed_page_without_hardcoding_9():
    payload={'composicoes':{'principais':{'1107892|SICRO':{'principal':{'codigo':'1107892','banco':'SICRO','descricao':'Concreto','und':'m³','quant':'1,0000000','valor_unit':'678,85','total':'678,85'},'paginas':[9,72,73],'sicro':{'resumos':{'custo_unitario_execucao':'678,85'}}}}}}
    exported=prune_runtime_only_fields(payload)['composicoes']['sicro']; block=(exported.get('principais') or {}).get('1107892|SICRO') or (exported.get('auxiliares_globais') or {})['1107892|SICRO']
    assert block['paginas']==[72,73]
    assert block['pagina_inicio']==72 and block['pagina_fim']==73

def test_sicro_span_uses_section_row_pages_when_available():
    payload={'composicoes':{'principais':{'1107892|SICRO':{'principal':{'codigo':'1107892','banco':'SICRO','descricao':'Concreto','und':'m³','quant':'1,0000000','valor_unit':'678,85','total':'678,85'},'paginas':[9,72,73],'detalhes':{'sicro':{'secoes':{'A':[{'codigo':'E9010','banco':'SICRO','descricao':'Balança','quant':1.0,'total':1.268,'detalhes':{'page':72,'numeric_source':{'quant':{'source_text':'1,0000000'},'custo_horario':{'source_text':'1,2680'}}}}]}}}}}}}
    exported=prune_runtime_only_fields(payload)['composicoes']['sicro']; block=(exported.get('principais') or {}).get('1107892|SICRO') or (exported.get('auxiliares_globais') or {})['1107892|SICRO']
    assert block['paginas']==[72]
    assert block['pagina_inicio']==72 and block['pagina_fim']==72
