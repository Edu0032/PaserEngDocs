from __future__ import annotations
import io
import re
from typing import Any, Dict, List, Tuple, Optional
from app.core.pdf_session import PdfDocumentSession
from app.core.performance import PerformanceTracker
from app.core.pdf_text import extract_pages_text, normalize_lines
from app.core.money import parse_ptbr_number
from app.core.sanitizer import (
    break_glued_markers,
    sanitize_lines,
    is_safe_continuation,
    clean_inline,
    contains_any,
    normalize_service_text,
)
from app.core.schemas import ParseResponse, OrcamentoSintetico, Composicoes, Validacao, ResumoValidacao
from app.core.context_markers import build_dynamic_markers
from app.core.base_rules import bank_regex_fragment, canonical_bank, header_cfg, line_has_header_markers, norm_text
from app.parser.compositions import parse_compositions_document as parse_composicoes_sinapi, sanitize_composicoes_for_output
_NUM = r"\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?"
# =====================
# ORÇAMENTO (SINTÉTICO)
# =====================
_RE_ITEM_START = re.compile(
    rf"^(?P<item>\d+(?:\.\d+)*)\s+(?P<codigo>.+?)\s+(?P<fonte>SINAPI|Próprio|SICRO3|SICRO|ORSE|SEINFRA)\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_RE_ITEM_COMPOSICAO_START = re.compile(
    rf"^(?P<item>\d+(?:\.\d+)*)\s+COMPOSI(?:ÇÃO|CAO)(?:\s+(?P<codigo>.+?))?\s+(?P<fonte>SINAPI|Próprio|SICRO3|SICRO|ORSE|SEINFRA)\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_RE_ITEM_COMPOSICAO_HEAD = re.compile(r"^(?P<item>\d+(?:\.\d+)*)\s+COMPOSI(?:ÇÃO|CAO)\s*$", re.IGNORECASE)
_RE_ITEM_TAIL = re.compile(
    rf"\s(?P<und>[A-Za-z0-9/%²³]+)\s+(?P<quant>{_NUM})\s+(?P<s_bdi>{_NUM})\s+(?P<c_bdi>{_NUM})\s+(?P<parcial>{_NUM})\s*$"
)
_RE_TRAILING_NUMERIC_BLOCK = re.compile(
    rf"^(?P<prefix>.*?)(?P<quant>{_NUM})\s+(?P<s_bdi>{_NUM})\s+(?P<c_bdi>{_NUM})\s+(?P<parcial>{_NUM})\s*$"
)
_RE_GROUP_WITH_TOTAL = re.compile(rf"^(?P<item>\d+(?:\.\d+)*)\s+(?P<desc>.+?)\s+(?P<total>{_NUM})\s*$")
_RE_GROUP_NO_TOTAL = re.compile(r"^(?P<item>\d+(?:\.\d+)*)\s+(?P<desc>.+?)\s*$")
_RE_ONLY_NUMBER = re.compile(rf"^(?P<num>{_NUM})$")
_GROUP_BLACKLIST = ("SINAPI", "PRÓPRIO", "PROPRIO", "COMPOSIÇÃO", "COMPOSICAO", "UND", "QUANT", "CUSTO", "BDI", "%", "SICRO")
_VALID_UNIT_TOKENS = {
    "M", "M2", "M3", "M²", "M³", "KG", "G", "UN", "UND", "UNID", "UNID.", "MES", "M/MES",
    "M3XKM", "M2XKM", "%", "T", "H", "HA", "L", "CJ", "VB", "KM", "CM", "MM", "ML",
    "PÇ", "PCA", "PC", "PÇS", "PAR", "PARES",
}
_INVALID_UNIT_TOKENS = {
    "DE", "DA", "DO", "DAS", "DOS", "EM", "NA", "NO", "NAS", "NOS", "COM", "SEM", "PARA",
    "E", "OU", "X", "BASE", "POSTE", "MADEIRA",
}


_DEFAULT_ORC_HEADER_ALIASES = {
    "item": ["ITEM"],
    "codigo": ["CÓDIGO", "CODIGO", "CÓD.", "COD.", "COD"],
    "fonte": ["FONTE", "BANCO"],
    "especificacao": ["ESPECIFICAÇÕES DOS SERVIÇOS", "ESPECIFICAÇÕES", "ESPECIFICACOES", "DESCRIÇÃO", "DESCRICAO", "DESC.", "DESCR.", "ESPEC."],
    "und": ["UND", "UNID", "UNIDADE", "UM", "U.M.", "UN"],
    "quant": ["QUANT", "QUANT.", "QTD", "QTD.", "QUANTIDADE"],
    "custo_parcial": ["CUSTO PARCIAL", "PARCIAL", "TOTAL PARCIAL"],
}


def _orc_header_cfg(config: dict) -> dict:
    return header_cfg(
        config,
        key="table_headers",
        default_aliases=_DEFAULT_ORC_HEADER_ALIASES,
        default_required=["item", "codigo", "fonte"],
        default_similarity=0.82,
    )


def _build_orcamento_regexes(config: dict) -> dict:
    bank_pat = bank_regex_fragment(config)
    comp_aliases = ((config.get("normalization") or {}).get("composition_labels") or {}).get("composicao") or ["COMPOSIÇÃO", "COMPOSICAO"]
    comp_pat = "(?:" + "|".join(sorted({re.escape(v) for v in comp_aliases if str(v).strip()}, key=len, reverse=True)) + ")"
    return {
        "item_start": re.compile(
            rf"^(?P<item>\d+(?:\.\d+)*)\s+(?P<codigo>.+?)\s+(?P<fonte>{bank_pat})\s*(?P<rest>.*)$",
            re.IGNORECASE,
        ),
        "item_composicao_start": re.compile(
            rf"^(?P<item>\d+(?:\.\d+)*)\s+{comp_pat}(?:\s+(?P<codigo>.+?))?\s+(?P<fonte>{bank_pat})\s*(?P<rest>.*)$",
            re.IGNORECASE,
        ),
        "item_composicao_head": re.compile(
            rf"^(?P<item>\d+(?:\.\d+)*)\s+{comp_pat}\s*$",
            re.IGNORECASE,
        ),
    }


def _looks_like_orcamento_header_line(line: str, config: dict) -> bool:
    cfg = _orc_header_cfg(config)
    return line_has_header_markers(line, cfg, required_keys=["item", "codigo"])


_ORCAMENTO_INLINE_NOISE_PATTERNS = [
    r"\bDEPARTAMENTO\s+DE\s+ESTRADAS\s+DE\s+RODAGEM\b",
    r"\bP[ÁA]GINA\s+\d+\s+DE\s+\d+\b",
    r"\bOBJETO:\b",
    r"\bMUNIC[ÍI]PIO:\b",
    r"\bENDERE[ÇC]O:\b",
    r"\bDATA-BASE\b",
    r"\bENC\.?\s+SOCIAIS\b",
    r"\bDATA\s*:\s*\d{2}/\d{2}/\d{4}\b",
    r"\b\d{2}/\d{2}/\d{4}\b",
    r"\bO\s+VALOR\s+DO\s+PRESENTE\s+OR[ÇC]AMENTO\b",
    r"\bASSINATURA\b",
    r"\bPARCIAL\s+CUSTO\s+TOTAL\b",
    r"\bTOTAL\s+COM\s+BDI\b",
    r"\bTOTAL\s+GERAL\b",
    r"\b(?:RUA|AVENIDA|AV\.?|RODOVIA|ESTRADA|TRAVESSA|ALAMEDA|R\.)\s+[^,]{1,80},\s*\d{1,5}\b",
    r"\bRESPONS[ÁA]VEL\s+T[ÉE]CNICO\b",
    r"\bCREA\b",
    r"#NOME\?",
]

_CONTEXT_TAIL_KEYWORDS = {
    "ALAMEDA", "ASSINATURA", "AV", "AVENIDA", "BAIRRO", "BRASIL", "CENTRO",
    "CONTRATANTE", "CREA", "DATA", "DATA-BASE", "DEPARTAMENTO", "ENDERECO", "ENDEREÇO",
"ESTADO", "GOVERNO", "LOCALIZACAO", "LOCALIZAÇÃO",
    "MUNICIPIO", "MUNICÍPIO", "OBJETO", "PARÂMETROS", "PARAMETROS", "PREFEITURA", "R", "RODOVIA",
    "RUA", "SECRETARIA", "TRAVESSA", "CONVENIO", "CONVÊNIO", "BDI",
}

_DYNAMIC_MARKER_STOPWORDS = {
    "A", "AC", "BR", "COM", "DA", "DAS", "DE", "DO", "DOS", "E", "EM", "NA", "NO", "PARA",
}



def _normalized_alnum_with_map(text: str) -> tuple[str, list[int]]:
    import unicodedata
    chars: list[str] = []
    idx_map: list[int] = []
    for idx, ch in enumerate(str(text or "")):
        norm = unicodedata.normalize("NFD", ch)
        for piece in norm:
            if unicodedata.category(piece) == "Mn":
                continue
            up = piece.upper()
            if up.isalnum():
                chars.append(up)
                idx_map.append(idx)
    return "".join(chars), idx_map


def _cut_by_dynamic_markers(text: str, dynamic_markers: List[str]) -> str:
    s = str(text or "").strip()
    if not s or not dynamic_markers:
        return s
    norm_s, idx_map = _normalized_alnum_with_map(s)
    best_idx: int | None = None
    for marker in dynamic_markers:
        mk = str(marker or "").strip()
        if len(mk) < 6:
            continue
        norm_mk, _ = _normalized_alnum_with_map(mk)
        if len(norm_mk) < 6:
            continue
        pos = norm_s.find(norm_mk)
        if pos == -1:
            continue
        orig_idx = idx_map[pos] if pos < len(idx_map) else 0
        if orig_idx == 0 and len(norm_mk) >= max(12, int(len(norm_s) * 0.6)):
            return ""
        if orig_idx >= 6:
            best_idx = orig_idx if best_idx is None else min(best_idx, orig_idx)
    if best_idx is not None:
        s = s[:best_idx].rstrip(" -,:;")
    return s


def _dynamic_marker_tokens(dynamic_markers: List[str]) -> set[str]:
    tokens: set[str] = set()
    for marker in dynamic_markers or []:
        for token in re.findall(r"[A-ZÀ-Ú0-9]{4,}", str(marker or "").upper()):
            if token in _DYNAMIC_MARKER_STOPWORDS:
                continue
            tokens.add(norm_text(token))
    return tokens


def _looks_like_contextual_tail(text: str, dynamic_markers: List[str]) -> bool:
    raw = re.sub(r"\s+", " ", str(text or "").replace("\xa0", " ")).strip(" -,:;.")
    if not raw:
        return False
    raw_up = raw.upper()
    raw_norm = norm_text(raw)

    if _cut_by_dynamic_markers(raw, dynamic_markers or []) != raw:
        return True
    if any(keyword in raw_up for keyword in _CONTEXT_TAIL_KEYWORDS):
        return True
    if re.search(r"\b(?:RUA|AVENIDA|AV\.?|RODOVIA|ESTRADA|TRAVESSA|ALAMEDA|R\.)\b", raw, flags=re.IGNORECASE):
        return True
    if re.search(r"\b\d{2}/\d{2}/\d{4}\b", raw_up):
        return True

    marker_tokens = _dynamic_marker_tokens(dynamic_markers or [])
    if marker_tokens:
        raw_tokens = set(re.findall(r"[A-Z0-9]{4,}", raw_norm))
        if raw_tokens & marker_tokens:
            return True
        if any(tok in raw_norm for tok in marker_tokens if len(tok) >= 6):
            return True
    return False


def _trim_contextual_tail_after_reference(text: str, dynamic_markers: List[str]) -> str:
    s = re.sub(r"\s+", " ", str(text or "").strip())
    if not s:
        return s

    ref_matches = list(re.finditer(r"\bAF_\d{2}/\d{4}(?:_[A-Z0-9]+)?\b", s, flags=re.IGNORECASE))
    for match in ref_matches:
        tail = s[match.end():].strip()
        if tail and _looks_like_contextual_tail(tail, dynamic_markers or []):
            return s[:match.end()].rstrip(" -,:;")

    if dynamic_markers:
        for punct in (". ", ") "):
            idx = s.rfind(punct)
            if idx == -1:
                continue
            tail_start = idx + len(punct)
            tail = s[tail_start:].strip()
            if tail and _looks_like_contextual_tail(tail, dynamic_markers or []):
                return s[:tail_start].rstrip(" -,:;")
    return s

def _extract_comp_placeholder_code(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    parts = re.findall(r"[0-9A-Z_]+", raw.upper())
    if not parts:
        return ""
    joined = "".join(parts)
    if any(ch.isdigit() for ch in joined):
        return joined
    return ""



def _sanitize_orcamento_especificacao(text: str, strip_inline_from: List[str], dynamic_markers: List[str]) -> str:
    s = clean_inline(text, strip_inline_from, dynamic_markers=dynamic_markers)
    if not s:
        return s
    s = _trim_contextual_tail_after_reference(s, dynamic_markers or [])
    cut_idx = None
    for pat in _ORCAMENTO_INLINE_NOISE_PATTERNS:
        m = re.search(pat, s, flags=re.IGNORECASE)
        if m:
            cut_idx = m.start() if cut_idx is None else min(cut_idx, m.start())
    if cut_idx is not None:
        s = s[:cut_idx].rstrip(" -,:;")
    # remoção defensiva de ruído institucional/endereço residual
    s = re.sub(r"\bPARCIAL\s+CUSTO\s+TOTAL\b.*$", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\b(?:TOTAL\s+COM\s+BDI|TOTAL\s+GERAL)\b.*$", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\b(?:RUA|AVENIDA|AV\.?|RODOVIA|ESTRADA|TRAVESSA|ALAMEDA|R\.)\s+[^,]{1,120},\s*\d{1,5}.*$", "", s, flags=re.IGNORECASE).strip()
    s = _cut_by_dynamic_markers(s, dynamic_markers or [])
    return normalize_service_text(re.sub(r"\s+", " ", s).strip())

def _is_probably_insumo_codigo(codigo: str) -> bool:
    """
    Heurística prática SINAPI:
    - Insumos costumam ser numéricos com zeros à esquerda (ex.: 00000370, 00005069)
    - Composições "principais" normalmente não começam com 0000
    """
    s = (codigo or "").strip()
    return s.isdigit() and len(s) >= 6 and s.startswith("0000")
def _orcamento_tem_total_final(texto: str) -> bool:
    up = (texto or "").upper()
    return "TOTAL COM BDI" in up or "TOTAL GERAL" in up
def _expand_orcamento_pages_if_needed(pdf_bytes: bytes, start_1based: int, end_1based: int, pages_text: List[str], *, pdf_session: PdfDocumentSession | None = None, text_engine: str = "pypdf") -> tuple[List[str], int, bool]:
    if not pages_text or _orcamento_tem_total_final("\n".join(pages_text)):
        return pages_text, end_1based, False
    session = pdf_session or PdfDocumentSession(pdf_bytes)
    current_end = end_1based
    expanded = False
    # margem curta: tenta capturar a continuação imediata do anexo sintético quando o usuário erra o fim por 1-2 páginas
    while current_end < session.page_count and current_end < end_1based + 2:
        next_text = session.get_page_text(current_end + 1, engine=text_engine) or ""
        next_up = next_text.upper()
        if "ANEXO 2" in next_up or "MEMÓRIA DE CÁLCULO" in next_up:
            break
        pages_text.append(next_text)
        current_end += 1
        expanded = True
        if _orcamento_tem_total_final(next_text):
            break
    return pages_text, current_end, expanded
def _canon_fonte(value: str, config: dict | None = None) -> str:
    return canonical_bank(value, config=config)


def _normalize_ref_key(codigo: str, fonte: str) -> str:
    codigo = re.sub(r"\s+", " ", str(codigo or "").replace("\u00a0", " ").strip())
    fonte = _canon_fonte(fonte)
    return f"{codigo}|{fonte}" if codigo and fonte else ""


def _is_valid_unit_token(token: str) -> bool:
    tok = str(token or "").strip().rstrip(".,;:").upper()
    if not tok or tok in _INVALID_UNIT_TOKENS:
        return False
    return tok in _VALID_UNIT_TOKENS


def _extract_desc_and_unit_fragment(
    text: str,
    *,
    allow_trailing_unit: bool,
    allow_whole_unit: bool,
) -> tuple[str, str]:
    s = re.sub(r"\s+", " ", str(text or "").replace("\xa0", " ")).strip()
    if not s:
        return "", ""
    if allow_whole_unit and _is_valid_unit_token(s):
        return "", s.rstrip(".,;:")
    if allow_trailing_unit:
        parts = s.split()
        if parts and _is_valid_unit_token(parts[-1]):
            if len(parts) == 2 and re.fullmatch(r"(?:%s)" % _NUM, parts[0]):
                return s, ""
            return " ".join(parts[:-1]).strip(), parts[-1].rstrip(".,;:")
    return s, ""


def _item_header_match(line: str, orc_regexes: dict) -> re.Match | None:
    return orc_regexes["item_start"].match(line) or orc_regexes["item_composicao_start"].match(line)


def _looks_like_code_only_fragment(line: str, config: dict | None = None) -> bool:
    raw = re.sub(r"\s+", " ", str(line or "")).strip()
    if not raw or " " in raw:
        return False
    if _line_has_numeric_tail(raw):
        return False
    if _looks_like_budget_noise_line(raw):
        return False
    if re.match(r"^\d+(?:\.\d+)*$", raw):
        return False
    bank_pat = bank_regex_fragment(config)
    if re.fullmatch(bank_pat, raw, flags=re.IGNORECASE):
        return False
    token = _extract_comp_placeholder_code(raw)
    if not token:
        return False
    if len(token) > 20:
        return False
    return bool(re.fullmatch(r"[0-9A-Z_.-]+", token))


def _extract_multiline_composicao_head(
    lines: List[str],
    start_idx: int,
    *,
    orc_regexes: dict,
    config: dict,
) -> tuple[Optional[str], int]:
    raw = lines[start_idx]
    m = orc_regexes["item_composicao_head"].match(raw)
    if not m:
        return None, start_idx
    item = m.group("item").strip()
    j = start_idx + 1
    code = ""
    if j < len(lines) and _looks_like_code_only_fragment(lines[j], config=config):
        code = _extract_comp_placeholder_code(lines[j])
        j += 1

    bank_pat = bank_regex_fragment(config)
    fonte_line_re = re.compile(rf"^(?P<fonte>{bank_pat})\s*(?P<rest>.*)$", re.IGNORECASE)
    fonte = ""
    rest = ""
    if j < len(lines):
        m2 = fonte_line_re.match(lines[j])
        if m2:
            fonte = _canon_fonte((m2.group("fonte") or "").strip(), config=config)
            rest = (m2.group("rest") or "").strip()
            j += 1

    if not fonte:
        return None, start_idx

    parts = [item, "COMPOSIÇÃO"]
    if code:
        parts.append(code)
    parts.append(fonte)
    if rest:
        parts.append(rest)
    return " ".join(part for part in parts if part).strip(), j


def _line_has_numeric_tail(line: str) -> bool:
    return bool(_RE_TRAILING_NUMERIC_BLOCK.match(str(line or "").strip()))


def _looks_like_short_safe_item_fragment(line: str) -> bool:
    raw = re.sub(r"\s+", " ", str(line or "")).strip()
    if not raw:
        return False
    up = raw.upper()
    if re.fullmatch(r"AF_\d{2}/\d{4}(?:_[A-Z0-9]+)?", up):
        return True
    if _is_valid_unit_token(raw):
        return True
    if re.fullmatch(r"\d+\s+[A-ZÇÃÕÂÊÔÁÉÍÓÚ/]{1,6}", up):
        return True
    if len(raw) <= 18 and not _looks_like_new_row(raw):
        return True
    return False


def _looks_like_budget_noise_line(line: str, dynamic_markers: List[str] | None = None) -> bool:
    raw = re.sub(r"\s+", " ", str(line or "").replace(" ", " ")).strip()
    if not raw:
        return True
    up = raw.upper()
    if up.startswith("ESTADO ") and not re.match(r"^\d+(?:\.\d+)*\b", raw):
        return True
    if up.startswith("DEPARTAMENTO ") and not _line_has_numeric_tail(raw):
        return True
    if re.search(r"\bP[ÁA]GINA\s+\d+\s+DE\s+\d+\b", up):
        return True
    if re.fullmatch(r"_+", up):
        return True
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", up):
        return True
    if re.search(r"\b(?:RUA|AVENIDA|AV\.?|RODOVIA|ESTRADA|TRAVESSA|ALAMEDA|R\.)\s+[^,]{1,80},\s*\d{1,5}\b", raw, flags=re.IGNORECASE):
        return True
    if "PARCIAL CUSTO TOTAL" in up:
        return True
    if "TOTAL COM BDI" in up or "TOTAL GERAL" in up:
        return True
    if dynamic_markers:
        raw_up = raw.upper()
        raw_ascii = norm_text(raw)
        for marker in dynamic_markers:
            mk = str(marker or "").strip()
            if not mk or len(mk) < 8:
                continue
            if mk.upper() in raw_up or norm_text(mk) in raw_ascii:
                if not _line_has_numeric_tail(raw) and not re.match(r"^\d+(?:\.\d+)*\b", raw):
                    return True
    return False


def _extract_budget_total(pages_text: List[str]) -> Optional[float]:
    for page_text in reversed(pages_text or []):
        for line in reversed((page_text or '').splitlines()):
            line = re.sub(r"\s+", " ", line or '').strip()
            m = re.search(r"(?:TOTAL\s+COM\s+BDI|TOTAL\s+GERAL(?:\s*\(R\$\))?\s*>>?)\s*[:>]*\s*(%s)" % _NUM, line, flags=re.IGNORECASE)
            if m:
                return parse_ptbr_number(m.group(1))
    return None


def _looks_like_incomplete_spec_text(text: str) -> bool:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return False
    up = s.upper()
    if s.endswith((",", "-", "/", "(")):
        return True
    if up.count("(") > up.count(")"):
        return True
    if re.search(r"\b(?:COM|DE|DA|DO|DAS|DOS|E|EM|PARA|SEM|SOB|ENTRE|INCLUINDO|INCLUSO|ATE|ATÉ|TIPO|TRACO|TRAÇO)$", up):
        return True
    if re.search(r"(?:PREPARO MEC[ÂA]NICO COM|ARGAMASSA DE|P[ÉE]-DIREITO SIMPLES|N[ÃA]O|AF_\d{2}/\d{4})$", up):
        return True
    return False


def _looks_like_contextual_continuation(line: str, dynamic_markers: List[str] | None = None) -> bool:
    raw = re.sub(r"\s+", " ", str(line or "").replace(" ", " ")).strip()
    if not raw:
        return False
    if _line_has_numeric_tail(raw):
        return False
    if _looks_like_budget_noise_line(raw, dynamic_markers=dynamic_markers):
        return False
    if re.match(r"^\d+(?:\.\d+)*\b", raw):
        return False
    if re.fullmatch(r"AF_\d{2}/\d{4}(?:_[A-Z0-9]+)?", raw.upper()):
        return True
    if len(raw) <= 96:
        return True
    if len(raw) <= 180 and any(ch.isalpha() for ch in raw):
        return True
    if re.search(r"\b(?:PARA|EM|COM|DE|DA|DO|DAS|DOS|E|SEM|INCLUSO|INCLUINDO|TIPO|AF_\d{2}/\d{4})\b", raw.upper()):
        return True
    return False


def _collect_item_suffix_lines(
    lines: List[str],
    start_idx: int,
    *,
    has_numbers: bool,
    orc_regexes: dict,
    leading_context: str = "",
    dynamic_markers: List[str] | None = None,
) -> tuple[List[str], int]:
    suffix: List[str] = []
    j = start_idx
    context_text = re.sub(r"\s+", " ", leading_context or "").strip()
    while j < len(lines):
        cur = lines[j]
        mg = _RE_GROUP_WITH_TOTAL.match(cur)
        mg2 = _RE_GROUP_NO_TOTAL.match(cur)
        if _item_header_match(cur, orc_regexes) or orc_regexes["item_composicao_head"].match(cur) or (mg and _is_probable_group_heading(mg.group("desc"))) or (mg2 and _is_probable_group_heading(mg2.group("desc"))):
            break
        if _line_has_numeric_tail(cur):
            if has_numbers:
                break
            has_numbers = True
            suffix.append(cur)
            context_text = f"{context_text} {cur}".strip()
            j += 1
            continue
        if has_numbers and not _looks_like_short_safe_item_fragment(cur):
            if _looks_like_incomplete_spec_text(context_text) and _looks_like_contextual_continuation(cur, dynamic_markers=dynamic_markers):
                suffix.append(cur)
                context_text = f"{context_text} {cur}".strip()
                j += 1
                continue
            break
        suffix.append(cur)
        context_text = f"{context_text} {cur}".strip()
        j += 1
    return suffix, j


def _parse_item_block(
    *,
    header_line: str,
    prefix_lines: List[str],
    suffix_lines: List[str],
    strip_inline_from: List[str],
    dynamic_markers: List[str],
    item_start_re: re.Pattern,
    config: dict | None = None,
) -> Optional[dict]:
    m = item_start_re.match(header_line)
    if not m:
        return None
    item = m.group("item").strip()
    codigo = re.sub(r"\s+", " ", (m.group("codigo") or "").strip())
    fonte = _canon_fonte((m.group("fonte") or "").strip(), config=config)
    rest = (m.group("rest") or "").strip()

    ordered_parts: List[tuple[str, str]] = [("prefix", ln) for ln in prefix_lines]
    ordered_parts.append(("header", rest))
    ordered_parts.extend(("suffix", ln) for ln in suffix_lines)

    numeric_candidates: List[tuple[int, int, int, re.Match[str]]] = []
    header_index = len(prefix_lines)
    for idx, (kind, text) in enumerate(ordered_parts):
        mt = _RE_TRAILING_NUMERIC_BLOCK.match((text or "").strip())
        if not mt:
            continue
        priority = 0 if kind == "header" else 1
        numeric_candidates.append((priority, abs(idx - header_index), idx, mt))
    if not numeric_candidates:
        return None
    numeric_candidates.sort()
    _, _, chosen_idx, chosen_tail = numeric_candidates[0]

    unit = ""
    desc_parts: List[str] = []
    quant = chosen_tail.group("quant").strip()
    s_bdi = chosen_tail.group("s_bdi").strip()
    c_bdi = chosen_tail.group("c_bdi").strip()
    parcial = chosen_tail.group("parcial").strip()

    for idx, (kind, text) in enumerate(ordered_parts):
        raw = (text or "").strip()
        if not raw:
            continue
        mt = _RE_TRAILING_NUMERIC_BLOCK.match(raw)
        if mt:
            prefix = mt.group("prefix").strip()
            desc, maybe_unit = _extract_desc_and_unit_fragment(
                prefix,
                allow_trailing_unit=True,
                allow_whole_unit=True,
            )
            if idx == chosen_idx:
                if desc:
                    desc_parts.append(desc)
                if maybe_unit and not unit:
                    unit = maybe_unit
            continue
        desc, maybe_unit = _extract_desc_and_unit_fragment(
            raw,
            allow_trailing_unit=(kind != "prefix"),
            allow_whole_unit=True,
        )
        if desc:
            desc_parts.append(desc)
        if maybe_unit and not unit:
            unit = maybe_unit

    especificacao = _sanitize_orcamento_especificacao(
        " ".join(part for part in desc_parts if part).strip(),
        strip_inline_from=strip_inline_from,
        dynamic_markers=dynamic_markers,
    )
    return {
        "tipo": "item",
        "item": item,
        "codigo": codigo,
        "fonte": fonte,
        "especificacao": especificacao,
        "und": unit,
        "quant": quant,
        "custo_unitario_sem_bdi": s_bdi,
        "custo_unitario_com_bdi": c_bdi,
        "custo_parcial": parcial,
        "reconstruido_multilinha": bool(prefix_lines or suffix_lines),
        "fragmentos_pre": list(prefix_lines),
        "fragmentos_pos": list(suffix_lines),
    }


def _build_validation_resumo(avisos: List[str], erros: List[str], ocorrencias: List[dict] | None = None) -> ResumoValidacao:
    ocorrencias = ocorrencias or []
    por_categoria = {}
    por_codigo = {}
    total_infos = 0
    total_avisos = 0
    total_erros = 0

    if ocorrencias:
        total_ocorrencias = len(ocorrencias)
        for oc in ocorrencias:
            categoria = str(oc.get("categoria", "") or "").strip()
            codigo = str(oc.get("codigo", "") or "").strip()
            severidade = str(oc.get("severidade", "") or "").strip().lower()
            if categoria:
                por_categoria[categoria] = por_categoria.get(categoria, 0) + 1
            if codigo:
                por_codigo[codigo] = por_codigo.get(codigo, 0) + 1
            if severidade == "erro":
                total_erros += 1
            elif severidade == "aviso":
                total_avisos += 1
            else:
                total_infos += 1
    else:
        total_ocorrencias = len(avisos) + len(erros)
        total_erros = len(erros)
        total_avisos = len(avisos)

    return ResumoValidacao(
        total_ocorrencias=total_ocorrencias,
        total_erros=total_erros,
        total_avisos=total_avisos,
        total_infos=total_infos,
        por_categoria=por_categoria,
        por_codigo=por_codigo,
        tem_erros=bool(total_erros),
    )




def _occ_key(oc: dict) -> tuple:
    return (
        str(oc.get("codigo", "") or ""),
        str(oc.get("categoria", "") or ""),
        str(oc.get("item", "") or ""),
        str(oc.get("ref_id", "") or ""),
        str(oc.get("mensagem", "") or ""),
    )


def _make_occurrence(
    codigo: str,
    severidade: str,
    categoria: str,
    mensagem: str,
    **meta: Any,
) -> dict:
    oc = {
        "codigo": codigo,
        "severidade": severidade,
        "categoria": categoria,
        "mensagem": mensagem,
    }
    oc.update({k: v for k, v in meta.items() if v not in (None, "", [], {})})
    return oc


def _append_occurrence(ocorrencias: List[dict], ocorrencia: dict) -> None:
    key = _occ_key(ocorrencia)
    if not any(_occ_key(x) == key for x in ocorrencias):
        ocorrencias.append(ocorrencia)


def _push_message(
    avisos: List[str],
    erros: List[str],
    ocorrencias: List[dict],
    *,
    codigo: str,
    severidade: str,
    categoria: str,
    mensagem: str,
    **meta: Any,
) -> None:
    if severidade == "erro":
        if mensagem not in erros:
            erros.append(mensagem)
    elif severidade == "aviso":
        if mensagem not in avisos:
            avisos.append(mensagem)
    _append_occurrence(
        ocorrencias,
        _make_occurrence(codigo=codigo, severidade=severidade, categoria=categoria, mensagem=mensagem, **meta),
    )




def _ingest_external_messages(
    avisos: List[str],
    erros: List[str],
    ocorrencias: List[dict],
    *,
    mensagens: List[str],
    severidade: str,
    categoria: str,
    etapa: str,
) -> None:
    for mensagem in mensagens or []:
        _push_message(
            avisos, erros, ocorrencias,
            codigo=f"{categoria}_mensagem_externa",
            severidade=severidade,
            categoria=categoria,
            mensagem=str(mensagem),
            etapa=etapa,
        )


_COMPOSITION_DEBUG_PREFIXES = (
    "[composicoes] preclassificacao_paginas:",
    "[composicoes] fallback_texto=",
)


def _split_composition_debug_messages(mensagens: List[str]) -> tuple[List[str], List[str]]:
    debug_msgs: List[str] = []
    user_msgs: List[str] = []
    for mensagem in mensagens or []:
        msg = str(mensagem or "")
        if msg.startswith(_COMPOSITION_DEBUG_PREFIXES):
            debug_msgs.append(msg)
        else:
            user_msgs.append(msg)
    return debug_msgs, user_msgs


def _msg_invalid_budget_range() -> str:
    return (
        "Orçamento sintético não processado: o intervalo de páginas informado é inválido. "
        "Envie composicoes_inicio/fim e orcamento_inicio/fim como páginas 1-based válidas."
    )


def _msg_budget_interval_expanded(page_end: int) -> str:
    return (
        f"Intervalo do orçamento expandido automaticamente até a página {page_end} para capturar o fim do anexo sintético."
    )


def _msg_item_without_analytic(item: str, ref_id: str) -> str:
    return (
        f"Item do orçamento sem tabela analítica clássica confirmada. O item {item} ({ref_id}) foi encontrado no orçamento sintético, "
        "mas pode representar lançamento direto, material/insumo ou uma composição com identificação divergente no próprio PDF."
    )


def _msg_direct_item_without_analytic(item: str, ref_id: str) -> str:
    return (
        f"Item do orçamento tratado como lançamento direto ou insumo. O item {item} ({ref_id}) foi mantido no orçamento sintético, "
        "mas não exige composição analítica clássica no anexo quando o próprio documento o apresenta como material/insumo direto."
    )


def _msg_placeholder_code(item: str, codigo: str) -> str:
    return (
        f"Item com código de composição ausente ou quebrado. O item {item} foi mantido com o código '{codigo}' para preservar a estrutura do orçamento."
    )


def _msg_missing_group_total(item: str) -> str:
    return (
        f"Grupo sem custo total informado no documento. O grupo {item} foi identificado no orçamento, mas o campo custo_total não estava preenchido no PDF."
    )


def _msg_suspicious_group(line: str) -> str:
    return (
        "Linha com formato de grupo atípico detectada durante o parse do orçamento. "
        f"Trecho: {line[:180]}"
    )


def _msg_ignored_line(line: str) -> str:
    return (
        "Linha do orçamento fora do padrão esperado e ignorada pelo parser. "
        f"Trecho: {line[:180]}"
    )


def _msg_non_numeric_group_total(item: str, raw: str) -> str:
    return (
        f"Grupo com custo_total não numérico. O grupo {item} foi preservado, mas o valor '{raw}' não pôde ser interpretado numericamente."
    )


def _msg_group_math_divergence(item: str, child_sum: float, ct: float, tol: float) -> str:
    return (
        f"Divergência matemática em grupo do orçamento. O grupo {item} tem soma dos filhos igual a {child_sum:.2f}, "
        f"enquanto o custo_total informado é {ct:.2f} (tolerância {tol:.2f})."
    )


def _msg_invalid_comp_range() -> str:
    return (
        "Anexo de composições não processado: o intervalo informado é inválido ou zero. "
        "Envie composicoes_inicio/fim válidos para incluir as composições no JSON."
    )


def _msg_comp_summary(c_ini: int, c_fim: int, comp: Composicoes) -> str:
    return (
        f"Resumo do anexo de composições: páginas {c_ini}-{c_fim}; principais={len(comp.principais)}; "
        f"auxiliares_globais={len(comp.auxiliares_globais)}; aliases={len(comp.aliases_auxiliares)}."
    )


def _resolve_budget_text_engine(config: dict | None) -> str:
    performance_cfg = (config or {}).get("performance") or {}
    explicit = str(performance_cfg.get("budget_text_engine") or "").strip().lower()
    if explicit in {"pypdf", "plumber", "auto"}:
        return explicit
    return "auto"
def parse_budget_document(
    pdf_bytes: bytes,
    ranges: Dict[str, Tuple[int, int]],
    config: dict,
    context: dict | None = None,
) -> Dict[str, Any]:
    """
    Parser SINAPI (Orçamento Sintético + Composições Analíticas).
    - ranges["orcamento"] = (ini, fim) 1-based
    - ranges["composicoes"] = (ini, fim) 1-based (ou (0,0) para pular)
    """
    context = context or {}
    avisos: List[str] = []
    erros: List[str] = []
    divergencias: List[dict] = []
    ocorrencias: List[dict] = []
    perf = PerformanceTracker()

    o_ini, o_fim = ranges.get("orcamento", (0, 0))
    c_ini, c_fim = ranges.get("composicoes", (0, 0))
    budget_text_engine = _resolve_budget_text_engine(config)
    perf.metric("budget_text_engine", budget_text_engine)
    perf.metric("orcamento_range", {"inicio": o_ini, "fim": o_fim})
    perf.metric("composicoes_range", {"inicio": c_ini, "fim": c_fim})

    with PdfDocumentSession(pdf_bytes) as full_pdf_session:
        perf.metric("pdf_page_count", full_pdf_session.page_count)
        # ===== ORÇAMENTO =====
        if o_ini and o_fim and o_ini >= 1 and o_fim >= o_ini:
            pages_text = extract_pages_text(pdf_bytes, o_ini, o_fim, pdf_session=full_pdf_session, engine=budget_text_engine)
            pages_text, o_fim_processado, expanded_orc = _expand_orcamento_pages_if_needed(
                pdf_bytes,
                o_ini,
                o_fim,
                pages_text,
                pdf_session=full_pdf_session,
                text_engine=budget_text_engine,
            )
            perf.metric("orcamento_pages_processadas", max(0, o_fim_processado - o_ini + 1))
            perf.metric("orcamento_intervalo_expandido", expanded_orc)
            perf.stage("orcamento_extract_text_ms")
            orc, a, e, d, ocs = _parse_orcamento_sintetico(pages_text, config=config, context=context)
            avisos.extend(a)
            erros.extend(e)
            divergencias.extend(d)
            ocorrencias.extend(ocs)
            perf.stage("orcamento_parse_ms")
            if expanded_orc:
                _push_message(
                    avisos, erros, ocorrencias,
                    codigo="orcamento_intervalo_expandido",
                    severidade="info",
                    categoria="orcamento",
                    mensagem=_msg_budget_interval_expanded(o_fim_processado),
                    etapa="orcamento",
                    pagina_inicio=o_ini,
                    pagina_fim=o_fim_processado,
                )
        else:
            orc = OrcamentoSintetico(itens_raiz=[], itens_plano=[])
            perf.metric("orcamento_pages_processadas", 0)
            perf.stage("orcamento_extract_text_ms")
            perf.stage("orcamento_parse_ms")
            _push_message(
                avisos, erros, ocorrencias,
                codigo="orcamento_intervalo_invalido",
                severidade="aviso",
                categoria="orcamento",
                mensagem=_msg_invalid_budget_range(),
                etapa="orcamento",
                pagina_inicio=o_ini or None,
                pagina_fim=o_fim or None,
            )

        # refs para validar/associar composições (inclui números úteis)
        item_refs_list = _collect_item_refs(orc.itens_raiz)

        # detectar insumos citados como item de orçamento (ex.: 00000370)
        insumos_no_orc = []

        def _walk_nodes(nodes):
            for n in nodes or []:
                yield n
                yield from _walk_nodes(getattr(n, "filhos", None) or (n.get("filhos") if isinstance(n, dict) else []) or [])

        for n in _walk_nodes(orc.itens_raiz):
            tipo = (getattr(n, "tipo", None) if not isinstance(n, dict) else n.get("tipo")) or ""
            if str(tipo).lower() != "item":
                continue
            codigo = (getattr(n, "codigo", None) if not isinstance(n, dict) else n.get("codigo")) or ""
            fonte = (getattr(n, "fonte", None) if not isinstance(n, dict) else n.get("fonte")) or ""
            item = (getattr(n, "item", None) if not isinstance(n, dict) else n.get("item")) or ""
            if _is_probably_insumo_codigo(str(codigo), str(fonte)):
                insumos_no_orc.append(f"{codigo}|{fonte} (item {item})")

        for rid in sorted(set(insumos_no_orc)):
            item = ""
            m_item = re.search(r"\(item\s+([^\)]+)\)", rid)
            if m_item:
                item = m_item.group(1).strip()
            _push_message(
                avisos, erros, ocorrencias,
                codigo="item_direto_sem_composicao_analitica",
                severidade="info",
                categoria="orcamento",
                mensagem=_msg_direct_item_without_analytic(item=item or "?", ref_id=rid.split(" (item ")[0]),
                etapa="orcamento",
                item=item,
                ref_id=rid.split(" (item ")[0],
                causa="Item do orçamento parece ser material/insumo direto, portanto a ausência de composição analítica pode ser esperada no próprio PDF.",
                sugestao="Conferir apenas se o lançamento direto faz sentido no contexto do orçamento. Não tratar automaticamente como falha do parser.",
                evidencia={"classificacao": "item_direto_ou_insumo"},
            )

        placeholders = [r for r in item_refs_list if str(r.get("codigo", "")).strip().upper() == "COMPOSICAO"]
        if placeholders:
            exemplos = ", ".join([f"item {r.get('item')}" for r in placeholders[:10]])
            _push_message(
                avisos, erros, ocorrencias,
                codigo="orcamento_codigo_placeholder",
                severidade="aviso",
                categoria="orcamento",
                mensagem=(
                    f"Itens com código de composição ausente ou quebrado detectados no orçamento. Quantidade={len(placeholders)}. Exemplos: {exemplos}"
                ),
                etapa="orcamento",
                evidencia={"exemplos": exemplos, "quantidade": len(placeholders)},
            )
            item_refs_list = [r for r in item_refs_list if r not in placeholders]
        perf.metric("orcamento_item_refs", len(item_refs_list))
        perf.metric("orcamento_insumos_diretos_detectados", len(set(insumos_no_orc)))
        perf.stage("orcamento_refs_ms")

        # ===== COMPOSIÇÕES =====
        comp = Composicoes(principais={}, auxiliares_globais={}, aliases_auxiliares={})
        itens_faltando: List[str] = []
        composicoes_nao_associadas: List[str] = []
        associacoes_por_indicio: List[dict] = []

        if not (c_ini and c_fim and c_ini >= 1 and c_fim >= c_ini):
            perf.metric("composicoes_pages_processadas", 0)
            _push_message(
                avisos, erros, ocorrencias,
                codigo="composicoes_intervalo_invalido",
                severidade="aviso",
                categoria="composicoes",
                mensagem=_msg_invalid_comp_range(),
                etapa="composicoes",
                pagina_inicio=c_ini or None,
                pagina_fim=c_fim or None,
            )
        else:
            perf.metric("composicoes_pages_processadas", max(0, c_fim - c_ini + 1))
            comp, comp_avisos, comp_erros, itens_faltando, composicoes_nao_associadas, associacoes_por_indicio = parse_composicoes_sinapi(
                pdf_bytes=pdf_bytes,
                start_1based=c_ini,
                end_1based=c_fim,
                config=config,
                item_refs=item_refs_list,
                context=context,
                pdf_session=full_pdf_session,
            )
            comp_debug_avisos, comp_avisos_publicos = _split_composition_debug_messages(comp_avisos)
            comp_debug_erros, comp_erros_publicos = _split_composition_debug_messages(comp_erros)
            perf.metric("composicoes_debug", {"avisos": comp_debug_avisos, "erros": comp_debug_erros})
            _ingest_external_messages(
                avisos, erros, ocorrencias,
                mensagens=comp_avisos_publicos,
                severidade="aviso",
                categoria="composicoes",
                etapa="composicoes",
            )
            _ingest_external_messages(
                avisos, erros, ocorrencias,
                mensagens=comp_erros_publicos,
                severidade="erro",
                categoria="composicoes",
                etapa="composicoes",
            )
            _push_message(
                avisos, erros, ocorrencias,
                codigo="composicoes_resumo_processamento",
                severidade="info",
                categoria="composicoes",
                mensagem=_msg_comp_summary(c_ini, c_fim, comp),
                etapa="composicoes",
                pagina_inicio=c_ini,
                pagina_fim=c_fim,
                evidencia={
                    "principais": len(comp.principais),
                    "auxiliares_globais": len(comp.auxiliares_globais),
                    "aliases": len(comp.aliases_auxiliares),
                },
            )
        perf.metric("composicoes_principais", len(comp.principais))
        perf.metric("composicoes_auxiliares_globais", len(comp.auxiliares_globais))
        perf.metric("composicoes_aliases", len(comp.aliases_auxiliares))
        perf.stage("composicoes_parse_ms")

    if not getattr(orc, "descricao", ""):
        orc.descricao = str(context.get("obra_nome") or "").strip()

    resumo_validacao = _build_validation_resumo(avisos=avisos, erros=erros, ocorrencias=ocorrencias)

    validacao_kwargs = {
        "itens_faltando": sorted(set(itens_faltando)),
        "composicoes_nao_associadas_diretamente": sorted(set(composicoes_nao_associadas)),
        "associacoes_por_indicio": associacoes_por_indicio,
        "avisos": avisos,
        "erros": erros,
        "divergencias": divergencias,
        "ocorrencias": ocorrencias,
        "resumo": resumo_validacao,
    }

    include_tipo_output = bool(((config or {}).get("output_options") or {}).get("include_tipo_in_final_json", False))
    comp_out = sanitize_composicoes_for_output(comp, include_tipo=include_tipo_output) if comp is not None else None
    perf.stage("validation_and_output_ms")

    resp = ParseResponse(
        base_id="misto",
        orcamento_sintetico=orc,
        composicoes=comp_out,
        validacao=Validacao(**validacao_kwargs),
    )
    payload = resp.model_dump(exclude_none=True, exclude_unset=True)
    payload.setdefault("meta", {})
    payload["meta"]["performance"] = perf.export()
    return payload

# --------------------
# ORÇAMENTO: helpers
# --------------------
def _parse_orcamento_sintetico(
    pages_text: List[str],
    config: dict,
    context: dict,
) -> tuple[OrcamentoSintetico, List[str], List[str], List[dict], List[dict]]:
    syn = config.get("synthetic", {})
    san = config.get("sanitizer", {})
    val = config.get("validation", {})
    ignore_markers = set(syn.get("ignore_markers", []))
    header_markers = set(syn.get("header_markers", []))
    break_before = san.get("break_before", [])
    strip_inline_from = san.get("strip_inline_from", [])
    drop_lines_if_contains = san.get("drop_lines_if_contains", [])
    toxic_for_continuation = san.get("toxic_for_continuation", [])
    missing_total_value = val.get("missing_group_total_value", "")
    allow_missing_group_total = bool(val.get("allow_missing_group_total", True))
    report_atypical_groups = bool(val.get("report_atypical_groups", False))
    fail_if_contaminated_text = bool(val.get("fail_if_contaminated_text", True))
    report_all_group_checks = bool(val.get("report_all_group_checks", False))
    tol_item_abs = float(val.get("tolerances", {}).get("item_abs", 0.02))
    tol_item_rel = float(val.get("tolerances", {}).get("item_rel", 0.0002))
    tol_group_abs = float(val.get("tolerances", {}).get("group_abs", 0.05))
    tol_group_rel = float(val.get("tolerances", {}).get("group_rel", 0.0001))
    dynamic_markers = build_dynamic_markers(context)
    orc_regexes = _build_orcamento_regexes(config)

    raw_lines: List[str] = []
    for page_text in pages_text:
        fixed = break_glued_markers(page_text, break_before=break_before, dynamic_markers=dynamic_markers)
        for ln in normalize_lines(fixed):
            if any(m in ln for m in ignore_markers):
                continue
            if ln in header_markers:
                continue
            structural_line = bool(
                _item_header_match(ln, orc_regexes)
                or orc_regexes["item_composicao_head"].match(ln)
                or (_RE_GROUP_WITH_TOTAL.match(ln) and _is_probable_group_heading(_RE_GROUP_WITH_TOTAL.match(ln).group("desc")))
                or (_RE_GROUP_NO_TOTAL.match(ln) and _is_probable_group_heading(_RE_GROUP_NO_TOTAL.match(ln).group("desc")))
            )
            if _looks_like_budget_noise_line(ln, dynamic_markers=dynamic_markers) and not structural_line:
                continue
            if _looks_like_orcamento_header_line(ln, config) or norm_text(ln).startswith("custo unitario") or norm_text(ln).startswith("s/"):
                continue
            raw_lines.append(ln)
    sanitized_lines: List[str] = []
    for ln in raw_lines:
        s = re.sub(r"\s+", " ", str(ln or "").replace("\u00a0", " ")).strip()
        if not s:
            continue
        structural_line = bool(
            _item_header_match(s, orc_regexes)
            or orc_regexes["item_composicao_head"].match(s)
            or (_RE_GROUP_WITH_TOTAL.match(s) and _is_probable_group_heading(_RE_GROUP_WITH_TOTAL.match(s).group("desc")))
            or (_RE_GROUP_NO_TOTAL.match(s) and _is_probable_group_heading(_RE_GROUP_NO_TOTAL.match(s).group("desc")))
            or _line_has_numeric_tail(s)
        )
        s = clean_inline(
            s,
            strip_inline_from=strip_inline_from,
            dynamic_markers=[] if structural_line else dynamic_markers,
        )
        if not s:
            continue
        if drop_lines_if_contains and any(m in s for m in drop_lines_if_contains if m):
            continue
        sanitized_lines.append(s)
    raw_lines = sanitized_lines

    started = False
    lines: List[str] = []
    for ln in raw_lines:
        mg = _RE_GROUP_WITH_TOTAL.match(ln)
        mg2 = _RE_GROUP_NO_TOTAL.match(ln)
        if not started:
            if (mg and _is_probable_group_heading(mg.group("desc"))) or (mg2 and _is_probable_group_heading(mg2.group("desc"))):
                started = True
                lines.append(ln)
            continue
        if "TOTAL SEM BDI" in ln or "TOTAL COM BDI" in ln:
            break
        lines.append(ln)

    avisos: List[str] = []
    erros: List[str] = []
    divergencias: List[dict] = []
    ocorrencias: List[dict] = []
    if not lines:
        erros.append("Nenhuma linha do orçamento sintético foi detectada no intervalo informado.")
        _push_message(
            avisos, erros, ocorrencias,
            codigo="orcamento_sem_linhas_detectadas",
            severidade="erro",
            categoria="orcamento",
            mensagem="Nenhuma linha do orçamento sintético foi detectada no intervalo informado.",
            etapa="orcamento",
        )
        return OrcamentoSintetico(itens_raiz=[], itens_plano=[]), avisos, erros, divergencias, ocorrencias

    root = {"tipo": "raiz", "filhos": []}
    stack: List[tuple[int, dict]] = [(0, root)]
    itens_plano: List[str] = []
    last_item_node: Optional[dict] = None
    pending_orphans: List[str] = []

    def normalize_group_total(v: str) -> str:
        return (v or "").strip()

    def push_node(node: dict):
        nonlocal last_item_node
        level = node["item"].count(".") + 1
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1]
        parent.setdefault("filhos", []).append(node)
        stack.append((level, node))
        if node.get("tipo") == "item":
            last_item_node = node

    def _orphans_lock_previous_item() -> bool:
        return any(_line_has_numeric_tail(x) or _item_header_match(x, orc_regexes) for x in pending_orphans)

    def flush_orphans_as_warning(force: bool = False):
        nonlocal pending_orphans
        if not pending_orphans:
            return
        if last_item_node and not force and not _orphans_lock_previous_item():
            safe_lines: List[str] = []
            while pending_orphans:
                cand = pending_orphans[0]
                if _line_has_numeric_tail(cand):
                    break
                if not is_safe_continuation(
                    last_item_node.get("especificacao", ""),
                    cand,
                    toxic_for_continuation,
                    dynamic_markers=dynamic_markers,
                ):
                    break
                safe_lines.append(pending_orphans.pop(0))
            if safe_lines:
                extra_text = _sanitize_orcamento_especificacao(
                    " ".join(safe_lines),
                    strip_inline_from=strip_inline_from,
                    dynamic_markers=dynamic_markers,
                )
                if extra_text:
                    last_item_node["especificacao"] = _sanitize_orcamento_especificacao(
                        f"{last_item_node.get('especificacao', '')} {extra_text}",
                        strip_inline_from=strip_inline_from,
                        dynamic_markers=dynamic_markers,
                    )
        if pending_orphans:
            trecho = " | ".join(pending_orphans[:3])
            _push_message(
                avisos, erros, ocorrencias,
                codigo="orcamento_linha_ignorada",
                severidade="aviso",
                categoria="orcamento",
                mensagem=_msg_ignored_line(trecho),
                etapa="orcamento",
                linha_original=trecho[:180],
            )
            pending_orphans = []

    i = 0
    while i < len(lines):
        ln = lines[i]
        mg = _RE_GROUP_WITH_TOTAL.match(ln)
        if mg and _is_probable_group_heading(mg.group("desc")):
            flush_orphans_as_warning(force=True)
            item = mg.group("item").strip()
            desc = mg.group("desc").strip()
            total = mg.group("total").strip()
            tipo = "meta" if "." not in item else "submeta"
            group_node = {"tipo": tipo, "item": item, "descricao": desc, "filhos": []}
            group_total = normalize_group_total(total)
            if group_total:
                group_node["custo_total"] = group_total
            push_node(group_node)
            i += 1
            continue

        mg2 = _RE_GROUP_NO_TOTAL.match(ln)
        if mg2 and _is_probable_group_heading(mg2.group("desc")):
            flush_orphans_as_warning(force=True)
            item = mg2.group("item").strip()
            desc = mg2.group("desc").strip()
            total = ""
            if i + 1 < len(lines):
                mn = _RE_ONLY_NUMBER.match(lines[i + 1])
                if mn:
                    total = mn.group("num").strip()
                    i += 1
            if not total:
                if allow_missing_group_total:
                    total = missing_total_value
                    _push_message(
                        avisos, erros, ocorrencias,
                        codigo="grupo_sem_custo_total",
                        severidade="aviso",
                        categoria="orcamento",
                        mensagem=_msg_missing_group_total(item),
                        etapa="orcamento",
                        item=item,
                        causa="Campo custo_total não apareceu preenchido no PDF.",
                        sugestao="Conferir se o total do grupo foi omitido no documento original.",
                    )
                else:
                    _push_message(
                        avisos, erros, ocorrencias,
                        codigo="grupo_sem_custo_total_bloqueante",
                        severidade="erro",
                        categoria="orcamento",
                        mensagem=f"Grupo {item} sem custo total informado e a configuração atual não permite manter esse campo vazio.",
                        etapa="orcamento",
                        item=item,
                    )
                    total = missing_total_value
            tipo = "meta" if "." not in item else "submeta"
            group_node = {"tipo": tipo, "item": item, "descricao": desc, "filhos": []}
            group_total = normalize_group_total(total)
            if group_total:
                group_node["custo_total"] = group_total
            push_node(group_node)
            i += 1
            continue

        header_line = ln
        header_match = _item_header_match(header_line, orc_regexes)
        header_consumed_until = i + 1
        if not header_match:
            expanded_head, consumed_until = _extract_multiline_composicao_head(lines, i, orc_regexes=orc_regexes, config=config)
            if expanded_head:
                header_line = expanded_head
                header_match = _item_header_match(header_line, orc_regexes)
                header_consumed_until = consumed_until
        if header_match:
            prefix_lines = list(pending_orphans)
            pending_orphans = []
            has_numbers = any(_line_has_numeric_tail(x) for x in prefix_lines) or _line_has_numeric_tail(header_match.groupdict().get("rest") or "")
            suffix_lines, next_idx = _collect_item_suffix_lines(
                lines,
                header_consumed_until,
                has_numbers=has_numbers,
                orc_regexes=orc_regexes,
                leading_context=" ".join(prefix_lines + [header_match.groupdict().get("rest") or ""]),
                dynamic_markers=dynamic_markers,
            )
            parsed = None
            if orc_regexes["item_composicao_start"].match(header_line):
                parsed = _parse_item_block(
                    header_line=header_line,
                    prefix_lines=prefix_lines,
                    suffix_lines=suffix_lines,
                    strip_inline_from=strip_inline_from,
                    dynamic_markers=dynamic_markers,
                    item_start_re=orc_regexes["item_composicao_start"],
                    config=config,
                )
                if parsed and str(parsed.get("codigo", "")).strip().upper() == "COMPOSICAO":
                    _push_message(
                        avisos, erros, ocorrencias,
                        codigo="orcamento_codigo_quebrado",
                        severidade="aviso",
                        categoria="orcamento",
                        mensagem=_msg_placeholder_code(str(parsed.get("item") or "?"), str(parsed.get("codigo") or "COMPOSICAO")),
                        etapa="orcamento",
                        item=str(parsed.get("item") or ""),
                        ref_id=_normalize_ref_key(str(parsed.get("codigo") or ""), str(parsed.get("fonte") or "")),
                    )
            if not parsed:
                parsed = _parse_item_block(
                    header_line=header_line,
                    prefix_lines=prefix_lines,
                    suffix_lines=suffix_lines,
                    strip_inline_from=strip_inline_from,
                    dynamic_markers=dynamic_markers,
                    item_start_re=orc_regexes["item_start"],
                    config=config,
                )

            if parsed:
                ok, reason = _validate_item_math(
                    parsed,
                    tol_abs=tol_item_abs,
                    tol_rel=tol_item_rel,
                    fail_if_contaminated_text=fail_if_contaminated_text,
                    toxic_markers=strip_inline_from,
                    dynamic_markers=dynamic_markers,
                )
                if not ok:
                    divergencias.append({
                        "tipo": "item",
                        "item": parsed.get("item"),
                        "quant": parsed.get("quant"),
                        "custo_unitario_com_bdi": parsed.get("custo_unitario_com_bdi"),
                        "custo_parcial": parsed.get("custo_parcial"),
                        "motivo": reason,
                    })
                    _push_message(
                        avisos, erros, ocorrencias,
                        codigo="orcamento_item_validacao",
                        severidade="erro",
                        categoria="orcamento",
                        mensagem=f"Item {parsed.get('item')} falhou na validação matemática do orçamento: {reason}",
                        etapa="orcamento",
                        item=str(parsed.get("item") or ""),
                        ref_id=_normalize_ref_key(str(parsed.get("codigo") or ""), str(parsed.get("fonte") or "")),
                        causa=reason,
                    )
                else:
                    if parsed.pop("reconstruido_multilinha", False):
                        _push_message(
                            avisos, erros, ocorrencias,
                            codigo="orcamento_item_reconstruido",
                            severidade="info",
                            categoria="orcamento",
                            mensagem=(
                                f"Item {parsed.get('item')} reconstruído a partir de múltiplos fragmentos verticais do orçamento sintético."
                            ),
                            etapa="orcamento",
                            item=str(parsed.get("item") or ""),
                            ref_id=_normalize_ref_key(str(parsed.get("codigo") or ""), str(parsed.get("fonte") or "")),
                            evidencia={
                                "fragmentos_pre": list(prefix_lines),
                                "fragmentos_pos": list(suffix_lines),
                            },
                        )
                    parsed.pop("fragmentos_pre", None)
                    parsed.pop("fragmentos_pos", None)
                    push_node(parsed)
                    itens_plano.append(parsed["item"])
                    i = next_idx
                    continue

            trecho = " | ".join(prefix_lines + [ln] + suffix_lines)
            _push_message(
                avisos, erros, ocorrencias,
                codigo="orcamento_linha_ignorada",
                severidade="aviso",
                categoria="orcamento",
                mensagem=_msg_ignored_line(trecho),
                etapa="orcamento",
                linha_original=trecho[:180],
            )
            i = next_idx
            continue

        if (
            last_item_node
            and not _orphans_lock_previous_item()
            and not orc_regexes["item_composicao_head"].match(ln)
            and is_safe_continuation(
                last_item_node.get("especificacao", ""),
                ln,
                toxic_for_continuation,
                dynamic_markers=dynamic_markers,
            )
            and not _line_has_numeric_tail(ln)
        ):
            last_item_node["especificacao"] = _sanitize_orcamento_especificacao(
                f"{last_item_node.get('especificacao', '')} {clean_inline(ln, strip_inline_from, dynamic_markers=dynamic_markers)}",
                strip_inline_from=strip_inline_from,
                dynamic_markers=dynamic_markers,
            )
            i += 1
            continue

        pending_orphans.append(ln)
        i += 1

    flush_orphans_as_warning(force=True)
    _validate_tree_math(
        root.get("filhos", []),
        avisos=avisos,
        erros=erros,
        divergencias=divergencias,
        ocorrencias=ocorrencias,
        tol_abs=tol_group_abs,
        tol_rel=tol_group_rel,
        missing_total_value=missing_total_value,
        report_all=report_all_group_checks,
    )
    total_geral = _extract_budget_total(pages_text)
    return OrcamentoSintetico(itens_raiz=root["filhos"], itens_plano=itens_plano, total=total_geral), avisos, erros, divergencias, ocorrencias
def _try_parse_item_row(text: str, strip_inline_from: List[str], dynamic_markers: List[str], item_start_re: re.Pattern, config: dict | None = None) -> Optional[dict]:
    m = item_start_re.match(text)
    if not m:
        return None
    item = m.group("item").strip()
    codigo = m.group("codigo").strip()
    fonte = _canon_fonte(m.group("fonte").strip(), config=config)
    rest = m.group("rest").strip()
    mt = _RE_ITEM_TAIL.search(text)
    if not mt:
        return None
    und = mt.group("und").strip()
    quant = mt.group("quant").strip()
    s_bdi = mt.group("s_bdi").strip()
    c_bdi = mt.group("c_bdi").strip()
    parcial = mt.group("parcial").strip()
    especificacao = _RE_ITEM_TAIL.sub("", rest).strip()
    especificacao = _sanitize_orcamento_especificacao(
        especificacao,
        strip_inline_from=strip_inline_from,
        dynamic_markers=dynamic_markers,
    )
    return {
        "tipo": "item",
        "item": item,
        "codigo": codigo,
        "fonte": fonte,
        "especificacao": especificacao,
        "und": und,
        "quant": quant,
        "custo_unitario_sem_bdi": s_bdi,
        "custo_unitario_com_bdi": c_bdi,
        "custo_parcial": parcial,
    }
def _validate_item_math(
    item_node: dict,
    tol_abs: float,
    tol_rel: float,
    fail_if_contaminated_text: bool,
    toxic_markers: List[str],
    dynamic_markers: List[str],
) -> tuple[bool, str]:
    espec = item_node.get("especificacao") or ""
    und = str(item_node.get("und", "") or "").strip()
    if not _is_valid_unit_token(und):
        return False, f"unidade inválida ou suspeita: '{und}'"
    if fail_if_contaminated_text and toxic_markers and contains_any(espec, toxic_markers, dynamic_markers=dynamic_markers):
        return False, "especificacao contaminada (marcadores detectados)"
    q = parse_ptbr_number(item_node.get("quant", ""))
    u = parse_ptbr_number(item_node.get("custo_unitario_com_bdi", ""))
    p = parse_ptbr_number(item_node.get("custo_parcial", ""))
    if q is None or u is None or p is None:
        return True, "campos numéricos não parseáveis (ok)"
    expected = q * u
    tol = max(tol_abs, abs(expected) * tol_rel)
    if abs(expected - p) <= tol:
        return True, "ok"
    return False, f"parcial {p:.2f} != quant*unit {expected:.2f} (tol {tol:.2f})"
def _validate_tree_math(
    nodes: List[dict],
    avisos: List[str],
    erros: List[str],
    divergencias: List[dict],
    ocorrencias: List[dict],
    tol_abs: float,
    tol_rel: float,
    missing_total_value: str,
    report_all: bool,
) -> float:
    total_sum = 0.0
    for node in nodes:
        if node.get("tipo") == "item":
            v = parse_ptbr_number(node.get("custo_parcial", "")) or 0.0
            total_sum += v
        else:
            child_sum = _validate_tree_math(
                node.get("filhos", []),
                avisos,
                erros,
                divergencias,
                ocorrencias,
                tol_abs,
                tol_rel,
                missing_total_value,
                report_all,
            )
            total_sum += child_sum
            ct_raw = (node.get("custo_total") or "").strip()
            if not ct_raw or ct_raw == missing_total_value:
                continue
            ct = parse_ptbr_number(ct_raw)
            if ct is None:
                _push_message(
                    avisos, erros, ocorrencias,
                    codigo="grupo_custo_total_nao_numerico",
                    severidade="aviso",
                    categoria="validacao",
                    mensagem=_msg_non_numeric_group_total(str(node.get("item") or "?"), ct_raw),
                    etapa="validacao_orcamento",
                    item=str(node.get("item") or ""),
                )
                continue
            tol = max(tol_abs, abs(ct) * tol_rel)
            diff = child_sum - ct
            if report_all or abs(diff) > tol:
                divergencias.append({
                    "tipo": "grupo",
                    "item": node.get("item"),
                    "custo_total": ct_raw,
                    "soma_filhos": f"{child_sum:.2f}",
                    "diferenca": f"{diff:.2f}",
                    "tolerancia": f"{tol:.2f}",
                })
            if abs(diff) > tol:
                _push_message(
                    avisos, erros, ocorrencias,
                    codigo="grupo_divergencia_matematica",
                    severidade="erro",
                    categoria="validacao",
                    mensagem=_msg_group_math_divergence(str(node.get("item") or "?"), child_sum, ct, tol),
                    etapa="validacao_orcamento",
                    item=str(node.get("item") or ""),
                    evidencia={"soma_filhos": round(child_sum, 2), "custo_total": round(ct, 2), "tolerancia": round(tol, 2)},
                )
    return total_sum
def _looks_like_new_row(ln: str) -> bool:
    return bool(re.match(r"^\d+(?:\.\d+)*\s+", ln))
def _is_probable_group_heading(desc: str) -> bool:
    up = re.sub(r"\s+", " ", (desc or "").upper()).strip()
    if len(up) < 3:
        return False
    if re.match(r"^[A-ZÀ-Ú](?:\s|[,:;.-])", up):
        return False
    if up.startswith(("COM ", "SEM ", "PARA ", "DE ", "DA ", "DO ", "DAS ", "DOS ", "E ", "OU ")):
        return False
    if "FORNECIMENTO E INSTALA" in up and ("SUPORTE" in up or "PLACA" in up or "TOMADA" in up or "INTERRUPTOR" in up):
        return False
    tokens = re.findall(r"[A-ZÀ-Ú0-9%]+", up)
    if not tokens:
        return False
    if len(tokens[0]) <= 1:
        return False
    for w in _GROUP_BLACKLIST:
        if w in tokens:
            return False
    nums = re.findall(rf"{_NUM}", desc)
    if len(nums) >= 2:
        return False
    alpha_tokens = [t for t in tokens if re.search(r"[A-ZÀ-Ú]", t)]
    if not alpha_tokens:
        return False
    if max((len(t) for t in alpha_tokens), default=0) < 4:
        return False
    return True
from typing import Any, Dict, List
def _node_get(n: Any, key: str, default: Any = "") -> Any:
    if isinstance(n, dict):
        return n.get(key, default)
    return getattr(n, key, default)
def _node_children(n: Any) -> List[Any]:
    ch = _node_get(n, "filhos", []) or []
    return list(ch)
def _is_probably_insumo_codigo(codigo: str, banco: str) -> bool:
    c = (codigo or "").strip()
    b = (banco or "").strip().upper()
    return b == "SINAPI" and c.isdigit() and c.startswith("0000")
def _collect_item_refs(itens_raiz) -> List[Dict[str, str]]:
    """
    Retorna lista de refs do orçamento em formato compatível com todo o pipeline.
    Cada ref sai com os campos:
      - item
      - codigo
      - fonte
      - ref_id  ("CODIGO|BANCO")
      - especificacao / und / quant / custo_unitario_sem_bdi / custo_unitario_com_bdi / custo_parcial

    Mantemos também itens de material direto/insumo (ex.: 0000xxxx) porque, em
    documentos mistos, eles podem precisar de validação flexível, vínculo por
    equivalência ou dispensa explícita de composição analítica.
    """
    refs: List[Dict[str, str]] = []

    def walk(nodes):
        for n in nodes or []:
            tipo = str(_node_get(n, "tipo", "") or "").strip().lower()
            if tipo == "item":
                item = str(_node_get(n, "item", "") or "").strip()
                codigo = re.sub(r"\s+", " ", str(_node_get(n, "codigo", "") or "").replace("\u00a0", " ").strip())
                banco = _canon_fonte(str(_node_get(n, "fonte", "") or "").strip())
                if item and codigo and banco and codigo != "COMPOSICAO":
                    refs.append(
                        {
                            "item": item,
                            "codigo": codigo,
                            "fonte": banco,
                            "ref_id": _normalize_ref_key(codigo, banco),
                            "especificacao": str(_node_get(n, "especificacao", "") or "").strip(),
                            "und": str(_node_get(n, "und", "") or "").strip(),
                            "quant": str(_node_get(n, "quant", "") or "").strip(),
                            "custo_unitario_sem_bdi": str(_node_get(n, "custo_unitario_sem_bdi", "") or "").strip(),
                            "custo_unitario_com_bdi": str(_node_get(n, "custo_unitario_com_bdi", "") or "").strip(),
                            "custo_parcial": str(_node_get(n, "custo_parcial", "") or "").strip(),
                            "provavel_insumo_direto": _is_probably_insumo_codigo(codigo, banco),
                        }
                    )
            walk(_node_children(n))

    walk(itens_raiz)
    return refs


# Compatibilidade interna
parse_sinapi = parse_budget_document
