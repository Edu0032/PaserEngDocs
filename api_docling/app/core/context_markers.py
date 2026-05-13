from __future__ import annotations

import re
import unicodedata
from typing import Any, List

from app.core.document_profile import collect_profile_ignore_phrases


def _deaccent(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def split_dynamic_phrases(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out: List[str] = []
        for item in value:
            out.extend(split_dynamic_phrases(item))
        return out
    s = str(value).strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        try:
            import json
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return split_dynamic_phrases(parsed)
        except Exception:
            pass
    # Formatos preferenciais: lista, texto por linha ou separado por ';'.
    # Não quebrar por vírgula evita destruir endereços/contexto institucional.
    return [part.strip() for part in re.split(r"[\n;]+", s) if part and part.strip()]


def _add_variants(base: str, out: List[str]) -> None:
    s = str(base or "").strip()
    if not s:
        return

    def _push(v: str) -> None:
        v = str(v or "").strip()
        if v and len(v) >= 4:
            out.append(v)

    variants = {
        s,
        s.replace(" ", ""),
        _deaccent(s),
        _deaccent(s).replace(" ", ""),
        re.sub(r"\s+", " ", s.replace("/", " ").replace("-", " ")).strip(),
        re.sub(r"[^\w\s]", " ", _deaccent(s)),
    }

    if ":" in s:
        tail = s.split(":", 1)[1].strip()
        if tail:
            variants.add(tail)
            variants.add(_deaccent(tail))
            variants.add(re.sub(r"\s+", " ", tail.replace("/", " ").replace("-", " ")).strip())

    pieces = [p.strip() for p in re.split(r"[:;\-–]+", s) if p and p.strip()]
    for piece in pieces:
        words = piece.split()
        if len(piece) >= 8 and (len(words) >= 2 or any(ch.isdigit() for ch in piece)):
            variants.add(piece)
            variants.add(_deaccent(piece))
            variants.add(re.sub(r"\s+", " ", piece.replace("/", " ").replace("-", " ")).strip())

    words = s.split()
    for n in (2, 3, 4, 5, 6):
        if len(words) >= n:
            variants.add(" ".join(words[:n]))
            variants.add(" ".join(words[-n:]))

    for value in variants:
        _push(value)


def build_dynamic_markers(context: dict | None) -> List[str]:
    context = context or {}
    out: List[str] = []

    for key in (
        "obra_nome",
        "obra_localizacao",
        "orgao_nome",
        "prefeitura_nome",
        "contratante_nome",
    ):
        _add_variants(context.get(key), out)

    for phrase in split_dynamic_phrases(context.get("dynamic_ignore_phrases")):
        _add_variants(phrase, out)

    for phrase in collect_profile_ignore_phrases(context.get("document_profile") if isinstance(context, dict) else None):
        _add_variants(phrase, out)

    uniq: List[str] = []
    seen = set()
    for marker in out:
        if marker not in seen:
            uniq.append(marker)
            seen.add(marker)

    uniq.sort(key=len, reverse=True)
    return uniq
