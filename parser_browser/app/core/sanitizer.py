from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, List, Optional


def _normalize_space(s: str) -> str:
    return re.sub(r"\s{2,}", " ", (s or "").replace("\u00a0", " ").strip())


_ACCENT_EQUIV = str.maketrans({
    "Á": "A", "À": "A", "Â": "A", "Ã": "A", "Ä": "A",
    "É": "E", "È": "E", "Ê": "E", "Ë": "E",
    "Í": "I", "Ì": "I", "Î": "I", "Ï": "I",
    "Ó": "O", "Ò": "O", "Ô": "O", "Õ": "O", "Ö": "O",
    "Ú": "U", "Ù": "U", "Û": "U", "Ü": "U",
    "Ç": "C",
    "²": "2", "³": "3",
    "á": "A", "à": "A", "â": "A", "ã": "A", "ä": "A",
    "é": "E", "è": "E", "ê": "E", "ë": "E",
    "í": "I", "ì": "I", "î": "I", "ï": "I",
    "ó": "O", "ò": "O", "ô": "O", "õ": "O", "ö": "O",
    "ú": "U", "ù": "U", "û": "U", "ü": "U",
    "ç": "C",
})


_DOMAIN_WORDS = {
    "A", "ABRIR", "ACABAMENTO", "ACI", "ACO", "ACRILICO", "ADMINISTRACAO", "AF", "AEREA", "AGREGADO", "ALVENARIA",
    "ALTURA", "ANEXO", "APARELHADA", "APLICACAO", "APLICADAS", "APLICADO", "AREA", "AREIA", "ARENOSA", "ARGAMASSA",
    "ARGILA", "ARMACAO", "ARMADURA", "ASFALTO", "ASFALTICA", "ATE", "ATIVIDADE", "AQUISICAO", "AUXILIAR", "BALDRAMES",
    "BANCO", "BANCADA", "BARRA", "BARRAMENTO", "BASE", "BASCULANTE", "BDI", "BETONEIRA", "BLOCO", "BLOCOS", "BOMBA", "BRANCO",
    "BROCA", "BUCHA", "CABO", "CAMADA", "CAMINHAO", "CAMINHAOZINHO", "CAPACIDADE", "CANTEIRO", "CARGA", "CATIONICA",
    "CAVALETE", "CA", "CAIXA", "CERAMICA", "CERAMICO", "CHAPA", "CHUVA", "CIMENTO", "CM", "CM30", "COBRE", "CODIGO", "COM",
    "COMPLEMENTARES", "COMPOSICAO", "COMPOSICOES", "COMPENSADA", "COMPRIMENTO", "COMUM", "CONCRETO", "CONDUTOR", "CONE",
    "CONCRETAGEM", "CONSTRUCAO", "CONTRAPISO", "COROAMENTO", "CORTE", "CROMADA", "CUSTO", "DA", "DAS", "DE", "DESCRICAO",
    "DETALHAMENTO", "DIAMETRO", "DILUIDO", "DMT", "DO", "DOS", "E", "ELETRICA", "ELETRICO", "EM", "EMBUTIR", "EMULSAO",
    "ENCARGOS", "ENDERECO", "ENERGIA", "ENTRADA", "EQUIPAMENTO", "EQUIPAMENTOS", "ESCAVACAO", "ESCRITORIO", "ESPESSURA",
    "ESTEIRAS", "ESTRUTURA", "EXECUCAO", "EXCLUSIVE", "FABRICACAO", "FABRICADAS", "FAIXA", "FCK", "FLEXIVEL", "FIXACAO",
    "FOLHAS", "FORMA", "FORNECIMENTO", "FORRACAO", "FOSSA", "FUNDO", "GALVANIZADO", "GERAL", "GORDURA", "GRAUS", "GUINDASTE", "H",
    "HIDRAULICA", "ICAMENTO", "IMERSAO", "IMPRIMACAO", "INCLUSA", "INCLUSO", "INCLUINDO", "INTEIRA", "INTERRUPTOR",
    "INSTALACAO", "INSUMO", "ISOLADO", "JANELA", "JAZIDA", "JOELHO", "KG", "KM", "KW", "LATERITICO", "LATAO", "LIGACAO",
    "LATAO", "LATEX", "LIMPEZA", "LONGA", "LS", "M", "M2", "M2XKM", "M3", "M3XKM", "MADEIRA", "MANUAL", "MATERIAL", "MECANICO",
    "MARMORE", "MECANIZADA", "MEIA", "MM", "MOBILIARIO", "MODULO", "MOMENTO", "MONTAGEM", "MPA", "MURO", "NA", "NAO", "NAS", "NÃO",
    "NO", "NOS", "OBRA", "OBJETO", "OU", "PANO", "PANOS", "PARA", "PARAFUSO", "PARAMETROS", "PARCIAL", "PAREDE", "PAREDES",
    "PAVIMENTACAO", "PAVIMENTADA", "PEQUENAS", "PINTURA", "PISO", "PLACA", "POLIDO", "POSTE", "PRE", "PREFABRICADAS",
    "PREPARO", "PRIMARIO", "PRODUCAO", "PROPRIO", "PROVISORIA", "PVC", "QUANT", "QUANTIDADE", "REFEITORIO", "REFLETIVA",
    "REFORCO", "REMOCAO", "RETIRADA", "REVESTIMENTO", "RIGIDO", "SARRAFO", "SE", "SELADOR", "SEM", "SERVENTE", "SERRADA",
    "SERVICO", "SERVICOS", "SIFONADO", "SIMPLES", "SINAPI", "SINALIZACAO", "SOLO", "SOLDAVEL", "SUB", "SUBBASE", "SUBLEITO",
    "SUPRESSAO", "T", "TA", "TANQUE", "TELHA", "TEMPO", "TESOURA", "TESOURAS", "TIPO", "TINTA", "ACRILICA", "TOPOGRAFO", "TORNEIRA",
    "TOTAL", "TRACO", "TRANSPORTE", "TRIFASICA", "TRIFASICO", "TRONCO", "TUBO", "UN", "UND", "UNIDADE", "URBANA", "USO",
    "UTILIZANDO", "VALOR", "VAO", "VASO", "VEGETACAO", "VERMELHA", "VESTIARIO", "VIA", "VIBRADOR", "VIGA", "VIGAS", "X",
}

