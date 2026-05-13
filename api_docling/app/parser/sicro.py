from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from pypdf import PdfReader

from app.core.base_rules import canonical_bank
from app.core.money import parse_ptbr_number
from app.core.numeric_fidelity import numeric_source, clean_numeric_text, apply_numeric_sources_to_row
from app.core.schemas import BlocoComposicao, LinhaComposicao, LinhaInsumo
from app.parser.sicro_profile import classify_sicro_code, identify_code_and_bank, sicro_config_payload

_NUM = r"\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?"
_PRICE = rf"(?:R\$\s*)?(?P<value>{_NUM})"

RE_ITEM_HEADER = re.compile(r"^(?P<item>\d+(?:\.\d+)*)\s+C[ÓO]DIGO\s+BANCO\s+DESCRI", re.IGNORECASE)
RE_COMP_START = re.compile(
    r"^Composi(?:ç[aã]o|cao)\s+(?P<code>[0-9A-Z./\-]+)\s+(?P<bank>SICRO\s*3?|DNIT)\s+(?P<rest>.*)$",
    re.IGNORECASE,
)
RE_ANY_COMP_START = re.compile(r"^Composi(?:ç[aã]o|cao)\s+(?P<code>[0-9A-Z./\-]+)\s+(?P<bank>[A-Z0-9ÇÃÕÁÉÍÓÚ./\-]+)\b", re.IGNORECASE)
RE_COMP_TAIL = re.compile(
    rf"\s(?P<und>[A-Za-z0-9/%²³]+)\s+(?P<quant>{_NUM})\s+(?P<valor>{_NUM})\s+(?P<total>{_NUM})\s*$"
)
RE_SECTION_HEADER = {
    "A": re.compile(r"^A\s+C[ÓO]DIGO\s+BANCO\s+EQUIP", re.IGNORECASE),
    "B": re.compile(r"^B\s+C[ÓO]DIGO\s+BANCO\s+M[ÃA]O\s+DE\s+OBRA", re.IGNORECASE),
    "C": re.compile(r"^C\s+BANCO\s+C[ÓO]DIGO\s+MATERIAL", re.IGNORECASE),
    "D": re.compile(r"^D\s+BANCO\s+C[ÓO]DIGO\s+ATIVIDADES\s+AUX", re.IGNORECASE),
    "E": re.compile(r"^E\s+BANCO\s+INSUMO\s+TEMPOS\s+FIXOS", re.IGNORECASE),
    "F": re.compile(r"^F\s+BANCO\s+INSUMO\s+MOMENTO\s+DE\s+TRANSPORTE", re.IGNORECASE),
}
RE_SICRO_A = re.compile(
    rf"^Insumo\s+(?P<code>E\d+)\s+(?P<bank>SICRO\s*3?|DNIT)\s+(?P<desc>.+?)\s+(?P<quant>{_NUM})\s+(?P<util_op>{_NUM})\s+(?P<util_imp>{_NUM})\s+(?P<custo_op>{_NUM})\s+(?P<custo_imp>{_NUM})\s+(?P<custo_hor>{_NUM})$",
    re.IGNORECASE,
)
RE_SICRO_B = re.compile(
    rf"^Insumo\s+(?P<code>P\d+)\s+(?P<bank>SICRO\s*3?|DNIT)\s+(?P<desc>.+?)\s+(?P<quant>{_NUM})\s+(?P<salario_hora>{_NUM})\s+(?P<custo_hor>{_NUM})$",
    re.IGNORECASE,
)
RE_SICRO_C = re.compile(
    rf"^Insumo\s+(?P<bank>SICRO\s*3?|DNIT)\s+(?P<code>M\d+)\s+(?P<desc>.+?)\s+(?P<quant>{_NUM})\s+(?P<und>[A-Za-z0-9/%²³]+)\s+(?P<preco_unit>{_NUM})\s+(?P<custo_hor>{_NUM})$",
    re.IGNORECASE,
)
RE_SICRO_D = re.compile(
    rf"^(?:Atividade\s+Auxiliar|Composi(?:ç[aã]o|cao)\s+Auxiliar|Auxiliar)\s+(?P<bank>SICRO\s*3?|DNIT)\s+(?P<code>[0-9A-Z./\-]+)\s+(?P<desc>.+?)\s+(?P<quant>{_NUM})\s+(?P<und>[A-Za-z0-9/%²³]+)\s+(?P<preco_unit>{_NUM})\s+(?P<custo_hor>{_NUM})$",
    re.IGNORECASE,
)
RE_SICRO_E = re.compile(
    rf"^Tempo\s+Fixo\s+(?P<bank>SICRO\s*3?|DNIT)\s+(?P<insumo>M\d+)\s+(?P<desc>.+?)\s+(?P<code>\d+)\s+(?P<quant>{_NUM})\s+(?P<und>[A-Za-z0-9/%²³]+)\s+(?P<preco_unit>{_NUM})\s+(?P<custo_hor>{_NUM})$",
    re.IGNORECASE,
)
RE_SICRO_F_BASE = re.compile(
    rf"^(?:(?:Momento\s+de\s+Transporte)\s+)?(?P<bank>SICRO\s*3?|DNIT)\s+(?P<insumo>M\d+)\s+(?P<desc>.+?)\s+(?P<quant>{_NUM})\s+(?P<und>[A-Za-z0-9/%²³]+)\s+(?P<code_ln>\d+)$",
    re.IGNORECASE,
)
RE_MO_LINE = re.compile(rf"MO\s+sem\s+LS\s*=+>\s*(?P<mo>{_NUM})\s+LS\s*=+>\s*(?P<ls>{_NUM})\s+MO\s+com\s+LS\s*=+>\s*(?P<com>{_NUM})", re.IGNORECASE)
RE_INLINE_VALUE = re.compile(rf"=+>\s*({_NUM})\b")

