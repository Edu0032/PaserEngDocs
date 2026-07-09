import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_config_ui_schema_declares_admin_and_user_scopes():
    data = json.loads((ROOT / "parser_browser/db/base_config.d/90_config_ui_schema.json").read_text(encoding="utf-8"))
    ui = data["config_ui"]
    assert ui["version"] == "v61.0.75-correction-output-contract-and-review-index"
    assert ui["admin_interface"]["scope"] == "global_base_config"
    assert ui["user_interface"]["scope"] == "user_base_config_overlay"
    assert "custom_table_builder" in ui["user_interface"]
    assert ui["user_interface"]["custom_table_builder"]["parser_consumption"] == "deep_merge_admin_then_user_before_parse"


def test_user_base_config_contract_limits_normal_user_scope():
    data = json.loads((ROOT / "parser_browser/db/base_config.d/85_user_base_config_contract.json").read_text(encoding="utf-8"))
    contract = data["user_base_config_contract"]
    assert contract["normal_user_edit_scope"] == "user_base_config_overlay_only"
    assert "quality_gate" in contract["admin_only_sections"]
    assert "custom_bank_profiles.profiles" in contract["user_editable_sections"]
    assert "optional_column_fields" in contract["custom_table_builder"]