# normaliza possíveis duplicações/erros de digitação leves no conjunto acima
_DOMAIN_WORDS = {w.replace(" ", "") for w in _DOMAIN_WORDS if w}

_FRAGMENT_STOPWORDS = {
    "A", "AS", "AO", "AOS", "COM", "DA", "DAS", "DE", "DO", "DOS", "E", "EM", "NA", "NAS", "NO", "NOS", "O", "OS", "PARA", "POR", "SEM",
}


def _normalized_ascii(text: str) -> str:
    return (text or "").translate(_ACCENT_EQUIV).upper()


def _is_upper_alpha_fragment(token: str) -> bool:
    return bool(re.fullmatch(r"[A-ZÀ-Ú]+", token or ""))


def _token_outer_parts(token: str) -> tuple[str, str, str]:
    match = re.fullmatch(r"([^A-ZÀ-Ú0-9]*)([A-ZÀ-Ú]+)([^A-ZÀ-Ú0-9]*)", token or "")
    if not match:
        return "", token or "", ""
    return match.group(1), match.group(2), match.group(3)


def _collapse_fragmented_upper_runs(text: str) -> str:
    words = _normalize_space(text).split()
    if not words:
        return ""

    collapsed: list[str] = []
    i = 0
    while i < len(words):
        prefix, core, suffix = _token_outer_parts(words[i])
        if _is_upper_alpha_fragment(core) and len(core) <= 3:
            j = i
            run_cores: list[str] = []
            run_prefix = prefix
            run_suffix = suffix
            while j < len(words):
                pfx, crt, sfx = _token_outer_parts(words[j])
                if not (_is_upper_alpha_fragment(crt) and len(crt) <= 3):
                    break
                if j > i and pfx:
                    break
                run_cores.append(crt)
                run_suffix = sfx
                j += 1
                if sfx:
                    break
            total_len = sum(len(part) for part in run_cores)
            has_single = any(len(part) == 1 for part in run_cores)
            if len(run_cores) >= 3 and total_len >= 5 and has_single:
                collapsed.append(f"{run_prefix}{''.join(run_cores)}{run_suffix}")
                i = j
                continue
        collapsed.append(words[i])
        i += 1
    return " ".join(collapsed)