SUMMARY_LABELS = {
    "custo_horario_equipamentos": "Custo Horário de Equipamentos",
    "custo_horario_mao_de_obra": "Custo Horário da Mão de Obra",
    "custo_total_material": "Custo Total do Material",
    "custo_total_atividades_auxiliares": "Custo Total das Atividades Auxiliares",
    "custo_total_tempos_fixos": "Custo Total dos Tempos Fixos",
    "custo_total_momentos_transporte": "Custo total dos Momentos de Transportes",
    "custo_horario_execucao": "Custo Horário de Execução",
    "fator_influencia_chuva": "Fator de Influencia da Chuva - FIC",
    "custo_fic": "Custo do FIC",
    "producao_equipe": "Produção de Equipe",
    "custo_unitario_execucao": "Custo Unitário de Execução",
    "preco_unitario": "Preço Unitário",
    "valor_com_bdi": "Valor com BDI",
}


SECTION_LABELS = {
    "A": "Equipamentos",
    "B": "Mão de Obra",
    "C": "Material",
    "D": "Atividades Auxiliares",
    "E": "Tempos Fixos",
    "F": "Momento de Transporte",
}

SECTION_ROW_TYPES = {
    "A": "Insumo",
    "B": "Insumo",
    "C": "Insumo",
    "D": "Atividade Auxiliar",
    "E": "Tempo Fixo",
    "F": "Momento de Transporte",
}

SECTION_FIELDS = {
    "A": [
        "codigo", "banco", "descricao", "quant",
        "utilizacao_operativa", "utilizacao_improdutiva",
        "custo_operacional_operativa", "custo_operacional_improdutiva",
        "custo_horario",
    ],
    "B": ["codigo", "banco", "descricao", "quant", "salario_hora", "custo_horario"],
    "C": ["codigo", "banco", "descricao", "quant", "und", "preco_unitario", "custo_horario"],
    "D": ["codigo", "banco", "descricao", "quant", "und", "preco_unitario", "custo_horario"],
    "E": [
        "codigo", "banco", "descricao", "quant", "und",
        "insumo_origem", "codigo_servico", "preco_unitario", "custo_horario",
    ],
    "F": [
        "codigo", "banco", "descricao", "quant", "und",
        "ln", "rp", "p", "custo_horario",
    ],
}


SECTION_DISPLAY_COLUMNS = {
    "A": [
        "Código", "Banco", "Equipamentos", "Quantidade",
        "Utilização Operativa", "Utilização Improdutiva",
        "Custo Operacional Operativa", "Custo Operacional Improdutiva", "Custo Horário",
    ],
    "B": ["Código", "Banco", "Mão de Obra", "Quantidade", "Salário Hora", "Custo Horário"],
    "C": ["Banco", "Código", "Material", "Quantidade", "Unidade", "Preço Unitário", "Custo Horário"],
    "D": ["Banco", "Código", "Atividades Auxiliares", "Quantidade", "Unidade", "Preço Unitário", "Custo Horário"],
    "E": ["Banco", "Insumo", "Tempos Fixos", "Código", "Quantidade", "Unidade", "Preço Unitário", "Custo Horário"],
    "F": ["Banco", "Insumo", "Momento de Transporte", "Quantidade", "Unidade", "DMT (LN/RP/P)", "Custo Horário"],
}


def _build_sicro_payload() -> Dict[str, Any]:
    return {
        "secoes": {sec: [] for sec in SECTION_LABELS},
        "secoes_meta": {
            sec: {
                "label": SECTION_LABELS[sec],
                "tipo_linha": SECTION_ROW_TYPES[sec],
                "campos": list(SECTION_FIELDS[sec]),
                "colunas_pdf": list(SECTION_DISPLAY_COLUMNS[sec]),
            }
            for sec in SECTION_LABELS
        },
        "resumos": {},
        "linhas_brutas": [],
        "profile": sicro_config_payload(),
    }

RAW_NOISE_LINES = {
    "TIPO",
    "HORÁRIO",
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "IMPRODU",
    "TIVA",
    "OPERATIVA IMPRODUTIVA",
    "TÉCNICOS",
    "PARÂMETROS",
    "DIVERSOS",
    "SUPRESSÃO VEGETAL",
    "MOMENTO DE",
    "TRANSPORTE",
    "=>",
}
RAW_NOISE_PREFIXES = (
    "LIVRO SINAPI:",
    "SERT - ",
    "SEDI - ",
    "TIPO ",
    "CUSTOS HORÁRIOS PRODUTIVO",
    "CUSTOS HORARIOS PRODUTIVO",
    "CÓDIGO BANCO DESCRIÇÃO",
    "CODIGO BANCO DESCRICAO",
    "TRANSPORTE, CARGA E",
    "DESCARGA DE MATERIAIS",
)


