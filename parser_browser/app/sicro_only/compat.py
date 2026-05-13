from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict

from .sicro_geometry import smoke_test_pymupdf_pdf_bytes


def local_pymupdf_smoke(pdf_path: str | Path, sample_page: int = 1) -> Dict[str, Any]:
    try:
        result = smoke_test_pymupdf_pdf_bytes(pdf_path, sample_page=sample_page)
        result["environment"] = "cpython"
        return result
    except Exception as exc:  # pragma: no cover - useful for CLI report
        return {"ok": False, "environment": "cpython", "error": repr(exc)}


def inspect_pyodide_npm_lock(pyodide_dir: str | Path) -> Dict[str, Any]:
    lock_path = Path(pyodide_dir) / "pyodide-lock.json"
    if not lock_path.exists():
        return {"ok": False, "error": f"pyodide-lock.json não encontrado em {lock_path}"}
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    pkg = (lock.get("packages") or {}).get("pymupdf")
    if not pkg:
        return {"ok": False, "error": "pymupdf não está listado no pyodide-lock.json"}
    imports = set(pkg.get("imports") or [])
    return {
        "ok": "pymupdf" in imports and "fitz" in imports,
        "package_name": pkg.get("name"),
        "version": pkg.get("version"),
        "file_name": pkg.get("file_name"),
        "imports": sorted(imports),
        "sha256": pkg.get("sha256"),
        "source": str(lock_path),
    }


def run_node_pyodide_core_smoke(script_path: str | Path, timeout_s: int = 120) -> Dict[str, Any]:
    script = Path(script_path)
    if not script.exists():
        return {"ok": False, "error": f"script não encontrado: {script}"}
    try:
        proc = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=timeout_s)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
        }
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}