def _merge_markers(static: List[str], dynamic: Optional[List[str]]) -> List[str]:
    dyn = [m for m in (dynamic or []) if m and m.strip()]
    merged = list(dict.fromkeys([m for m in (static or []) if m and m.strip()] + dyn))
    merged.sort(key=len, reverse=True)
    return merged


def _find_marker_pos(text: str, marker: str) -> int:
    if not text or not marker:
        return -1
    idx = text.find(marker)
    if idx != -1:
        return idx
    text_upper = text.upper()
    marker_upper = marker.upper()
    idx = text_upper.find(marker_upper)
    if idx != -1:
        return idx
    text_ascii = _normalized_ascii(text)
    marker_ascii = _normalized_ascii(marker)
    return text_ascii.find(marker_ascii)


@lru_cache(maxsize=4096)
def _split_glued_alnum_token(token: str) -> str:
    raw = token or ""
    if len(raw) < 5:
        return raw
    if re.search(r"[a-z]", raw):
        return raw
    if re.fullmatch(r"[0-9A-Z_\-/\.]+", raw) and ("AF_" in raw or "/" in raw or "-" in raw or "_" in raw):
        return raw

    ascii_token = _normalized_ascii(raw)
    if not re.fullmatch(r"[A-Z0-9]+", ascii_token):
        return raw

    lexicon = _DOMAIN_WORDS | _FRAGMENT_STOPWORDS | {"M3", "M2", "M3XKM", "M2XKM", "CM", "MM", "KM", "KW", "KG", "LS"}
    max_word = max(len(w) for w in lexicon)

    @lru_cache(maxsize=None)
    def solve(i: int):
        if i >= len(ascii_token):
            return (0.0, [])

        best_cost = float("inf")
        best_parts: list[str] = []

        upper = min(len(ascii_token), i + max_word)
        for j in range(i + 1, upper + 1):
            piece = ascii_token[i:j]
            raw_piece = raw[i:j]
            known = piece in lexicon
            numeric = bool(re.fullmatch(r"\d+(?:X\d+)?", piece))
            unitlike = piece in {"M", "M2", "M3", "CM", "MM", "KM", "%", "UN", "UND", "H", "T", "LS", "KW", "KG"}
            if not (known or numeric or unitlike):
                continue
            next_cost, next_parts = solve(j)
            if len(piece) == 1 and piece not in _FRAGMENT_STOPWORDS:
                weight = 2.6
            elif known and len(piece) >= 4:
                weight = 0.08
            elif known:
                weight = 0.18
            elif numeric or unitlike:
                weight = 0.28
            else:
                weight = 0.9
            cost = next_cost + weight + (0.01 / max(1, len(piece)))
            if cost < best_cost:
                best_cost = cost
                best_parts = [raw_piece] + next_parts

        next_cost, next_parts = solve(i + 1)
        fallback_cost = next_cost + 3.2
        if fallback_cost < best_cost:
            best_cost = fallback_cost
            best_parts = [raw[i : i + 1]] + next_parts
        return (best_cost, best_parts)

    cost, parts = solve(0)
    if not parts or len(parts) <= 1:
        return raw

    invalid_single = sum(1 for p in parts if len(p) == 1 and _normalized_ascii(p) not in _FRAGMENT_STOPWORDS)
    if invalid_single:
        return raw

    recognized_parts = sum(
        1
        for p in parts
        if _normalized_ascii(p) in lexicon or re.fullmatch(r"\d+(?:X\d+)?", _normalized_ascii(p) or "")
    )
    long_known_parts = sum(1 for p in parts if _normalized_ascii(p) in lexicon and len(p) >= 4)
    if recognized_parts < 2:
        return raw
    if long_known_parts == 0 and all(_normalized_ascii(p) in _FRAGMENT_STOPWORDS for p in parts):
        return raw
    if cost / max(1, len(parts)) > 1.05:
        return raw
    return " ".join(parts)