@dataclass
class SicroBlockData:
    key: str
    item: str = ""
    principal: Optional[LinhaComposicao] = None
    auxiliares: List[LinhaComposicao] = field(default_factory=list)
    insumos: List[LinhaInsumo] = field(default_factory=list)
    detalhes: Dict[str, Any] = field(default_factory=lambda: {"sicro": _build_sicro_payload()})


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", str(line or "").replace("\xa0", " ")).strip()


def _canon_bank(bank: str) -> str:
    return canonical_bank(bank)


def _normalize_code(code: str) -> str:
    return re.sub(r"\s+", " ", str(code or "").replace("\xa0", " ").strip())


def _normalize_ref_key(code: str, bank: str) -> str:
    code = _normalize_code(code)
    bank = _canon_bank(bank)
    return f"{code}|{bank}" if code and bank else ""


def _parse_num(raw: Any) -> Optional[float]:
    return parse_ptbr_number(str(raw)) if raw not in (None, "") else None


def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b in (None, 0):
        return None
    return a / b


def _section_details(section: str, **extra: Any) -> Dict[str, Any]:
    det = {
        "secao": section,
        "secao_label": SECTION_LABELS.get(section, section),
        "tipo_linha": SECTION_ROW_TYPES.get(section, ""),
    }
    det.update({k: v for k, v in extra.items() if v is not None and v != ""})
    return det


def _with_numeric_source(detalhes: Optional[Dict[str, Any]], **values: Any) -> Dict[str, Any]:
    det = dict(detalhes or {})
    ns = dict(det.get("numeric_source") or {})
    for field, raw in values.items():
        raw_text = clean_numeric_text(raw)
        if raw_text:
            ns[field] = numeric_source(raw_text)
    if ns:
        det["numeric_source"] = ns
    return det


def _make_line(*, code: str, bank: str, desc: str, und: str = "", quant: Optional[float] = None,
               valor_unit: Optional[float] = None, total: Optional[float] = None,
               tipo: str = "", detalhes: Optional[Dict[str, Any]] = None) -> LinhaComposicao:
    natureza = ""
    if detalhes and isinstance(detalhes, dict):
        natureza = str(detalhes.get("tipo_linha", "") or "")
    return LinhaComposicao(
        codigo=_normalize_code(code),
        banco=_canon_bank(bank),
        descricao=_clean(desc),
        natureza=natureza,
        tipo=tipo,
        und=und,
        quant=quant,
        valor_unit=valor_unit,
        total=total,
        banco_coluna=_canon_bank(bank),
        detalhes=detalhes or {},
    )


def _as_insumo(line: LinhaComposicao) -> LinhaInsumo:
    return LinhaInsumo(**line.model_dump())


def _principal_from_comp_text(code: str, bank: str, text: str) -> Optional[LinhaComposicao]:
    compact = _clean(text)
    mt = RE_COMP_TAIL.search(compact)
    if not mt:
        return None
    und = mt.group("und")
    quant = _parse_num(mt.group("quant"))
    valor = _parse_num(mt.group("valor"))
    total = _parse_num(mt.group("total"))
    desc = compact[: mt.start()].strip(" -,:;")
    detalhes = _with_numeric_source({}, quant=mt.group("quant"), valor_unit=mt.group("valor"), total=mt.group("total"))
    return _make_line(code=code, bank=bank, desc=desc, und=und, quant=quant, valor_unit=valor, total=total, tipo="", detalhes=detalhes)


def _detect_section(line: str) -> str:
    for code, rgx in RE_SECTION_HEADER.items():
        if rgx.search(line):
            return code
    return ""


def _append_raw_line(block: SicroBlockData, line: str) -> None:
    raw = _clean(line)
    if not raw:
        return
    up = raw.upper()
    if up in RAW_NOISE_LINES:
        return
    if any(up.startswith(prefix) for prefix in RAW_NOISE_PREFIXES):
        return
    if up.startswith("A CÓDIGO BANCO") or up.startswith("A CODIGO BANCO"):
        return
    if up.startswith("B CÓDIGO BANCO") or up.startswith("B CODIGO BANCO"):
        return
    if up.startswith("C BANCO CÓDIGO") or up.startswith("C BANCO CODIGO"):
        return
    if up.startswith("D BANCO CÓDIGO") or up.startswith("D BANCO CODIGO"):
        return
    if up.startswith("E BANCO INSUMO") or up.startswith("F BANCO INSUMO"):
        return
    lines = block.detalhes["sicro"]["linhas_brutas"]
    if not lines or lines[-1] != raw:
        lines.append(raw)


