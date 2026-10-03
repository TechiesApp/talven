#include <limits.h>
#include <stdio.h>
#include <string.h>
#include "runtime.h"
#ifndef CAPACITY
#define CAPACITY 32
#endif
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr, "oracle:%d\n", __LINE__); exit(41); } } while (0)

static int32_t fail_at = -1;
static uint32_t fault_calls;
bool tv_region_test_fault(uint32_t step) {
    REQUIRE(step == fault_calls);
    fault_calls += 1;
    return fail_at >= 0 && step == (uint32_t)fail_at;
}

typedef struct {
    uint8_t bytes[CAPACITY + 32];
    uint64_t epoch;
    bool live;
    size_t size;
    size_t alignment;
    unsigned requests;
    unsigned releases;
} ledger;

static void observe(tv_region *region, uint8_t *storage, const ledger *model) {
    REQUIRE(region->storage == storage + 16);
    REQUIRE(region->capacity == CAPACITY);
    REQUIRE(region->instance == model->epoch);
    REQUIRE(region->occupied == model->live);
    REQUIRE(region->live_size == model->size);
    REQUIRE(region->live_alignment == model->alignment);
    REQUIRE(memcmp(storage, model->bytes, sizeof(model->bytes)) == 0);
}

static void fresh(tv_region *region, uint8_t *storage, ledger *model) {
    memset(storage, 0xa5, CAPACITY + 32);
    *model = (ledger){0};
    memset(model->bytes, 0xa5, sizeof(model->bytes));
    tv_region_init(region, storage + 16, CAPACITY);
    observe(region, storage, model);
}

static tv_allocation reserve_checked(tv_region *region, uint8_t *storage, ledger *model,
                                     int32_t size, int32_t alignment) {
    bool valid = size > 0 && (alignment == 1 || alignment == 2 || alignment == 4 ||
                              alignment == 8 || alignment == 16);
    bool space = valid && (size_t)size <= CAPACITY && !model->live && model->epoch != UINT64_MAX;
    uint32_t expected = !valid ? TV_INVALID_REQUEST : !space ? TV_EXHAUSTED : TV_GRANTED;
    if (space) {
        model->epoch += UINT64_C(1);
        bool failed = fail_at >= 0 && fail_at <= size + 1;
        size_t initialized = failed ? (fail_at <= 1 ? 0 : (size_t)fail_at - 1) : (size_t)size;
        memset(model->bytes + 16, 0, initialized);
        if (failed) { expected = TV_EXHAUSTED; }
        else { model->live = true; model->size = (size_t)size; model->alignment = (size_t)alignment; }
    }
    fault_calls = 0;
    tv_allocation result = tv_region_reserve(region, size, alignment);
    model->requests += 1;
    REQUIRE(result.tag == expected);
#ifdef TV_REGION_TEST_FAULT
    REQUIRE(fault_calls == (!space ? 0 : expected == TV_GRANTED ? (uint32_t)size + 2 : (uint32_t)fail_at + 1));
#else
    REQUIRE(fault_calls == 0);
#endif
    observe(region, storage, model);
    if (expected == TV_GRANTED) {
        REQUIRE(result.payload.block.origin == region);
        REQUIRE(result.payload.block.instance == model->epoch);
        REQUIRE(result.payload.block.length == model->size);
        REQUIRE(result.payload.block.alignment == model->alignment);
        REQUIRE(((uintptr_t)region->storage % model->alignment) == 0);
    }
    return result;
}

static void release_checked(tv_region *region, uint8_t *storage, ledger *model, tv_block block) {
    REQUIRE(model->live && block.origin == region && block.instance == model->epoch);
    REQUIRE(tv_region_release(block) == 0);
    model->live = false;
    model->size = model->alignment = 0;
    model->releases += 1;
    observe(region, storage, model);
}

static void accesses(tv_region *region, uint8_t *storage, ledger *model, tv_block block) {
    int32_t indices[] = {INT32_MIN, -1, 0, (int32_t)block.length - 1, (int32_t)block.length, INT32_MAX};
    int32_t values[] = {INT32_MIN, -1, 0, 1, 255, 256, INT32_MAX};
    for (unsigned i = 0; i < sizeof(indices)/sizeof(indices[0]); ++i) {
        for (unsigned v = 0; v < sizeof(values)/sizeof(values[0]); ++v) {
            int32_t index = indices[i], value = values[v];
            uint32_t expected = index < 0 || (size_t)index >= model->size ? TV_WRITE_OUT_OF_BOUNDS :
                                value < 0 || value > 255 ? TV_INVALID_BYTE : TV_WRITTEN;
            REQUIRE(tv_region_write(&block, index, value) == expected);
            if (expected == TV_WRITTEN) { model->bytes[16 + (size_t)index] = (uint8_t)value; }
            observe(region, storage, model);
            tv_byte_read read = tv_region_read(&block, index);
            bool valid = index >= 0 && (size_t)index < model->size;
            REQUIRE(read.tag == (valid ? TV_READ_VALUE : TV_READ_OUT_OF_BOUNDS));
            if (valid) { REQUIRE(read.value == model->bytes[16 + (size_t)index]); }
        }
    }
}

