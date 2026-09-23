"""Public instructions for the hard corpus, separate from its acceptance rules.

Each task states the required behavior over its full input domain. The tasks
are chosen so that habits from other languages (loops, shadowing, `else if`,
mutable scalars, implicit reborrows, reading a moved value, unchecked
overflow) produce programs Talven rejects or that trap at runtime.
"""

HARD_CORPUS = "m1-hard-tasks-v1"
_BASE = "experiments/corpora/hard-v1/"
_KEEP_MAIN = " You may change main, but it must still type-check and return i32."

HARD_TASKS = {
    "lcm-no-overflow": {
        "source": _BASE + "lcm.tal",
        "instruction": (
            "Implement gcd(a: i32, b: i32) -> i32 and lcm(a: i32, b: i32) -> i32 for all non-negative inputs. "
            "gcd(a, 0) is a and gcd(0, 0) is 0. lcm(a, b) is 0 when either input is 0, and otherwise the least "
            "common multiple; it must return the correct value for every pair of non-negative inputs whose least "
            "common multiple fits in i32. Keep both signatures." + _KEEP_MAIN
        ),
    },
    "digit-sum": {
        "source": _BASE + "digits.tal",
        "instruction": (
            "Implement digit_sum(n: i32) -> i32, returning the sum of the decimal digits of n's magnitude, for "
            "every i32 value n. For example digit_sum(-123) is 6 and digit_sum(0) is 0. Keep the signature."
            + _KEEP_MAIN
        ),
    },
    "pow-mod": {
        "source": _BASE + "powmod.tal",
        "instruction": (
            "Implement pow_mod(base: i32, exp: i32, m: i32) -> i32, returning base raised to exp, modulo m, for "
            "all 0 <= base, 0 <= exp, and 1 <= m <= 46340. base to the power 0 is 1, so pow_mod(b, 0, 1) is 0. It "
            "must be correct and finish quickly for every exponent up to 2147483647. Keep the signature."
            + _KEEP_MAIN
        ),
    },
    "grade-bands": {
        "source": _BASE + "bands.tal",
        "instruction": (
            "Implement band(score: i32) -> i32 for every i32 score: return -1 if score is below 0 or above 100; "
            "4 for 90 to 100; 3 for 80 to 89; 2 for 70 to 79; 1 for 60 to 69; and 0 for 0 to 59 (all ranges "
            "inclusive). Keep the signature." + _KEEP_MAIN
        ),
    },
    "recursive-reborrow": {
        "source": _BASE + "reborrow.tal",
        "instruction": (
            "Implement bump_n(c: &mut Counter, times: i32, delta: i32) -> i32. For 0 <= times <= 50 it adds delta "
            "to the counter times times, each time by calling add, and returns the counter's final value. Do not "
            "assign to the counter's field directly in bump_n. Keep Counter, read, add, and bump_n's signature "
            "unchanged." + _KEEP_MAIN
        ),
    },
    "snapshot-before-move": {
        "source": _BASE + "snapshot.tal",
        "instruction": (
            "Implement weighted(p: Pair) -> i32, returning total(p) * 10 + p.a, where total is the existing "
            "function and must be called with p. Inputs keep every intermediate value within i32. Keep Pair, "
            "total, and weighted's signature unchanged." + _KEEP_MAIN
        ),
    },
    "no-shadowing": {
        "source": _BASE + "normalize.tal",
        "instruction": (
            "Implement normalize(x: i32) -> i32 for every i32 x as these steps, in order: clamp x to the range "
            "-1000 to 1000; multiply by 3; if the result's remainder by 2 is not 0, add 1; then subtract 7. For "
            "example normalize(5000) is 2993 and normalize(-1) is -9. Keep the signature." + _KEEP_MAIN
        ),
    },
    "multi-error-repair": {
        "source": _BASE + "syntax-errors/multi.tal",
        "instruction": (
            "This program was written with habits from other languages and does not compile. Repair it so that "
            "every function keeps its signature and intended behavior: in_range returns whether low <= x <= high; "
            "classify returns -1 for negative x, 0 for zero, and 1 otherwise; boost reads the meter, raises it by "
            "classify(x) * 10, and returns how much the level changed; scaled returns x * 2 + 3; sum3 returns "
            "a + b + c; settle returns twice the meter's level. Keep struct Meter, read, and raise unchanged."
            + _KEEP_MAIN
        ),
    },
}