def _insert_letter_digit_boundaries(text: str) -> str:
    s = text or ""
    # Separa sequências úteis como DE25MM -> DE 25 MM, JOELHO90 -> JOELHO 90, 4FOLHAS -> 4 FOLHAS.
    s = re.sub(r"(?<=[A-ZÀ-Ú])(?=\d)", " ", s)
    s = re.sub(r"(?<=\d)(?=[A-ZÀ-Ú])", " ", s)
    s = re.sub(r"(?<=[A-ZÀ-Ú])(?=\()", " ", s)
    s = re.sub(r"(?<=\d)(?=\()", " ", s)
    s = re.sub(r"(?<=\))(?=[A-ZÀ-Ú])", " ", s)
    s = re.sub(r"(?<=,)(?=[A-ZÀ-Ú0-9])", " ", s)
    return _normalize_space(s)


def _fix_common_glued_phrases(text: str) -> str:
    s = text or ""
    replacements = {
        "USODE": "USO DE",
        "COMBARRAMENTO": "COM BARRAMENTO",
        "INTERRUPTORSIMPLES": "INTERRUPTOR SIMPLES",
        "CABODE": "CABO DE",
        "DECOBRE": "DE COBRE",
        "FLEXÍVELISOLADO": "FLEXÍVEL ISOLADO",
        "FLEXIVELISOLADO": "FLEXIVEL ISOLADO",
        "DEABRIR": "DE ABRIR",
        "PARAPISO": "PARA PISO",
        "EMPANOS": "EM PANOS",
        "COM4": "COM 4",
        "TIPOACI": "TIPO ACI",
        "DE25MM": "DE 25 MM",
        "DE20MM": "DE 20 MM",
        "DE32MM": "DE 32 MM",
        "DE40MM": "DE 40 MM",
        "DE50MM": "DE 50 MM",
        "JOELHO90": "JOELHO 90",
        "CAIXADE": "CAIXA DE",
        "DEGORDURA": "DE GORDURA",
        "GORDURASIMPLES": "GORDURA SIMPLES",
        "BANCADADE": "BANCADA DE",
        "DEMÁRMORE": "DE MÁRMORE",
        "MARMOREBRANCO": "MARMORE BRANCO",
        "BRANCOPOLIDO": "BRANCO POLIDO",
        "APLICAÇÃOMANUAL": "APLICAÇÃO MANUAL",
        "APLICACAOMANUAL": "APLICACAO MANUAL",
        "DEPINTURA": "DE PINTURA",
        "COMTINTA": "COM TINTA",
        "LÁTEXACRÍLICA": "LÁTEX ACRÍLICA",
        "LATEXACRILICA": "LATEX ACRILICA",
        "AÇOCA": "AÇO CA",
        "ACOCA": "ACO CA",
        "PANOSCEGOS": "PANOS CEGOS",
        "TINTALÁTEX": "TINTA LÁTEX",
        "TINTALATEX": "TINTA LATEX",
        "LÁTEXPVA": "LÁTEX PVA",
        "LATEXPVA": "LATEX PVA",
        "PVAEM": "PVA EM",
        "EMPAREDES": "EM PAREDES",
        "PISOCOM": "PISO COM",
        "COMPLACAS": "COM PLACAS",
        "PLACASTIPO": "PLACAS TIPO",
        "TIPOESMALTADA": "TIPO ESMALTADA",
        "CONCRETOARMADO": "CONCRETO ARMADO",
        "ARMADOUTILIZANDO": "ARMADO UTILIZANDO",
        "UTILIZANDOAÇO": "UTILIZANDO AÇO",
        "UTILIZANDOACO": "UTILIZANDO ACO",
        "INSTALADOEM": "INSTALADO EM",
        "EMPRUMADA": "EM PRUMADA",
        "PRUMADADEÁGUA": "PRUMADA DE ÁGUA",
        "PRUMADADEAGUA": "PRUMADA DE AGUA",
        "FORNECIDAE": "FORNECIDA E",
        "EINSTALADA": "E INSTALADA",
        "INSTALADAEM": "INSTALADA EM",
        "EMRAMAL": "EM RAMAL",
        "RAMALDEDESCARGA": "RAMAL DE DESCARGA",
        "DEFACHADA": "DE FACHADA",
        "DEÁGUA": "DE ÁGUA",
        "DEAGUA": "DE AGUA",
    }
    for src, dst in replacements.items():
        s = s.replace(src, dst)
    return s

