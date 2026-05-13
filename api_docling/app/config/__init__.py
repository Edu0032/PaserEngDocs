from __future__ import annotations

__all__ = [
    'load_parser_config', 'load_base_config', 'resolve_runtime_config', 'refresh_parser_config_cache', 'merge_base_config_layers', 'validate_user_base_config_overlay',
    'get_settings', 'AppSettings', 'refresh_app_settings_cache',
]


def __getattr__(name: str):
    if name in {'load_parser_config', 'load_base_config', 'resolve_runtime_config', 'refresh_parser_config_cache', 'merge_base_config_layers', 'validate_user_base_config_overlay'}:
        from .loader import load_parser_config, load_base_config, resolve_runtime_config, refresh_parser_config_cache, merge_base_config_layers, validate_user_base_config_overlay
        return {
            'load_parser_config': load_parser_config,
            'load_base_config': load_base_config,
            'resolve_runtime_config': resolve_runtime_config,
            'refresh_parser_config_cache': refresh_parser_config_cache,
            'merge_base_config_layers': merge_base_config_layers,
            'validate_user_base_config_overlay': validate_user_base_config_overlay,
        }[name]
    if name in {'get_settings', 'AppSettings', 'refresh_app_settings_cache'}:
        from .settings import get_settings, AppSettings, refresh_app_settings_cache
        return {
            'get_settings': get_settings,
            'AppSettings': AppSettings,
            'refresh_app_settings_cache': refresh_app_settings_cache,
        }[name]
    raise AttributeError(name)
