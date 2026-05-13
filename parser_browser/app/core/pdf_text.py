import io
from typing import List

try:  # pragma: no cover - dependência opcional no browser
    import pdfplumber  # type: ignore
except Exception:  # pragma: no cover
    pdfplumber = None

from pypdf import PdfReader

from app.core.pdf_session import PdfDocumentSession



def extract_pages_text(
    pdf_bytes: bytes,
    start_1based: int,
    end_1based: int,
    *,
    pdf_session: PdfDocumentSession | None = None,
    engine: str = "auto",
) -> List[str]:
    """Extrai texto página a página no intervalo [start,end] (1-based)."""
    if start_1based < 1 or end_1based < 1:
        raise ValueError("Páginas devem ser 1-based e >= 1")
    if pdf_session is not None:
        return pdf_session.get_page_texts(start_1based, end_1based, engine=engine)

    resolved_engine = engine
    if resolved_engine == 'auto':
        resolved_engine = 'plumber' if pdfplumber is not None else 'pypdf'

    if resolved_engine == 'plumber' and pdfplumber is not None:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            n = len(pdf.pages)
            if end_1based > n:
                raise ValueError(f"PDF tem {n} páginas, mas você pediu até {end_1based}")
            return [pdf.pages[idx].extract_text() or "" for idx in range(start_1based - 1, end_1based)]

    reader = PdfReader(io.BytesIO(pdf_bytes))
    n = len(reader.pages)
    if end_1based > n:
        raise ValueError(f"PDF tem {n} páginas, mas você pediu até {end_1based}")
    return [reader.pages[idx].extract_text() or "" for idx in range(start_1based - 1, end_1based)]



def normalize_lines(text: str) -> List[str]:
    """Normaliza espaços e remove linhas vazias."""
    lines = []
    for raw in text.splitlines():
        s = " ".join(raw.strip().split())
        if s:
            lines.append(s)
    return lines
