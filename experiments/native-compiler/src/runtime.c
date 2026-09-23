/* Checked i32 helpers, retained verbatim from the Python reference's C11 contract. lib.rs emits only referenced definitions; keep one helper per blank-line-separated chunk, in this order. */

static inline int32_t tv_narrow(int64_t value) {
    if (value < INT32_MIN || value > INT32_MAX) { talven_trap(); }
    return (int32_t)value;
}

static inline int32_t tv_add(int32_t a, int32_t b) { return tv_narrow((int64_t)a + b); }

static inline int32_t tv_sub(int32_t a, int32_t b) { return tv_narrow((int64_t)a - b); }

static inline int32_t tv_mul(int32_t a, int32_t b) { return tv_narrow((int64_t)a * b); }

static inline int32_t tv_neg(int32_t a) { return tv_narrow(-(int64_t)a); }

static inline int32_t tv_div(int32_t a, int32_t b) {
    if (b == 0 || (a == INT32_MIN && b == -1)) { talven_trap(); }
    return a / b;
}

static inline int32_t tv_mod(int32_t a, int32_t b) {
    if (b == 0 || (a == INT32_MIN && b == -1)) { talven_trap(); }
    return a % b;
}
