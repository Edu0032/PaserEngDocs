from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

TEXT_SUFFIXES = {'.py', '.js', '.ts', '.json', '.md', '.yaml', '.yml', '.txt', '.html'}
SKIP_DIRS = {'__pycache__', '.git', 'release'}
DANGEROUS_REGEX_SNIPPETS = [
    r'\bENGENHEIR[OA]\b',
    r'\bARQUITET[OA]\b',
]


def iter_text_files(root: Path) -> Iterable[Path]:
    for p in root.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


def scan_project(root: str | Path = '.') -> List[dict]:
    root = Path(root)
    findings: List[dict] = []
    for path in iter_text_files(root):
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        rel = str(path.relative_to(root))
        for idx, ch in enumerate(text):
            if ord(ch) < 32 and ch not in '\n\r\t':
                findings.append({'file': rel, 'code': 'invisible_control_character', 'offset': idx, 'ord': ord(ch)})
                break
        app_file = rel.startswith('parser_browser/app/') or rel.startswith('api_docling/app/')
        if app_file:
            for snippet in DANGEROUS_REGEX_SNIPPETS:
                if snippet in text:
                    findings.append({'file': rel, 'code': 'dangerous_document_specific_regex', 'snippet': snippet})
    return findings


if __name__ == '__main__':
    import json, sys
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('.')
    findings = scan_project(root)
    print(json.dumps({'ok': not findings, 'findings': findings}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if findings else 0)
