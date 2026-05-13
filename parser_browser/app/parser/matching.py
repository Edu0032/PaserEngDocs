"""Regras de vínculo entre orçamento e composições.

Na v20.2 este módulo passa a ser o ponto semântico para heurísticas de matching,
mesmo que a implementação principal ainda viva em ``app.parser.compositions`` por
segurança de comportamento.
"""

from app.parser.compositions import (
    _apply_flexible_ref_resolution,
    _compute_missing_refs,
)

__all__ = ["_apply_flexible_ref_resolution", "_compute_missing_refs"]