def _capture_summary(block: SicroBlockData, line: str) -> None:
    resumos = block.detalhes["sicro"]["resumos"]
    raw = _clean(line)
    if not raw:
        return

    m_mo = RE_MO_LINE.search(raw)
    if m_mo:
        resumos["mo_sem_ls"] = _parse_num(m_mo.group("mo"))
        resumos["ls"] = _parse_num(m_mo.group("ls"))
        resumos["mo_com_ls"] = _parse_num(m_mo.group("com"))
        return

    m_bdi = re.search(rf"Valor\s+do\s+BDI\s*=+>\s*({_NUM})\s+({_NUM})", raw, flags=re.IGNORECASE)
    if m_bdi:
        resumos["valor_bdi"] = _parse_num(m_bdi.group(1))
        resumos["valor_com_bdi"] = _parse_num(m_bdi.group(2))
        return

    for key, label in SUMMARY_LABELS.items():
        if label.lower() not in raw.lower():
            continue
        inline = re.search(rf"{re.escape(label)}\s*=+>\s*({_NUM})", raw, flags=re.IGNORECASE)
        if inline:
            resumos[key] = _parse_num(inline.group(1))
        else:
            resumos.setdefault("rotulos_detectados", []).append(label)
        return


def _parse_section_line(section: str, line: str) -> tuple[Optional[LinhaComposicao], Optional[str]]:
    if section == "A":
        m = RE_SICRO_A.match(line)
        if not m:
            return None, None
        custo_hor = _parse_num(m.group("custo_hor"))
        det = _with_numeric_source(_section_details(
            "A",
            utilizacao_operativa=_parse_num(m.group("util_op")),
            utilizacao_improdutiva=_parse_num(m.group("util_imp")),
            custo_operacional_operativa=_parse_num(m.group("custo_op")),
            custo_operacional_improdutiva=_parse_num(m.group("custo_imp")),
            custo_horario=custo_hor,
        ), quant=m.group("quant"), valor_unit=m.group("custo_hor"), total=m.group("custo_hor"), utilizacao_operativa=m.group("util_op"), utilizacao_improdutiva=m.group("util_imp"), custo_operacional_operativa=m.group("custo_op"), custo_operacional_improdutiva=m.group("custo_imp"), custo_horario=m.group("custo_hor"))
        line_obj = _make_line(
            code=m.group("code"), bank=m.group("bank"), desc=m.group("desc"),
            quant=_parse_num(m.group("quant")), valor_unit=custo_hor,
            total=custo_hor, tipo="", detalhes=det,
        )
        return line_obj, "insumo"

    if section == "B":
        m = RE_SICRO_B.match(line)
        if not m:
            return None, None
        salario = _parse_num(m.group("salario_hora"))
        custo_hor = _parse_num(m.group("custo_hor"))
        det = _with_numeric_source(_section_details("B", salario_hora=salario, custo_horario=custo_hor), quant=m.group("quant"), valor_unit=m.group("salario_hora"), total=m.group("custo_hor"), salario_hora=m.group("salario_hora"), custo_horario=m.group("custo_hor"))
        line_obj = _make_line(
            code=m.group("code"), bank=m.group("bank"), desc=m.group("desc"),
            quant=_parse_num(m.group("quant")), valor_unit=salario,
            total=custo_hor, tipo="", detalhes=det,
        )
        return line_obj, "insumo"

    if section == "C":
        m = RE_SICRO_C.match(line)
        if not m:
            return None, None
        quant = _parse_num(m.group("quant"))
        custo_hor = _parse_num(m.group("custo_hor"))
        preco_unit = _parse_num(m.group("preco_unit"))
        code, bank, evidence = identify_code_and_bank(m.group("bank"), m.group("code"))
        det = _with_numeric_source(_section_details("C", preco_unitario=preco_unit, custo_horario=custo_hor, code_bank_detection=evidence), quant=m.group("quant"), valor_unit=m.group("preco_unit"), total=m.group("custo_hor"), preco_unitario=m.group("preco_unit"), custo_horario=m.group("custo_hor"))
        line_obj = _make_line(
            code=code, bank=bank, desc=m.group("desc"), und=m.group("und"),
            quant=quant, valor_unit=preco_unit,
            total=custo_hor, tipo="", detalhes=det,
        )
        return line_obj, "insumo"

    if section == "D":
        m = RE_SICRO_D.match(line)
        if not m:
            return None, None
        quant = _parse_num(m.group("quant"))
        custo_hor = _parse_num(m.group("custo_hor"))
        preco_unit = _parse_num(m.group("preco_unit"))
        code, bank, evidence = identify_code_and_bank(m.group("bank"), m.group("code"))
        det = _with_numeric_source(_section_details("D", preco_unitario=preco_unit, custo_horario=custo_hor, code_bank_detection=evidence), quant=m.group("quant"), valor_unit=m.group("preco_unit"), total=m.group("custo_hor"), preco_unitario=m.group("preco_unit"), custo_horario=m.group("custo_hor"))
        line_obj = _make_line(
            code=code, bank=bank, desc=m.group("desc"), und=m.group("und"),
            quant=quant, valor_unit=preco_unit,
            total=custo_hor, tipo="", detalhes=det,
        )
        return line_obj, "auxiliar"

    if section == "E":
        m = RE_SICRO_E.match(line)
        if not m:
            return None, None
        quant = _parse_num(m.group("quant"))
        custo_hor = _parse_num(m.group("custo_hor"))
        preco_unit = _parse_num(m.group("preco_unit"))
        det = _with_numeric_source(_section_details(
            "E",
            codigo_servico=_normalize_code(m.group("code")),
            insumo_origem=_normalize_code(m.group("insumo")),
            preco_unitario=preco_unit,
            custo_horario=custo_hor,
        ), quant=m.group("quant"), valor_unit=m.group("preco_unit"), total=m.group("custo_hor"), preco_unitario=m.group("preco_unit"), custo_horario=m.group("custo_hor"))
        line_obj = _make_line(
            code=m.group("code"), bank=m.group("bank"), desc=m.group("desc"), und=m.group("und"),
            quant=quant, valor_unit=preco_unit,
            total=custo_hor, tipo="", detalhes=det,
        )
        return line_obj, "insumo"

    return None, None