int main(int argc, char **argv) {
    _Alignas(16) uint8_t storage[CAPACITY + 32];
    tv_region region;
    ledger model;
    if (argc > 1) {
        fresh(&region, storage, &model);
        tv_block old = reserve_checked(&region, storage, &model, 1, 1).payload.block;
        if (strcmp(argv[1], "stale") == 0) {
            release_checked(&region, storage, &model, old);
            (void)reserve_checked(&region, storage, &model, 1, 1);
            (void)tv_region_release(old);
        } else if (strcmp(argv[1], "double") == 0) {
            release_checked(&region, storage, &model, old);
            (void)tv_region_release(old);
        } else if (strcmp(argv[1], "length") == 0) {
            old.length += 1;
            (void)tv_region_release(old);
        } else if (strcmp(argv[1], "alignment") == 0) {
            old.alignment = 16;
            (void)tv_region_release(old);
        } else if (strcmp(argv[1], "instance") == 0) {
            old.instance = 0;
            (void)tv_region_release(old);
        } else if (strcmp(argv[1], "read-released") == 0) {
            release_checked(&region, storage, &model, old);
            (void)tv_region_read(&old, 0);
        } else { return 42; }
        return 0; /* A negative contract probe must abort, never return normally. */
    }
    int32_t sizes[] = {INT32_MIN, -1, 0, 1, CAPACITY, CAPACITY + 1, INT32_MAX};
    int32_t alignments[] = {INT32_MIN, -1, 0, 1, 2, 3, 4, 8, 16, 17, INT32_MAX};
    for (unsigned s = 0; s < sizeof(sizes)/sizeof(sizes[0]); ++s) {
        for (unsigned a = 0; a < sizeof(alignments)/sizeof(alignments[0]); ++a) {
            fresh(&region, storage, &model);
            tv_allocation result = reserve_checked(&region, storage, &model, sizes[s], alignments[a]);
            if (result.tag == TV_GRANTED) {
                accesses(&region, storage, &model, result.payload.block);
                (void)reserve_checked(&region, storage, &model, 1, 1); /* preserves existing owner */
                release_checked(&region, storage, &model, result.payload.block);
            }
            REQUIRE(!model.live);
            tv_block reuse = reserve_checked(&region, storage, &model, 1, 1).payload.block;
            release_checked(&region, storage, &model, reuse);
            REQUIRE(model.requests >= 2 && model.releases >= 1 && !model.live);
        }
    }
#ifdef TV_REGION_TEST_FAULT
    int32_t counts[] = {1, CAPACITY};
    for (unsigned n = 0; n < sizeof(counts)/sizeof(counts[0]); ++n) {
        for (int32_t fault = 0; fault <= counts[n] + 1; ++fault) {
            fresh(&region, storage, &model);
            fail_at = fault;
            REQUIRE(reserve_checked(&region, storage, &model, counts[n], 16).tag == TV_EXHAUSTED);
            REQUIRE(!model.live && model.epoch == 1);
            fail_at = -1;
            tv_block retry = reserve_checked(&region, storage, &model, counts[n], 16).payload.block;
            accesses(&region, storage, &model, retry);
            release_checked(&region, storage, &model, retry);
            REQUIRE(model.epoch == 2 && model.releases == 1 && model.requests == 2 && !model.live);
        }
    }
#endif
    fresh(&region, storage, &model);
    region.instance = model.epoch = UINT64_MAX - 1;
    tv_block last = reserve_checked(&region, storage, &model, 1, 1).payload.block;
    REQUIRE(last.instance == UINT64_MAX);
    release_checked(&region, storage, &model, last);
    REQUIRE(reserve_checked(&region, storage, &model, 1, 1).tag == TV_EXHAUSTED);
    REQUIRE(model.epoch == UINT64_MAX && !model.live);
    printf("{\"capacity\":%d,\"descriptor_bytes\":%zu,\"block_bytes\":%zu,\"allocation_bytes\":%zu}\n",
           CAPACITY, sizeof(tv_region), sizeof(tv_block), sizeof(tv_allocation));
    return 0;
}
