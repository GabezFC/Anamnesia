"""R4: routing task dataset (Task, loader, balanced splitter)."""
from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

DIFFICULTIES = ("easy", "medium", "hard")
KINDS = ("memory_qa", "extraction", "code", "summarization", "open")
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "benchmark" / "routing_tasks.json"


@dataclass(frozen=True)
class Task:
    id: str
    kind: str
    query: str
    difficulty_label: str
    ground_truth: dict[str, Any] = field(default_factory=dict)
    verifier: dict[str, Any] = field(default_factory=dict)
    risk: str = "low"

    def __post_init__(self):
        if self.difficulty_label not in DIFFICULTIES:
            raise ValueError(f"bad difficulty {self.difficulty_label!r}")
        if self.kind not in KINDS:
            raise ValueError(f"bad kind {self.kind!r}")

    def to_dict(self) -> dict:
        return asdict(self)


def load_tasks(path: str | Path = DEFAULT_PATH) -> list[Task]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Task(**t) for t in data["tasks"]]


def split_tasks(tasks: list[Task], seed: int = 42, calibration_frac: float = 0.5) -> tuple[list[Task], list[Task]]:
    """Stratified split by difficulty (calibration/eval): each stratum split with the same fraction. Deterministic."""
    rng = random.Random(seed)
    by: dict[str, list[Task]] = defaultdict(list)
    for t in sorted(tasks, key=lambda t: t.id):
        by[t.difficulty_label].append(t)
    cal: list[Task] = []
    ev: list[Task] = []
    for d in DIFFICULTIES:
        items = by.get(d, [])
        rng.shuffle(items)
        k = round(len(items) * calibration_frac)
        cal += items[:k]
        ev += items[k:]
    return sorted(cal, key=lambda t: t.id), sorted(ev, key=lambda t: t.id)