def _try_join_section_lines(lines: List[str], start_idx: int, section: str) -> tuple[str, int]:
    base = _clean(lines[start_idx])
    best = base
    consumed = 0
    for extra in range(1, 4):
        if start_idx + extra >= len(lines):
            break
        candidate = _clean(f"{best} {lines[start_idx + extra]}")
        parsed, _ = _parse_section_line(section, candidate)
        if parsed is not None:
            return candidate, extra
        best = candidate
    return base, consumed


def _extract_price_token(raw: str) -> Optional[float]:
    m = re.search(_PRICE, _clean(raw), flags=re.IGNORECASE)
    return _parse_num(m.group("value")) if m else None


def _numeric_only_value(raw: str) -> Optional[float]:
    txt = _clean(raw)
    if not txt:
        return None
    if re.fullmatch(rf"(?:R\$\s*)?{_NUM}", txt, flags=re.IGNORECASE):
        return _parse_num(txt.replace("R$", "").strip())
    return None


def _contains_label(raw: str, labels: tuple[str, ...]) -> bool:
    up = _clean(raw).upper()
    return any(label in up for label in labels)


def _collect_post_b_summary_numbers(lines: List[str]) -> List[float]:
    last_b_idx = -1
    for idx, line in enumerate(lines):
        if RE_SICRO_B.match(_clean(line)):
            last_b_idx = idx
    if last_b_idx < 0:
        return []

    values: List[float] = []
    for idx in range(last_b_idx + 1, min(len(lines), last_b_idx + 18)):
        raw = _clean(lines[idx])
        if not raw:
            continue
        if RE_ANY_COMP_START.match(raw) or RE_ITEM_HEADER.match(raw):
            break
        if _detect_section(raw) in {"C", "D", "E", "F"}:
            break
        if _contains_label(raw, ("MO SEM LS", "VALOR DO BDI")):
            break
        val = _numeric_only_value(raw)
        if val is not None:
            values.append(val)
    return values


def _capture_split_summary_pairs(block: SicroBlockData) -> None:
    sicro = block.detalhes.get("sicro", {})
    resumos = sicro.setdefault("resumos", {})
    lines = sicro.get("linhas_brutas", []) or []
    for idx, raw in enumerate(lines[:-1]):
        up = _clean(raw).upper()
        nxt = _clean(lines[idx + 1])
        if "VALOR DO BDI" in up and ("valor_bdi" not in resumos or "valor_com_bdi" not in resumos):
            m = re.match(rf"^({_NUM})\s+({_NUM})$", nxt)
            if m:
                resumos.setdefault("valor_bdi", _parse_num(m.group(1)))
                resumos.setdefault("valor_com_bdi", _parse_num(m.group(2)))
        if "MO SEM LS" in up and idx + 2 < len(lines):
            joined = f"{nxt} {_clean(lines[idx+2])}" if nxt == "=>" else nxt
            m = RE_MO_LINE.search(joined)
            if m:
                resumos.setdefault("mo_sem_ls", _parse_num(m.group("mo")))
                resumos.setdefault("ls", _parse_num(m.group("ls")))
                resumos.setdefault("mo_com_ls", _parse_num(m.group("com")))


def _infer_summary_from_numeric_runs(block: SicroBlockData) -> None:
    sicro = block.detalhes.get("sicro", {})
    resumos = sicro.setdefault("resumos", {})
    lines = sicro.get("linhas_brutas", []) or []
    nums = _collect_post_b_summary_numbers(lines)
    if not nums:
        return

    equip = resumos.get("custo_horario_equipamentos")
    mao = resumos.get("custo_horario_mao_de_obra")

    def _pop_if_close(seq: List[float], target: Optional[float]) -> None:
        if seq and target is not None and abs(seq[0] - float(target)) <= max(0.05, 0.005 * max(abs(float(target)), 1.0)):
            seq.pop(0)

    work = list(nums)
    _pop_if_close(work, equip)
    _pop_if_close(work, mao)

    if work and "adc_mao_de_obra_ferramentas" not in resumos and work[0] <= 1.0:
        resumos["adc_mao_de_obra_ferramentas"] = work.pop(0)

    if work and "custo_horario_execucao" not in resumos:
        base = work[0]
        if base >= 1.0:
            resumos["custo_horario_execucao"] = work.pop(0)

    if "custo_horario_execucao" not in resumos and equip is not None and mao is not None:
        adc = float(resumos.get("adc_mao_de_obra_ferramentas") or 0.0)
        resumos["custo_horario_execucao"] = round(float(equip) + float(mao) + adc, 4)

    if len(work) >= 2 and "producao_equipe" not in resumos and "custo_unitario_execucao" not in resumos:
        base_cost = float(resumos.get("custo_horario_execucao") or 0.0) + float(resumos.get("custo_fic") or 0.0)
        a, b = work[-2], work[-1]
        if a > 0 and b > 0 and base_cost > 0 and abs((base_cost / a) - b) <= max(0.25, 0.03 * max(b, 1.0)):
            resumos["producao_equipe"] = a
            resumos["custo_unitario_execucao"] = b
            work = work[:-2]

    if len(work) >= 2 and "fator_influencia_chuva" not in resumos and "custo_fic" not in resumos:
        a, b = work[0], work[1]
        if a <= 1.0 and b >= 0:
            resumos["fator_influencia_chuva"] = a
            resumos["custo_fic"] = b
            work = work[2:]

    if "custo_fic" not in resumos and "fator_influencia_chuva" in resumos and "custo_horario_execucao" in resumos:
        resumos["custo_fic"] = round(float(resumos["fator_influencia_chuva"]) * float(resumos["custo_horario_execucao"]), 4)

    if "producao_equipe" in resumos and "custo_unitario_execucao" not in resumos and "custo_horario_execucao" in resumos:
        denom = float(resumos["producao_equipe"])
        numer = float(resumos["custo_horario_execucao"]) + float(resumos.get("custo_fic") or 0.0)
        if denom:
            resumos["custo_unitario_execucao"] = round(numer / denom, 4)

    if "preco_unitario" not in resumos and getattr(block, "principal", None) is not None and block.principal.valor_unit is not None:
        resumos["preco_unitario"] = float(block.principal.valor_unit)


