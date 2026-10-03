/* Experimental hosted C11 single-slot runtime. No Talven source support.
 * Callers supply aligned storage and keep every descriptor alive while its
 * published owner is live. Initialization starts a fresh logical origin lifetime;
 * do not reinitialize while earlier tokens are considered valid. Descriptor fields
 * are private runtime state apart from explicitly controlled trusted test probes.
 * Metadata is not a foreign-pointer security boundary.
 * TV_REGION_TEST_FAULT enables only trusted test instrumentation.
 */
#ifndef TALVEN_REGION_RUNTIME_V1_H
#define TALVEN_REGION_RUNTIME_V1_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

typedef struct {
    uint8_t *storage;
    size_t capacity;
    uint64_t instance;
    size_t live_size;
    size_t live_alignment;
    bool occupied;
} tv_region;

typedef struct {
    tv_region *origin;
    uint64_t instance;
    size_t length;
    size_t alignment;
} tv_block;

enum { TV_GRANTED = 0, TV_INVALID_REQUEST = 1, TV_EXHAUSTED = 2 };
typedef struct {
    uint32_t tag;
    union { tv_block block; } payload;
} tv_allocation;

enum { TV_READ_VALUE = 0, TV_READ_OUT_OF_BOUNDS = 1 };
typedef struct { uint32_t tag; int32_t value; } tv_byte_read;
enum { TV_WRITTEN = 0, TV_WRITE_OUT_OF_BOUNDS = 1, TV_INVALID_BYTE = 2 };

#ifdef TV_REGION_TEST_FAULT
extern bool tv_region_test_fault(uint32_t step);
#endif

static inline void tv_region_require(bool condition) {
    if (!condition) { abort(); }
}

static inline void tv_region_init(tv_region *region, uint8_t *storage, size_t capacity) {
    tv_region_require(region != NULL && storage != NULL);
    tv_region_require(capacity >= 1 && capacity <= 4096);
    tv_region_require(((uintptr_t)storage % 16) == 0);
    *region = (tv_region){.storage = storage, .capacity = capacity};
}

static inline tv_allocation tv_region_reserve(tv_region *region, int32_t size, int32_t alignment) {
    tv_region_require(region != NULL);
    if (size <= 0 || !(alignment == 1 || alignment == 2 || alignment == 4 ||
                      alignment == 8 || alignment == 16)) {
        return (tv_allocation){.tag = TV_INVALID_REQUEST};
    }
    if ((size_t)size > region->capacity || region->occupied || region->instance == UINT64_MAX) {
        return (tv_allocation){.tag = TV_EXHAUSTED};
    }
    region->instance += UINT64_C(1);
    region->occupied = true;
    region->live_size = (size_t)size;
    region->live_alignment = (size_t)alignment;
#ifdef TV_REGION_TEST_FAULT
    if (tv_region_test_fault(0)) { goto rollback; }
#endif
    for (size_t i = 0; i < (size_t)size; ++i) {
#ifdef TV_REGION_TEST_FAULT
        if (tv_region_test_fault((uint32_t)i + 1)) { goto rollback; }
#endif
        region->storage[i] = 0;
    }
#ifdef TV_REGION_TEST_FAULT
    if (tv_region_test_fault((uint32_t)size + 1)) { goto rollback; }
#endif
    return (tv_allocation){.tag = TV_GRANTED, .payload.block = {
        .origin = region, .instance = region->instance,
        .length = (size_t)size, .alignment = (size_t)alignment
    }};
#ifdef TV_REGION_TEST_FAULT
rollback:
    region->occupied = false;
    region->live_size = 0;
    region->live_alignment = 0;
    return (tv_allocation){.tag = TV_EXHAUSTED};
#endif
}

static inline tv_region *tv_region_owner(tv_block block) {
    tv_region_require(block.origin != NULL);
    tv_region *region = block.origin;
    tv_region_require(region->occupied && block.instance == region->instance &&
                      block.length == region->live_size && block.alignment == region->live_alignment);
    return region;
}

static inline int32_t tv_region_release(tv_block block) {
    tv_region *region = tv_region_owner(block);
    region->occupied = false;
    region->live_size = 0;
    region->live_alignment = 0;
    return 0;
}

static inline tv_byte_read tv_region_read(const tv_block *block, int32_t index) {
    tv_region_require(block != NULL);
    tv_region *region = tv_region_owner(*block);
    if (index < 0 || (size_t)index >= block->length) {
        return (tv_byte_read){.tag = TV_READ_OUT_OF_BOUNDS};
    }
    return (tv_byte_read){.tag = TV_READ_VALUE, .value = region->storage[(size_t)index]};
}

static inline uint32_t tv_region_write(tv_block *block, int32_t index, int32_t value) {
    tv_region_require(block != NULL);
    tv_region *region = tv_region_owner(*block);
    if (index < 0 || (size_t)index >= block->length) { return TV_WRITE_OUT_OF_BOUNDS; }
    if (value < 0 || value > 255) { return TV_INVALID_BYTE; }
    region->storage[(size_t)index] = (uint8_t)value;
    return TV_WRITTEN;
}
#endif