def repair_glued_terms(text: str) -> str:
    s = _normalize_space(text)
    if not s:
        return s

    s = _collapse_fragmented_upper_runs(s)
    s = _insert_letter_digit_boundaries(s)
    s = _fix_common_glued_phrases(s)

    def repl(match: re.Match) -> str:
        token = match.group(0)
        return _split_glued_alnum_token(token)

    # Repara trechos alfanuméricos longos e colados, preservando pontuação externa.
    s = re.sub(r"[A-ZÀ-Ú0-9²³]{5,}", repl, s)
    s = _fix_common_glued_phrases(s)

    # Correções finas de pontuação e conectores que costumam sair colados.
    s = re.sub(r",(?=[A-ZÀ-Ú])", ", ", s)
    s = re.sub(r"\)(?=[A-ZÀ-Ú])", ") ", s)
    s = re.sub(r"(?<=[A-ZÀ-Ú])\((?=[A-ZÀ-Ú])", " (", s)
    s = re.sub(r"(?<=[A-ZÀ-Ú]),\s*E=", ", E=", s)
    s = re.sub(r"\bNAO\b", "NÃO", s)
    s = re.sub(r"\bATE\b", "ATÉ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def normalize_service_text(text: str) -> str:
    s = repair_glued_terms(text)
    if not s:
        return s
    s = re.sub(r"(?<=\d)\s*,\s*(?=\d)", ",", s)
    s = re.sub(r"\s+,", ",", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"\s+([;:.])", r"\1", s)
    s = re.sub(r"(\d+)\s+X\s+(\d+)\s+(CM|MM|M)\b", r"\1X\2 \3", s)
    s = re.sub(r"(?<=\b\d\sMM)-(?=[A-ZÀ-Ú])", " - ", s)
    s = re.sub(r"(?<=\b\d\sCM)-(?=[A-ZÀ-Ú])", " - ", s)
    s = re.sub(r"\b(M)DE\s*V([AÃ])O\b", r"\1 DE V\2O", s, flags=re.IGNORECASE)
    s = re.sub(r"\bPOR\s+TA\b", "PORTA", s, flags=re.IGNORECASE)
    s = re.sub(r"\bELETRI\s+CISTA\b", "ELETRICISTA", s, flags=re.IGNORECASE)
    s = re.sub(r"\bAUXILI\s+AR\b", "AUXILIAR", s, flags=re.IGNORECASE)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def break_glued_markers(text: str, break_before: List[str], dynamic_markers: Optional[List[str]] = None) -> str:
    if not text:
        return text or ""
    markers = _merge_markers(break_before, dynamic_markers)
    if not markers:
        return text
    pattern = r"(?=(" + "|".join(re.escape(m) for m in markers) + r"))"
    rx = re.compile(pattern)
    return rx.sub("\n", text)


def clean_inline(text: str, strip_inline_from: List[str], dynamic_markers: Optional[List[str]] = None) -> str:
    s = _normalize_space(text)
    markers = _merge_markers(strip_inline_from, dynamic_markers)
    if not s or not markers:
        return s
    cut_idx = None
    for m in markers:
        idx = _find_marker_pos(s, m)
        if idx != -1:
            cut_idx = idx if cut_idx is None else min(cut_idx, idx)
    if cut_idx is not None:
        s = s[:cut_idx].rstrip()
    return _normalize_space(s)


def sanitize_lines(
    lines: Iterable[str],
    drop_lines_if_contains: List[str],
    strip_inline_from: List[str],
    dynamic_markers: Optional[List[str]] = None,
) -> List[str]:
    out: List[str] = []
    for ln in lines:
        s = _normalize_space(ln)
        if not s:
            continue
        s = clean_inline(s, strip_inline_from=strip_inline_from, dynamic_markers=dynamic_markers)
        if not s:
            continue
        if drop_lines_if_contains and any(m in s for m in drop_lines_if_contains if m):
            continue
        out.append(s)
    return out


def contains_any(text: str, markers: List[str], dynamic_markers: Optional[List[str]] = None) -> bool:
    s = text or ""
    merged = _merge_markers(markers, dynamic_markers)
    return any(m in s for m in merged)


def is_safe_continuation(prev_text: str, next_line: str, toxic_for_continuation: List[str], dynamic_markers: Optional[List[str]] = None) -> bool:
    s = _normalize_space(next_line)
    if not s:
        return False
    if re.match(r"^\d+(?:\.\d+)*\s+\S+", s):
        return False
    if contains_any(s, toxic_for_continuation, dynamic_markers=dynamic_markers):
        return False
    return True
