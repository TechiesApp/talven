"""Public M1c borrowing repair tasks, separate from the original corpus."""

_BOUNDARY = (
    " Keep Counter with exactly value:i32, all existing helper signatures/bodies, and main's "
    "example values and executable checks unchanged (formatting/comments may change). "
    "Do not add records or functions. Keep exercise(c: &mut Counter, delta: i32) -> i32; "
    "its body must be straight-line let bindings/call statements followed by one final return, "
    "without record construction or direct field assignment. Operate on c's original pointee, "
    "using the required helpers exactly as described. Independent native checks use multiple "
    "positive, negative, and zero inputs and check the resulting record and helper call order."
)

BORROWING_TASKS = {
    "borrow-overlap": {
        "source": "experiments/corpora/borrowing-v1/overlap.tal",
        "instruction": (
            "Repair the overlapping exclusive/shared loans in exercise. Read c once before "
            "calling with_before once with an exclusive reborrow, that scalar snapshot, and delta. "
            "with_before calls add once. Return old_value*100 + updated_value; c must increase "
            "by delta exactly once. The required helper order is read, with_before, add."
        ) + _BOUNDARY,
    },
    "borrow-permission": {
        "source": "experiments/corpora/borrowing-v1/permission.tal",
        "instruction": (
            "Repair missing write permissions: make exercise's c parameter exclusive and main's "
            "counter owner mutable. These are the only exceptions to preserving signatures/main. "
            "In exercise call add once with delta, then read once; return the updated value. "
            "c must increase by delta exactly once. The required helper order is add, read."
        ) + _BOUNDARY,
    },
    "borrow-reborrow": {
        "source": "experiments/corpora/borrowing-v1/reborrow.tal",
        "instruction": (
            "Repair missing explicit reborrows in exercise. Read c once, add delta once through "
            "an exclusive reborrow, then read c once again. Return old_value*100 + updated_value; "
            "c must increase by delta exactly once. The required helper order is read, add, read."
        ) + _BOUNDARY,
    },
    "borrow-order": {
        "source": "experiments/corpora/borrowing-v1/order.tal",
        "instruction": (
            "Repair exercise's evaluation order. Snapshot c with read once before either mutation, "
            "then call add twice with delta, retaining each returned value in source order. "
            "Return old_value*10000 + first_updated_value*100 + second_updated_value; "
            "c must increase by delta exactly twice. The required helper order is read, add, add."
        ) + _BOUNDARY,
    },
}
