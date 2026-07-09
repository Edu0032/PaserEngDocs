import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RUNTIME_KEYS = {"docling_api_url", "docling_api_key", "docling_timeout_ms", "normalizer_url", "normalizer_mode"}


def test_payload_examples_are_semantic_and_do_not_include_runtime():
    for rel in ["examples/payloads/payload_empty_v61_0_37.json", "examples/payloads/payload_filled_v61_0_37.json"]:
        payload = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        assert payload["version"] == "v61.0.39-deep-area-sweep-iterative-closure"
        assert "runtime" not in payload
        assert not (set(payload.keys()) & RUNTIME_KEYS)
        assert set(["document", "ranges", "seed_pages", "tables"]).issubset(payload.keys())


def test_filled_payload_preserves_grouped_and_ignored_columns():
    payload = json.loads((ROOT / "examples/payloads/payload_filled_v61_0_37.json").read_text(encoding="utf-8"))
    budget = payload["tables"]["budget"]
    composition = payload["tables"]["composition"]
    group = budget["header_groups"][0]
    assert group["children"] == ["custo_unitario_sem_bdi", "custo_unitario_com_bdi"]
    assert [h["canonical"] for h in budget["observed_headers"]][6:8] == ["custo_unitario_sem_bdi", "custo_unitario_com_bdi"]
    tipo = [h for h in composition["observed_headers"] if h["canonical"] == "tipo"][0]
    assert tipo["ignore_in_domain"] is True
    assert tipo["include_in_final_json"] is False
    assert [h["canonical"] for h in composition["observed_headers"]][:5] == ["controle_linha", "codigo", "banco", "descricao", "tipo"]
