from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKERS = [
    ROOT / "parser_browser/browser/pyodide/pyodide-parser-worker.js",
    ROOT / "parser_browser/browser/demo/pyodide/pyodide-parser-worker.js",
]


def test_workers_have_batched_targeted_recovery_helpers():
    for worker in WORKERS:
        text = worker.read_text(encoding="utf-8")
        assert "function chunkPagesForTargetedRecovery" in text
        assert "function filterTargetsByPages" in text
        assert "function resolveTargetedRecoveryBatchSize" in text
        assert "targeted-recovery-batch-started" in text
        assert "targeted-recovery-batch-finished" in text
        assert "targeted-recovery-batch-failed-nonfatal" in text
        assert "targeted_recovery_batched: true" in text


def test_workers_do_not_build_one_unbounded_targeted_recovery_pdf():
    for worker in WORKERS:
        text = worker.read_text(encoding="utf-8")
        assert "buildSelectedPagesPdfBufferFromPath(pdfPath, pages, options = {})" in text
        assert "const payload = { pages: uniquePages, max_pages: maxPages" in text
        assert "pageBatches = chunkPagesForTargetedRecovery" in text
        assert "mergedRecovery.patches.push(...patches)" in text


def test_batching_has_nonfatal_error_path_instead_of_throwing_flow():
    for worker in WORKERS:
        text = worker.read_text(encoding="utf-8")
        assert "status: 'error_nonfatal'" in text
        assert "buildTargetedRecoveryUnresolved(batchTargets" in text
        assert "return { final: finalPreliminary, compositions: compositionsStage, recovery: mergedRecovery }" in text