def _consume_section_f(lines: List[str], start_idx: int) -> Tuple[List[LinhaComposicao], Dict[str, Any], int]:
    parts: List[str] = []
    consumed = 0
    i = start_idx
    while i < len(lines) and consumed < 3 and len(parts) < 3:
        cur = _clean(lines[i])
        if cur:
            parts.append(cur)
        if len(parts) >= 3 and RE_SICRO_F_BASE.match(" ".join(parts[-3:])):
            break
        if RE_SICRO_F_BASE.match(" ".join(parts)):
            break
        i += 1
        consumed += 1
    base_text = " ".join(parts)
    m = RE_SICRO_F_BASE.match(base_text)
    if not m:
        return [], {}, 0

    bank = m.group("bank")
    insumo = m.group("insumo")
    desc = m.group("desc")
    quant = _parse_num(m.group("quant"))
    und = m.group("und")
    branches: Dict[str, Dict[str, Any]] = {
        "LN": {"codigo": _normalize_code(m.group("code_ln"))},
        "RP": {},
        "P": {},
    }
    idx = start_idx + len(parts)
    branch_order = ["LN", "RP", "P"]
    branch_pos = 0
    final_cost: Optional[float] = None

    while idx < len(lines):
        raw = _clean(lines[idx])
        if not raw:
            idx += 1
            continue
        if RE_ITEM_HEADER.match(raw) or RE_ANY_COMP_START.match(raw) or _detect_section(raw):
            break
        if raw.upper().startswith("MO SEM LS") or "VALOR DO BDI" in raw.upper() or "CUSTO HORÁRIO" in raw.upper() or "CUSTO HORARIO" in raw.upper():
            break
        if branch_pos >= 1 and branch_pos < len(branch_order) and re.fullmatch(r"\d+", raw):
            branch = branches[branch_order[branch_pos]]
            if "codigo" not in branch:
                branch["codigo"] = _normalize_code(raw)
                idx += 1
                continue
        if branch_pos < len(branch_order):
            branch = branches[branch_order[branch_pos]]
            if "quantidade_dmt" not in branch:
                qtd = _parse_num(raw)
                if qtd is not None:
                    branch["quantidade_dmt"] = qtd
                    idx += 1
                    continue
            if "preco_unitario_dmt" not in branch:
                price = _extract_price_token(raw)
                if price is not None:
                    branch["preco_unitario_dmt"] = price
                    if branch_order[branch_pos] == "P":
                        branch_pos = len(branch_order)
                    else:
                        branch_pos += 1
                    idx += 1
                    continue
        maybe_cost = _parse_num(raw)
        if maybe_cost is not None:
            final_cost = maybe_cost
            idx += 1
            break
        idx += 1

    detalhe_row = _with_numeric_source(_section_details(
        "F",
        insumo_origem=_normalize_code(insumo),
        quantidade_principal=quant,
        unidade_principal=und,
        custo_horario=final_cost,
        ln=branches.get("LN", {}),
        rp=branches.get("RP", {}),
        p=branches.get("P", {}),
        dmt={"LN": branches.get("LN", {}), "RP": branches.get("RP", {}), "P": branches.get("P", {})},
    ), quant=m.group("quant"), total=str(final_cost).replace(".", ",") if final_cost is not None else "")
    row = _make_line(
        code=insumo,
        bank=bank,
        desc=desc,
        und=und,
        quant=quant,
        valor_unit=None,
        total=final_cost,
        tipo="",
        detalhes=detalhe_row,
    )

    aux_rows: List[LinhaComposicao] = []
    for branch_name, info in branches.items():
        code = _normalize_code(str(info.get("codigo") or ""))
        if not code:
            continue
        det = _section_details(
            "F",
            ramo=branch_name,
            insumo_origem=_normalize_code(insumo),
            quantidade_dmt=info.get("quantidade_dmt"),
            preco_unitario_dmt=info.get("preco_unitario_dmt"),
            custo_horario_referencia=final_cost,
            dmt_ramo=branch_name,
        )
        aux_rows.append(
            _make_line(
                code=code,
                bank=bank,
                desc=desc,
                und=und,
                quant=quant,
                valor_unit=info.get("preco_unitario_dmt"),
                total=final_cost,
                tipo="",
                detalhes=det,
            )
        )

    return aux_rows, row.model_dump(), max(idx - start_idx, len(parts))


