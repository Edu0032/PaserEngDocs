from __future__ import annotations

import re
from typing import Dict, List

# Generic SICRO section boundary patterns used only as page/layout signals by
# the legacy SINAPI-like parser. Final SICRO extraction remains exclusively in
# app.sicro_only (motor SICRO v20) and the non-destructive native bridge.
SICRO_SECTION_REGEXES: Dict[str, List[re.Pattern[str]]] = {
    "A": [re.compile(r"^A\b", re.IGNORECASE), re.compile(r"^Insumo\s+E\d+\s+(?:SICRO\s*3?|DNIT)", re.IGNORECASE)],
    "B": [re.compile(r"^B\b", re.IGNORECASE), re.compile(r"^Insumo\s+P\d+\s+(?:SICRO\s*3?|DNIT)", re.IGNORECASE)],
    "C": [re.compile(r"^C\b", re.IGNORECASE), re.compile(r"^Insumo\s+(?:SICRO\s*3?|DNIT)\s+M\d+", re.IGNORECASE)],
    "D": [re.compile(r"^D\b", re.IGNORECASE), re.compile(r"^(?:Atividade\s+Auxiliar|Composi(?:ç[aã]o|cao)\s+Auxiliar|Auxiliar)\s+(?:SICRO\s*3?|DNIT)", re.IGNORECASE)],
    "E": [re.compile(r"^E\b", re.IGNORECASE), re.compile(r"^Tempo\s+Fixo\s+(?:SICRO\s*3?|DNIT)", re.IGNORECASE)],
    "F": [re.compile(r"^F\b", re.IGNORECASE), re.compile(r"^(?:Momento\s+de\s+Transporte|Transporte\s+(?:SICRO\s*3?|DNIT)|(?:SICRO\s*3?|DNIT)\s+M\d+)", re.IGNORECASE)],
}
