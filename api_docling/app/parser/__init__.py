from __future__ import annotations

# v60.2: keep parser package import lightweight for Pyodide and tests.  Heavy
# modules (budget/compositions/sicro) are imported lazily only when the public
# symbols are requested.

__all__ = [
    'parse_document',
    'parse_budget_document',
    'parse_sinapi',
    'parse_compositions_document',
    'parse_composicoes_sinapi',
    'extract_sicro_blocks',
    'materialize_sicro_block',
]


def __getattr__(name: str):
    if name == 'parse_document':
        from .pipeline import parse_document
        return parse_document
    if name in {'parse_budget_document', 'parse_sinapi'}:
        from .budget import parse_budget_document, parse_sinapi
        return {'parse_budget_document': parse_budget_document, 'parse_sinapi': parse_sinapi}[name]
    if name in {'parse_compositions_document', 'parse_composicoes_sinapi'}:
        from .compositions import parse_compositions_document, parse_composicoes_sinapi
        return {'parse_compositions_document': parse_compositions_document, 'parse_composicoes_sinapi': parse_composicoes_sinapi}[name]
    if name in {'extract_sicro_blocks', 'materialize_sicro_block'}:
        from .sicro import extract_sicro_blocks_from_text as extract_sicro_blocks, materialize_sicro_block
        return {'extract_sicro_blocks': extract_sicro_blocks, 'materialize_sicro_block': materialize_sicro_block}[name]
    raise AttributeError(name)
