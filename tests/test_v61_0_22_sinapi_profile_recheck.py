from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'parser_browser'))

from app.config.knowledge_base import validate_knowledge_base, match_code_pattern, list_units
from app.core.schemas import Composicoes, BlocoComposicao, LinhaComposicao, LinhaInsumo
from app.parser.sinapi_profile_recheck import apply_sinapi_profile_recheck
from app.browser.recovery_agent import apply_targeted_recovery_to_final_result


def _cfg():
    return json.loads((ROOT / 'parser_browser' / 'db' / 'base_config.json').read_text(encoding='utf-8'))

def test_knowledge_base_is_expandable_and_regex_valid():
    cfg = _cfg()
    kb = cfg.get('knowledge_base') or {}
    assert kb.get('editable_via_lovable') is True
    assert any(b.get('canonical') == 'SICRO' for b in kb.get('banks') or [])
    assert any(u.get('canonical') == 'tkm' for u in kb.get('units') or [])
    result = validate_knowledge_base(cfg)
    assert result['ok'], result
    assert result['checked_regex'] >= 10
    assert 'sinapi_composition' in match_code_pattern(cfg, '90777', family='sinapi_like')
    assert 'sicro_equipamento' in match_code_pattern(cfg, 'E9571', family='sicro')
    assert any(u.get('canonical') == 'm³' for u in list_units(cfg, family='sinapi_like'))


def test_sinapi_profile_recheck_repairs_truncated_description_from_registry():
    cfg = _cfg()
    complete = LinhaComposicao(codigo='95402', banco='SINAPI', descricao='CURSO DE CAPACITAÇÃO PARA ENGENHEIRO CIVIL DE OBRA JÚNIOR (ENCARGOS COMPLEMENTARES) - HORISTA', und='H', quant=1, valor_unit=1.85, total=1.85)
    truncated = LinhaComposicao(codigo='95402', banco='SINAPI', descricao='CURSO DE CAPACITAÇÃO PARA', und='H', quant=1, valor_unit=1.85, total=1.85)
    block1 = BlocoComposicao(principal=complete)
    block2 = BlocoComposicao(principal=truncated)
    comp = Composicoes(principais={'95402|SINAPI': block1}, auxiliares_globais={'95402_TRUNC|SINAPI': block2})
    report = apply_sinapi_profile_recheck(comp, context={'structured_tables': {'tables': {'composition': {'columns': [{'canonical':'descricao','x0':145,'x1':358}]}}}}, config=cfg)
    assert report['metrics']['description_registry_entries'] >= 1
    assert report['metrics']['description_repairs_applied'] == 1
    assert comp.auxiliares_globais['95402_TRUNC|SINAPI'].principal.descricao.endswith('HORISTA')
    assert report['column_bands']['descricao']['x0_median'] == 145


def test_sinapi_profile_recheck_fills_missing_total_conservatively():
    cfg = _cfg()
    row = LinhaComposicao(codigo='12345', banco='SINAPI', descricao='Teste', und='UN', quant=2, valor_unit=10.5, total=None)
    block = BlocoComposicao(principal=row)
    comp = Composicoes(principais={'12345|SINAPI': block})
    report = apply_sinapi_profile_recheck(comp, context={}, config=cfg)
    assert report['metrics']['math_repairs_applied'] == 1
    assert comp.principais['12345|SINAPI'].principal.total == 21.0


def test_targeted_recovery_syncs_validation_summary_when_correction_is_clean():
    final = {
        'composicoes': {'principais': {}, 'auxiliares_globais': {}, 'aliases_auxiliares': {}},
        'validacao': {'ocorrencias': [{'codigo': 'campos_vazios', 'severidade': 'erro', 'categoria': 'composicoes', 'mensagem': 'preliminar'}], 'resumo': {'total_erros': 1, 'tem_erros': True}},
        'documento_correcao': {'resumo': {'total_registros_com_erro': 1}},
    }
    recovery = {'attempted': True, 'patches': []}
    result = apply_targeted_recovery_to_final_result(final, recovery, version='v61.0.35-candidate-profile-consensus-engine')
    assert result['documento_correcao']['resumo']['total_registros_com_erro'] == 0
    assert result['validacao']['resumo']['total_erros'] == 0
    assert result['validacao']['resumo']['tem_erros'] is False
