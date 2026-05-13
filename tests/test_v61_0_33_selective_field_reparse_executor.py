from app.parser.selective_field_reparse_executor import run_selective_field_reparse_executor
from app.parser.broken_line_recovery import pollution_reason


def _base_result():
    return {
        "orcamento_sintetico": {
            "itens_raiz": [
                {"tipo": "item", "item": "1.1", "codigo": "90777", "fonte": "SINAPI", "especificacao": "ENGENHEIRO CIVIL DE OBRA JUNIOR COM"},
                {"tipo": "item", "item": "3.2.7", "codigo": "ANP 01", "fonte": "PRÓPRIO", "especificacao": "AQUISIÇÃO DE ASFALTO DILUIDO CM-30"},
            ]
        },
        "composicoes": {
            "sinapi_like": {
                "principais": {
                    "90777|SINAPI": {"principal": {"codigo": "90777", "banco": "SINAPI", "descricao": "ENGENHEIRO CIVIL DE OBRA JUNIOR COM ENCARGOS COMPLEMENTARES"}},
                    "ANP01|PRÓPRIO": {"principal": {"codigo": "ANP 01", "banco": "PRÓPRIO", "descricao": "AQUISIÇÃO DE ASFALTO DILUIDO CM-30"}},
                },
                "auxiliares_globais": {},
            }
        },
    }


def test_selective_field_reparse_applies_safe_cross_table_candidate():
    patched, report = run_selective_field_reparse_executor(_base_result(), apply=True)
    item = patched["orcamento_sintetico"]["itens_raiz"][0]
    assert item["especificacao"] == "ENGENHEIRO CIVIL DE OBRA JUNIOR COM ENCARGOS COMPLEMENTARES"
    assert report["summary"]["applied"] >= 1
    assert any(p["codigo"] == "90777" and p["decision"] == "accepted" for p in report["applied"])


def test_selective_field_reparse_does_not_patch_already_good_budget_item():
    patched, report = run_selective_field_reparse_executor(_base_result(), apply=True)
    item = patched["orcamento_sintetico"]["itens_raiz"][1]
    assert item["especificacao"] == "AQUISIÇÃO DE ASFALTO DILUIDO CM-30"
    assert not any(p["codigo"] == "ANP 01" for p in report["applied"])


def test_selective_field_reparse_quarantines_polluted_candidate():
    result = {
        "orcamento_sintetico": {"itens_raiz": [{"tipo": "item", "codigo": "88316", "fonte": "SINAPI", "especificacao": "SERVENTE COM"}]},
        "composicoes": {"sinapi_like": {"principais": {"88316|SINAPI": {"principal": {"codigo": "88316", "banco": "SINAPI", "descricao": "SERVENTE COM ENCARGOS COMPLEMENTARES Revestimentos Cerâmicos Internos"}}}}},
    }
    assert pollution_reason("SERVENTE COM ENCARGOS COMPLEMENTARES Revestimentos Cerâmicos Internos")
    patched, report = run_selective_field_reparse_executor(result, apply=True)
    assert patched["orcamento_sintetico"]["itens_raiz"][0]["especificacao"] == "SERVENTE COM"
    assert report["summary"]["applied"] == 0
    assert report["summary"]["targets"] >= 1


def test_selective_field_reparse_generates_surgical_target_when_no_safe_candidate():
    result = {
        "orcamento_sintetico": {"itens_raiz": [{"tipo": "item", "item": "9.1", "codigo": "99999", "fonte": "SINAPI", "especificacao": "EXECUÇÃO DE"}]},
        "composicoes": {"sinapi_like": {"principais": {}, "auxiliares_globais": {}}},
    }
    _, report = run_selective_field_reparse_executor(result, apply=True)
    assert report["summary"]["applied"] == 0
    assert report["summary"]["targets"] == 1
    target = report["targets"][0]
    assert target["family"] == "budget"
    assert target["field"] == "especificacao"
    assert target["codigo"] == "99999"


def test_worker_collects_selective_field_executor_targets():
    worker = open("parser_browser/browser/pyodide/pyodide-parser-worker.js", encoding="utf-8").read()
    assert "function addTargetsFromSelectiveFieldExecutor" in worker
    assert "selective_field_reparse_executor" in worker
    assert "addTargetsFromSelectiveFieldExecutor(targets, finalResult)" in worker