def _finalize_block(block: SicroBlockData) -> None:
    sicro = block.detalhes.get("sicro", {})
    secoes = sicro.get("secoes", {})
    resumos = sicro.setdefault("resumos", {})

    def _sum_section(sec: str) -> Optional[float]:
        vals: List[float] = []
        for row in secoes.get(sec, []) or []:
            det = dict(row.get("detalhes") or {})
            val = det.get("custo_horario")
            if val is None:
                val = row.get("total")
            if isinstance(val, (int, float)):
                vals.append(float(val))
        return round(sum(vals), 4) if vals else None

    derived = {
        "custo_horario_equipamentos": _sum_section("A"),
        "custo_horario_mao_de_obra": _sum_section("B"),
        "custo_total_material": _sum_section("C"),
        "custo_total_atividades_auxiliares": _sum_section("D"),
        "custo_total_tempos_fixos": _sum_section("E"),
        "custo_total_momentos_transporte": _sum_section("F"),
    }
    for key, value in derived.items():
        if value is not None and key not in resumos:
            resumos[key] = value

    _capture_split_summary_pairs(block)
    _infer_summary_from_numeric_runs(block)

    if "mo_com_ls" in resumos and "custo_horario_equipamentos" in resumos and "custo_horario_execucao" not in resumos:
        resumos["custo_horario_execucao"] = round(float(resumos["mo_com_ls"]) + float(resumos["custo_horario_equipamentos"]), 4)

    rotulos = list(dict.fromkeys(resumos.get("rotulos_detectados", []) or []))
    if rotulos:
        resumos["rotulos_detectados"] = rotulos
    else:
        resumos.pop("rotulos_detectados", None)

    sicro["linhas_brutas"] = list(dict.fromkeys(sicro.get("linhas_brutas", []) or []))
    if not sicro.get("linhas_brutas"):
        sicro.pop("linhas_brutas", None)
    else:
        # Mantemos internamente durante a finalização apenas o necessário para inferência;
        # não expomos esse bloco no payload final porque ele polui e duplica informação.
        sicro.pop("linhas_brutas", None)


