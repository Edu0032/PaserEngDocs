from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class PerformanceTracker:
    """Rastreador simples de tempos por etapa para o parser.

    Mantém a instrumentação barata e serial, sem introduzir dependências.
    """

    started_at: float = field(default_factory=time.perf_counter)
    _last_mark: float = field(default_factory=time.perf_counter)
    _stages: Dict[str, float] = field(default_factory=dict)
    _metrics: Dict[str, Any] = field(default_factory=dict)

    def stage(self, name: str) -> float:
        now = time.perf_counter()
        elapsed_ms = round((now - self._last_mark) * 1000, 3)
        self._last_mark = now
        if name:
            self._stages[name] = elapsed_ms
        return elapsed_ms

    def metric(self, name: str, value: Any) -> Any:
        if name:
            self._metrics[name] = value
        return value

    def export(self) -> Dict[str, Any]:
        total_ms = round((time.perf_counter() - self.started_at) * 1000, 3)
        return {
            'total_parser_ms': total_ms,
            'stages_ms': dict(self._stages),
            'metrics': dict(self._metrics),
        }
