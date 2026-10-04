/* Independent request-plan oracle for the internal C-only byte buffer. */
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include "../../experiments/byte-buffer/runtime.h"
#ifndef CAPACITY
#define CAPACITY 32
#endif
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr, "oracle:%d\n", __LINE__); exit(41); } } while (0)
static int32_t fail_at = -1;
static uint32_t fault_calls;
bool tv_region_test_fault(uint32_t step) {
    REQUIRE(step == fault_calls);
    fault_calls++;
    return fail_at >= 0 && step == (uint32_t)fail_at;
}
typedef struct {
    uint8_t bytes[CAPACITY + 32];
    uint64_t epoch;
    bool live;
    size_t reserved, alignment, length;
    unsigned granted, released;
} ledger;
typedef struct {
    _Alignas(16) uint8_t storage[CAPACITY + 32];
    tv_region region;
    ledger expected;
} fixture;
static void observe(const fixture *f) {
    const ledger *m = &f->expected;
    REQUIRE(f->region.storage == f->storage + 16);
    REQUIRE(f->region.capacity == CAPACITY);
    REQUIRE(f->region.instance == m->epoch);
    REQUIRE(f->region.occupied == m->live);
    REQUIRE(f->region.live_size == m->reserved);
    REQUIRE(f->region.live_alignment == m->alignment);
    REQUIRE(memcmp(f->storage, m->bytes, sizeof(m->bytes)) == 0);
}
static void observe_buffer(const fixture *f, const tv_buffer *b) {
    observe(f);
    REQUIRE(f->expected.live);
    REQUIRE(b->block.origin == &f->region);
    REQUIRE(b->block.instance == f->expected.epoch);
    REQUIRE(b->block.length == f->expected.reserved);
    REQUIRE(b->block.alignment == 1);
    REQUIRE(b->length == f->expected.length);
}
static void fresh(fixture *f, uint64_t epoch) {
    memset(f->storage, 0xa5, sizeof(f->storage));
    f->expected = (ledger){.epoch = epoch};
    memset(f->expected.bytes, 0xa5, sizeof(f->expected.bytes));
    tv_region_init(&f->region, f->storage + 16, CAPACITY);
    /* Explicit trusted saturation injection; never an observed oracle input. */
    f->region.instance = epoch;
    observe(f);
}
static uint32_t planned_reserve(fixture *f, int32_t size, int32_t alignment) {
    ledger *m = &f->expected;
    bool valid = size > 0 && (alignment == 1 || alignment == 2 || alignment == 4 || alignment == 8 || alignment == 16);
    bool space = valid && (size_t)size <= CAPACITY && !m->live && m->epoch != UINT64_MAX;
    uint32_t tag = !valid ? 1 : !space ? 2 : 0;
    fault_calls = 0;
    if (space) {
        m->epoch++;
        bool failed = false;
#ifdef TV_REGION_TEST_FAULT
        failed = fail_at >= 0 && fail_at <= size + 1;
#endif
        size_t initialized = failed ? (fail_at <= 1 ? 0 : (size_t)fail_at - 1) : (size_t)size;
        memset(m->bytes + 16, 0, initialized);
        if (failed) { tag = 2; }
        else {
            m->live = true;
            m->reserved = (size_t)size;
            m->alignment = (size_t)alignment;
            m->length = 0;
            m->granted++;
        }
    }
    return tag;
}
static void check_faults(uint32_t tag, bool attempted, int32_t size) {
#ifdef TV_REGION_TEST_FAULT
    REQUIRE(fault_calls == (!attempted ? 0 : tag == 0 ? (uint32_t)size + 2 : (uint32_t)fail_at + 1));
#else
    (void)tag; (void)attempted; (void)size;
    REQUIRE(fault_calls == 0);
#endif
}
static tv_buffer_allocation reserve_buffer(fixture *f, int32_t capacity) {
    bool attempted = capacity > 0 && capacity <= CAPACITY && !f->expected.live && f->expected.epoch != UINT64_MAX;
    uint32_t expected = planned_reserve(f, capacity, 1);
    tv_buffer_allocation result = tv_buffer_reserve(&f->region, capacity);
    REQUIRE(result.tag == expected);
    check_faults(expected, attempted, capacity);
    observe(f);
    if (expected == 0) { observe_buffer(f, &result.payload.buffer); }
    return result;
}
static tv_allocation reserve_block(fixture *f, int32_t size, int32_t alignment) {
    bool attempted = size > 0 && size <= CAPACITY && !f->expected.live && f->expected.epoch != UINT64_MAX && (alignment == 1 || alignment == 2 || alignment == 4 || alignment == 8 || alignment == 16);
    uint32_t expected = planned_reserve(f, size, alignment);
    tv_allocation result = tv_region_reserve(&f->region, size, alignment);
    REQUIRE(result.tag == expected);
    check_faults(expected, attempted, size);
    observe(f);
    if (expected == 0) {
        REQUIRE(result.payload.block.origin == &f->region);
        REQUIRE(result.payload.block.instance == f->expected.epoch);
        REQUIRE(result.payload.block.length == f->expected.reserved);
        REQUIRE(result.payload.block.alignment == f->expected.alignment);
    }
    return result;
}
static void retired(fixture *f) {
    f->expected.live = false;
    f->expected.reserved = f->expected.alignment = f->expected.length = 0;
    f->expected.released++;
    observe(f);
}
static void close_buffer(fixture *f, tv_buffer b) {
    observe_buffer(f, &b);
    REQUIRE(tv_buffer_close(b) == 0);
    retired(f);
}
static void queries(fixture *f, const tv_buffer *b) {
    REQUIRE(tv_buffer_length(b) == (int32_t)f->expected.length);
    observe_buffer(f, b);
    REQUIRE(tv_buffer_capacity(b) == (int32_t)f->expected.reserved);
    observe_buffer(f, b);
}
static void read_buffer(fixture *f, const tv_buffer *b, int32_t index) {
    bool valid = index >= 0 && (size_t)index < f->expected.length;
    tv_byte_read result = tv_buffer_read(b, index);
    REQUIRE(result.tag == (valid ? 0u : 1u));
    if (valid) { REQUIRE(result.value == f->expected.bytes[16 + (size_t)index]); }
    observe_buffer(f, b);
}
static void write_buffer(fixture *f, tv_buffer *b, int32_t index, int32_t value) {
    uint32_t expected = index < 0 || (size_t)index >= f->expected.length ? 1 : value < 0 || value > 255 ? 2 : 0;
    if (expected == 0) { f->expected.bytes[16 + (size_t)index] = (uint8_t)value; }
    REQUIRE(tv_buffer_write(b, index, value) == expected);
    observe_buffer(f, b);
    queries(f, b);
}
static void push(fixture *f, tv_buffer *b, int32_t value) {
    uint32_t expected = f->expected.length == f->expected.reserved ? 1 : value < 0 || value > 255 ? 2 : 0;
    if (expected == 0) {
        f->expected.bytes[16 + f->expected.length] = (uint8_t)value;
        f->expected.length++;
    }
    REQUIRE(tv_buffer_push(b, value) == expected);
    observe_buffer(f, b);
    queries(f, b);
}
static void pop(fixture *f, tv_buffer *b) {
    bool nonempty = f->expected.length != 0;
    int32_t value = nonempty ? f->expected.bytes[16 + f->expected.length - 1] : 0;
    if (nonempty) { f->expected.length--; }
    tv_buffer_pop_result result = tv_buffer_pop(b);
    REQUIRE(result.tag == (nonempty ? 0u : 1u));
    if (nonempty) { REQUIRE(result.value == value); }
    observe_buffer(f, b);
    queries(f, b);
}
static void accesses(fixture *f, tv_buffer *b) {
    int32_t indices[] = {INT32_MIN, -1, 0, (int32_t)f->expected.length - 1,
                         (int32_t)f->expected.length, (int32_t)f->expected.reserved, INT32_MAX};
    int32_t values[] = {INT32_MIN, -1, 0, 1, 254, 255, 256, INT32_MAX};
    for (size_t i = 0; i < sizeof(indices)/sizeof(indices[0]); i++) {
        for (size_t v = 0; v < sizeof(values)/sizeof(values[0]); v++) {
            write_buffer(f, b, indices[i], values[v]);
            read_buffer(f, b, indices[i]);
        }
    }
}
static void transitions(fixture *f, tv_buffer *b) {
    queries(f, b);
    pop(f, b);
    accesses(f, b);
    push(f, b, INT32_MIN);
    push(f, b, -1);
    push(f, b, 256);
    push(f, b, INT32_MAX);
    for (unsigned round = 0; round < 3; round++) {
        size_t reserved = f->expected.reserved;
        for (size_t i = 0; i < reserved; i++) {
            push(f, b, (int32_t)((i * 37 + round * 83) % 256));
            read_buffer(f, b, (int32_t)i);
            read_buffer(f, b, (int32_t)i + 1);
        }
        accesses(f, b);
        push(f, b, 0);
        push(f, b, -1); /* Full precedes invalid byte. */
        push(f, b, 256);
        push(f, b, INT32_MAX);
        for (size_t i = 0; i < reserved; i++) {
            pop(f, b);
            read_buffer(f, b, (int32_t)f->expected.length); /* Retired byte inaccessible. */
        }
        pop(f, b);
    }
    /* All byte values, even when the backing capacity is one. */
    for (int32_t value = 0; value <= 255; value++) { push(f, b, value); read_buffer(f, b, 0); pop(f, b); }
}
static void complete(fixture *f) {
    REQUIRE(!f->expected.live && f->expected.granted == f->expected.released);
    observe(f);
}
static int probe(fixture *f, const char *name) {
    const char *names[] = {"stale", "double", "length", "block-capacity", "alignment", "instance",
                          "read-closed", "write-closed", "push-closed", "pop-closed", "length-closed", "capacity-closed"};
    bool known = false;
    for (size_t i = 0; i < sizeof(names)/sizeof(names[0]); i++) { if (strcmp(name, names[i]) == 0) { known = true; } }
    if (!known) { return 42; }
    fresh(f, 0);
    if (strcmp(name, "alignment") == 0) {
        tv_block aligned = reserve_block(f, 1, 2).payload.block;
        tv_buffer wrapped = {.block = aligned, .length = 0};
        (void)tv_buffer_push(&wrapped, 0);
        return 0;
    }
    tv_buffer b = reserve_buffer(f, 1).payload.buffer;
    if (strcmp(name, "stale") == 0) { close_buffer(f, b); (void)reserve_buffer(f, 1); (void)tv_buffer_close(b); }
    else if (strcmp(name, "double") == 0) { close_buffer(f, b); (void)tv_buffer_close(b); }
    else if (strcmp(name, "length") == 0) { b.length = 2; (void)tv_buffer_length(&b); }
    else if (strcmp(name, "block-capacity") == 0) { b.block.length = 2; (void)tv_buffer_capacity(&b); }
    else if (strcmp(name, "instance") == 0) { b.block.instance = 0; (void)tv_buffer_pop(&b); }
    else {
        close_buffer(f, b);
        if (strcmp(name, "read-closed") == 0) { (void)tv_buffer_read(&b, 0); }
        else if (strcmp(name, "write-closed") == 0) { (void)tv_buffer_write(&b, 0, 0); }
        else if (strcmp(name, "push-closed") == 0) { (void)tv_buffer_push(&b, 0); }
        else if (strcmp(name, "pop-closed") == 0) { (void)tv_buffer_pop(&b); }
        else if (strcmp(name, "length-closed") == 0) { (void)tv_buffer_length(&b); }
        else { (void)tv_buffer_capacity(&b); }
    }
    return 0;
}
int main(int argc, char **argv) {
    fixture f;
    REQUIRE(TV_BUFFER_PUSHED == 0 && TV_BUFFER_FULL == 1 && TV_BUFFER_INVALID_BYTE == 2);
    REQUIRE(TV_BUFFER_VALUE == 0 && TV_BUFFER_EMPTY == 1);
    if (argc > 1) { return probe(&f, argv[1]); }
    int32_t capacities[] = {INT32_MIN, -1, 0, 1, CAPACITY, CAPACITY + 1, INT32_MAX};
    for (size_t i = 0; i < sizeof(capacities)/sizeof(capacities[0]); i++) {
        fresh(&f, 0);
        tv_buffer_allocation allocation = reserve_buffer(&f, capacities[i]);
        if (allocation.tag == 0) {
            tv_buffer b = allocation.payload.buffer;
            transitions(&f, &b);
            (void)reserve_buffer(&f, 1);
            (void)reserve_buffer(&f, 0);
            (void)reserve_block(&f, 1, 1);
            (void)reserve_block(&f, 0, 1);
            close_buffer(&f, b);
        }
        tv_buffer reuse = reserve_buffer(&f, 1).payload.buffer;
        close_buffer(&f, reuse);
        complete(&f);
    }
    fresh(&f, 0);
    tv_block block = reserve_block(&f, CAPACITY, 1).payload.block;
    REQUIRE(tv_region_write(&block, 0, 219) == 0);
    f.expected.bytes[16] = 219;
    observe(&f);
    (void)reserve_buffer(&f, CAPACITY);
    (void)reserve_buffer(&f, -1);
    REQUIRE(tv_region_release(block) == 0);
    retired(&f);
    tv_buffer mixed = reserve_buffer(&f, CAPACITY).payload.buffer;
    close_buffer(&f, mixed);
    complete(&f);
#ifdef TV_REGION_TEST_FAULT
    int32_t sizes[] = {1, CAPACITY};
    for (size_t n = 0; n < sizeof(sizes)/sizeof(sizes[0]); n++) {
        for (int32_t fault = 0; fault <= sizes[n] + 1; fault++) {
            fresh(&f, 0);
            fail_at = fault;
            REQUIRE(reserve_buffer(&f, sizes[n]).tag == 2);
            REQUIRE(!f.expected.live && f.expected.epoch == 1);
            fail_at = -1;
            tv_buffer retry = reserve_buffer(&f, sizes[n]).payload.buffer;
            push(&f, &retry, 255);
            pop(&f, &retry);
            close_buffer(&f, retry);
            REQUIRE(f.expected.epoch == 2);
            complete(&f);
        }
    }
    fresh(&f, UINT64_MAX - 1);
    fail_at = 1;
    REQUIRE(reserve_buffer(&f, 1).tag == 2);
    fail_at = -1;
    REQUIRE(reserve_buffer(&f, 1).tag == 2);
    REQUIRE(f.expected.epoch == UINT64_MAX);
    complete(&f);
#endif
    fresh(&f, UINT64_MAX);
    REQUIRE(reserve_buffer(&f, 1).tag == 2);
    REQUIRE(reserve_buffer(&f, 0).tag == 1);
    complete(&f);
    fresh(&f, UINT64_MAX - 1);
    tv_buffer last = reserve_buffer(&f, 1).payload.buffer;
    push(&f, &last, 128);
    close_buffer(&f, last);
    REQUIRE(reserve_buffer(&f, 1).tag == 2);
    complete(&f);
    printf("{\"capacity\":%d,\"descriptor_bytes\":%zu,\"block_bytes\":%zu,\"buffer_bytes\":%zu,\"allocation_bytes\":%zu,\"pop_result_bytes\":%zu}\n",
           CAPACITY, sizeof(tv_region), sizeof(tv_block), sizeof(tv_buffer), sizeof(tv_buffer_allocation), sizeof(tv_buffer_pop_result));
    return 0;
}