def extract_sicro_blocks_from_text(
    *,
    pdf_bytes: bytes,
    start_1based: int,
    end_1based: int,
    item_refs: Optional[List[dict]] = None,
    page_texts: Optional[List[str]] = None,
    page_numbers: Optional[List[int]] = None,
    section_templates: Optional[Dict[str, Dict[str, Any]]] = None,
    page_section_hints: Optional[Dict[int, List[str]]] = None,
) -> Dict[str, SicroBlockData]:
    refs_by_key = {str(r.get("ref_id", "")): r for r in (item_refs or []) if str(r.get("ref_id", ""))}
    blocks: Dict[str, SicroBlockData] = {}
    pending_item = ""
    current: Optional[SicroBlockData] = None
    current_section = ""

    if page_texts is None:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        max_page = min(end_1based, len(reader.pages))
        page_numbers = list(range(max(1, start_1based), max_page + 1))
        page_texts = [reader.pages[page_no - 1].extract_text() or "" for page_no in page_numbers]
    elif page_numbers is None:
        page_numbers = list(range(start_1based, start_1based + len(page_texts)))

    def ensure_block(principal: LinhaComposicao, fallback_item: str) -> SicroBlockData:
        key = _normalize_ref_key(principal.codigo, principal.banco)
        ref = refs_by_key.get(key)
        item_value = str(ref.get("item") or "") if ref is not None else (fallback_item or "")
        block = blocks.get(key)
        if not principal.tipo:
            principal.tipo = "Composição"
        if block is None:
            block = SicroBlockData(key=key, item=item_value, principal=principal)
            blocks[key] = block
        else:
            block.principal = block.principal or principal
            if not block.item:
                block.item = item_value
        return block

    if section_templates is None:
        section_templates = {}
    if page_section_hints is None:
        page_section_hints = {}
    resolved_page_numbers = list(page_numbers or [])
    for offset, page_text in enumerate(page_texts):
        page_no = resolved_page_numbers[offset] if offset < len(resolved_page_numbers) else start_1based + offset
        lines = [_clean(x) for x in page_text.splitlines() if _clean(x)]
        hinted_sections = list(page_section_hints.get(page_no) or [])
        for hinted in hinted_sections:
            section_templates.setdefault(hinted, {"section": hinted, "first_page": page_no, "template_source": "learned_first_occurrence"})
        i = 0
        while i < len(lines):
            line = lines[i]

            m_item = RE_ITEM_HEADER.match(line)
            if m_item:
                pending_item = m_item.group("item")
                current = None
                current_section = ""
                i += 1
                continue

            m_comp = RE_COMP_START.match(line)
            if m_comp:
                code = _normalize_code(m_comp.group("code"))
                bank = _canon_bank(m_comp.group("bank"))
                fragments = [m_comp.group("rest")]
                j = i + 1
                if not RE_COMP_TAIL.search(" ".join(fragments)):
                    while j < len(lines):
                        nxt = lines[j]
                        if RE_ANY_COMP_START.match(nxt) or RE_ITEM_HEADER.match(nxt):
                            break
                        fragments.append(nxt)
                        if RE_COMP_TAIL.search(" ".join(fragments)):
                            break
                        j += 1
                principal = _principal_from_comp_text(code, bank, " ".join(fragments))
                if principal is not None and _canon_bank(principal.banco) == "SICRO":
                    current = ensure_block(principal, pending_item)
                    current_section = ""
                    _append_raw_line(current, line)
                    i = j + 1
                    continue
                current = None
                current_section = ""
                i += 1
                continue

            if current is not None and RE_ANY_COMP_START.match(line):
                current = None
                current_section = ""
                i += 1
                continue

            if current is None:
                i += 1
                continue

            _append_raw_line(current, line)
            section = _detect_section(line)
            if section:
                current_section = section
                section_templates.setdefault(section, {"section": section, "first_page": page_no, "template_source": "learned_first_occurrence"})
                i += 1
                continue
            if not current_section and len(hinted_sections) == 1 and hinted_sections[0] in section_templates:
                current_section = hinted_sections[0]
            if not current_section:
                if re.match(r"^Insumo\s+E\d+\s+SICRO", line, flags=re.IGNORECASE):
                    current_section = "A"
                elif re.match(r"^Insumo\s+P\d+\s+SICRO", line, flags=re.IGNORECASE):
                    current_section = "B"
                elif re.match(r"^Insumo\s+SICRO\s+M\d+", line, flags=re.IGNORECASE):
                    current_section = "C"
                elif re.match(r"^(Atividade\s+Auxiliar|Composi(?:ç[aã]o|cao)\s+Auxiliar|Auxiliar)\s+SICRO", line, flags=re.IGNORECASE):
                    current_section = "D"
                elif re.match(r"^(Momento\s+de|Transporte\s+SICRO|SICRO\s*M\d+)", line, flags=re.IGNORECASE):
                    current_section = "F"
                if current_section:
                    section_templates.setdefault(current_section, {"section": current_section, "first_page": page_no, "template_source": "learned_first_occurrence"})

            if current_section == "F" and (line.upper().startswith("MOMENTO DE") or re.match(r"^(?:Transporte\s+)?SICRO\s*3?\s+M\d+", line, flags=re.IGNORECASE)):
                aux_rows, f_row_dict, consumed = _consume_section_f(lines, i)
                if consumed:
                    current.detalhes["sicro"]["secoes"]["F"].append(f_row_dict)
                    for aux in aux_rows:
                        current.auxiliares.append(aux)
                    i += consumed
                    continue

            parsed, target = _parse_section_line(current_section, line)
            consumed_extra = 0
            if parsed is None and current_section:
                joined_line, consumed_extra = _try_join_section_lines(lines, i, current_section)
                if consumed_extra:
                    parsed, target = _parse_section_line(current_section, joined_line)
                    if parsed is not None:
                        _append_raw_line(current, joined_line)
            if parsed is not None:
                current.detalhes["sicro"]["secoes"][current_section].append(parsed.model_dump())
                if target == "auxiliar":
                    current.auxiliares.append(parsed)
                else:
                    current.insumos.append(_as_insumo(parsed))
                i += 1 + consumed_extra
                continue

            _capture_summary(current, line)
            i += 1

    for block in blocks.values():
        _finalize_block(block)
    return blocks


def _sanitize_sicro_materialized_payload(sicro: Dict[str, Any]) -> Dict[str, Any]:
    clean = dict(sicro or {})
    clean.pop("linhas_brutas", None)
    clean.pop("secoes_meta", None)
    clean.pop("resumos", None)
    clean.pop("profile", None)
    secoes = clean.get("secoes")
    if isinstance(secoes, dict):
        normalized: Dict[str, Any] = {}
        for sec, rows in secoes.items():
            if not isinstance(rows, list):
                continue
            new_rows: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_clean = apply_numeric_sources_to_row(dict(row))
                detalhes = row_clean.get("detalhes")
                if isinstance(detalhes, dict):
                    det = dict(detalhes)
                    det.pop("secao_label", None)
                    det.pop("tipo_linha", None)
                    det.pop("numeric_source", None)
                    det.pop("code_bank_detection", None)
                    row_clean["detalhes"] = det
                new_rows.append(row_clean)
            normalized[sec] = new_rows
        clean["secoes"] = normalized
    return clean


def materialize_sicro_block(block: SicroBlockData) -> BlocoComposicao:
    detalhes = dict(block.detalhes or {})
    sicro = detalhes.get("sicro")
    if isinstance(sicro, dict):
        detalhes["sicro"] = _sanitize_sicro_materialized_payload(sicro)
    return BlocoComposicao(
        item=block.item,
        principal=block.principal,
        composicoes_auxiliares=block.auxiliares,
        insumos=[],
        detalhes=detalhes,
    )


# Compatibilidade interna
extract_sicro_blocks = extract_sicro_blocks_from_text
