from __future__ import annotations

from app.config.loader import merge_base_config_layers, validate_user_base_config_overlay


def test_admin_user_base_config_deep_merge_preserves_admin_and_adds_user_profile():
    admin = {
        "quality_gate": {"numeric_fidelity": {"enabled": True}},
        "custom_bank_profiles": {"profiles": {"builtin": {"family": "sinapi_like"}}},
    }
    user = {
        "custom_bank_profiles": {
            "profiles": {
                "usuario_tabela_x": {
                    "display_name": "Tabela do usuário",
                    "family": "sinapi_like",
                    "templates": [{"id": "padrao", "columns": [{"header": "COD", "canonical": "codigo"}]}],
                }
            }
        }
    }
    merged = merge_base_config_layers(admin, user)
    assert merged["quality_gate"]["numeric_fidelity"]["enabled"] is True
    assert "builtin" in merged["custom_bank_profiles"]["profiles"]
    assert "usuario_tabela_x" in merged["custom_bank_profiles"]["profiles"]
    assert merged["metadata"]["user_base_config_merged"] is True


def test_user_base_config_overlay_validation_flags_columns_without_canonical():
    user = {"custom_bank_profiles": {"profiles": {"x": {"templates": [{"columns": [{"header": "COD"}]}]}}}}
    report = validate_user_base_config_overlay(user)
    assert report["ok"] is False
    assert report["errors"][0]["message"] == "coluna sem canonical"
