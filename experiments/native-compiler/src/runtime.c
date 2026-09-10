/* Hosted checked arithmetic, retained from the Python reference's C11 contract. */
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <limits.h>
typedef struct { const uint8_t *data; size_t len; } tv_str;
_Static_assert(INT_MAX >= INT32_MAX, "Talven requires at least 32-bit int");
static _Noreturn void talven_trap(void) { abort(); }

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
