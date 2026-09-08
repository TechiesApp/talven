"""Versioned public task instructions. Acceptance implementation is separate."""

from . import CORPUS_VERSION
from .borrowing_tasks import BORROWING_TASKS


TASKS = {
    "move-scalar": {
        "source": "examples/invalid/moved.tal",
        "instruction": "Repair main so it returns the original scalar value, 7, after a real record move. "
                       "Keep Item.value:i32, original initialized to Item { value: 7 }, and the direct "
                       "let transferred = original transfer in main. Before the move, save original.value "
                       "in a scalar binding; return that binding after the move. Do not replace the move "
                       "with a borrow, reconstruct the record, or hardcode the return value.",
    },
    "strict-type": {
        "source": "examples/invalid/type.tal",
        "instruction": "Repair the strict type error. Keep main() -> i32, the count binding explicitly "
                       "typed i32, and return count. Initialize count with an integer expression so main "
                       "returns exactly 1. Do not remove or bypass count.",
    },
    "rename-field": {
        "source": "examples/vectors.tal",
        "instruction": "Rename Vec2.x to horizontal at its declaration and all field reads and "
                       "constructors; keep y:i32 and horizontal:i32. Preserve dot(a: Vec2, b: Vec2) -> i32 "
                       "as a general dot product and preserve main's executable check that dot((2,3),(4,5)) "
                       "is 23, returning 0 only when correct. No x field may remain.",
    },
    "squared-length": {
        "source": "examples/vectors.tal",
        "instruction": "Add squared_length(value: Vec2) -> i32 computing x*x + y*y for arbitrary "
                       "representable inputs, preserving Vec2 and dot. Keep the existing dot check in "
                       "main and add an executable check that squared_length(Vec2 { x: 3, y: 4 }) is 25. "
                       "Return 0 only when both checks pass, nonzero otherwise. The independent native "
                       "verifier will exercise squared_length on multiple positive, negative and zero vectors.",
    },
}


CORPORA = {
    CORPUS_VERSION: TASKS,
    "m1c-borrowing-tasks-v1": BORROWING_TASKS,
}


def get_tasks(corpus_version=CORPUS_VERSION):
    if not isinstance(corpus_version, str) or corpus_version not in CORPORA:
        raise ValueError(f"Unsupported evaluation corpus: {corpus_version!r}")
    return CORPORA[corpus_version]
