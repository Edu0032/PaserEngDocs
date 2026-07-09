from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

TEXT_SUFFIXES = {'.py', '.js', '.ts', '.json', '.md', '.yaml', '.yml', '.txt', '.html'}
BAD_DOCUMENT_SPECIFIC_EXAMPLES = [
    '74209/001', '00006079', 'COMP.JCO.3', 'CP - 120', 'ANP 01', '5503041', '2003373'
]
ACTIVE_CONFIG_PATHS = [
    'parser_browser/db', 'api_docling/db', 'parser_browser/app', 'api_docling/app',
    'parser_browser/browser/demo/index.html', 'examples', 'docs/lovable_contracts'
]
SKIP_PARTS = {'.git', '__pycache__', '.pytest_cache', 'archive'}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _iter_text(root: Path, base: Path) -> Iterable[Path]:
    if root.is_file():
        yield root; return
    if not root.exists():
        return
    for p in root.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = p.relative_to(base)
        if any(part in SKIP_PARTS for part in rel.parts):
            continue
        yield p


def scan(root: str | Path = '.') -> Dict[str, Any]:
    base = Path(root)
    findings: List[Dict[str, Any]] = []

    # No cache/build junk in release tree.
    for junk in ['.pytest_cache', '__pycache__']:
        for p in base.rglob(junk):
            findings.append({'code': 'release_junk_directory', 'path': str(p.relative_to(base))})

    # Active config/docs/code should not carry real-document examples in global rules.
    for rel in ACTIVE_CONFIG_PATHS:
        start = base / rel
        for p in _iter_text(start, base):
            try:
                text = p.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue
            relp = str(p.relative_to(base))
            for token in BAD_DOCUMENT_SPECIFIC_EXAMPLES:
                if token in text:
                    findings.append({'code': 'document_specific_example_in_active_surface', 'path': relp, 'token': token})

    # Manifest SHA must match the embedded Pyodide source archive.
    for manifest in [
        base / 'parser_browser/browser/pyodide/manifest.json',
        base / 'parser_browser/browser/demo/pyodide/manifest.json',
    ]:
        if not manifest.exists():
            findings.append({'code': 'manifest_missing', 'path': str(manifest.relative_to(base))})
            continue
        try:
            data = json.loads(manifest.read_text())
        except Exception as exc:
            findings.append({'code': 'manifest_invalid_json', 'path': str(manifest.relative_to(base)), 'error': str(exc)})
            continue
        src = manifest.parent / str(data.get('sourceArchive') or 'api_pdf_pyodide_src.zip')
        declared = str(data.get('sourceZipSha256') or '')
        if not src.exists():
            findings.append({'code': 'source_archive_missing', 'path': str(src.relative_to(base))})
        else:
            actual = _sha256(src)
            if declared != actual:
                findings.append({'code': 'manifest_source_sha_mismatch', 'manifest': str(manifest.relative_to(base)), 'archive': str(src.relative_to(base)), 'declared': declared, 'actual': actual})

    # Current docs must exist and README must not advertise old release as current.
    version_file = base / 'parser_browser/app/config/version.py'
    current = ''
    if version_file.exists():
        m = re.search(r"CURRENT_RELEASE\s*=\s*['\"]([^'\"]+)", version_file.read_text())
        current = m.group(1) if m else ''
    if current:
        mver = re.match(r'v(\d+)\.(\d+)\.(\d+)', current)
        version_suffix = f"V{mver.group(1)}_{mver.group(2)}_{mver.group(3)}" if mver else 'CURRENT'
        required_docs = [
            'README.md',
            f'docs/CHANGELOG_{version_suffix}.md',
            f'docs/TEST_REPORT_{version_suffix}.md',
            'docs/lovable_contracts/13_CORRECTION_DOCUMENT_UI_REVIEW_CONTRACT.md',
        ]
        for doc in required_docs:
            path = base / doc
            if not path.exists():
                findings.append({'code': 'current_release_doc_missing', 'path': doc})
            elif current not in path.read_text(errors='ignore') and doc != 'docs/lovable_contracts/13_CORRECTION_DOCUMENT_UI_REVIEW_CONTRACT.md':
                findings.append({'code': 'current_release_doc_not_stamped', 'path': doc, 'expected': current})
        readme = base / 'README.md'
        if readme.exists() and re.search(r'ParserOrca — v(?!61\.0\.75)', readme.read_text(errors='ignore')):
            findings.append({'code': 'readme_header_not_current_release', 'path': 'README.md', 'expected': current})

    return {'ok': not findings, 'finding_count': len(findings), 'findings': findings}


if __name__ == '__main__':
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('.')
    result = scan(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['ok'] else 1)
