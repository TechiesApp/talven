/* Experimental hosted C11 supplied-storage byte buffer. No Talven source support.
 * The block token, logical length and originating region are private runtime state.
 * Trusted C callers keep the descriptor and backing object alive, and transfer
 * rather than copy owners. Matching forged tokens are outside this boundary.
 */
#ifndef TALVEN_BYTE_BUFFER_RUNTIME_V1_H
#define TALVEN_BYTE_BUFFER_RUNTIME_V1_H
#include "../supplied-storage/runtime.h"

typedef struct {
    tv_block block;
    size_t length;
} tv_buffer;

typedef struct {
    uint32_t tag;
    union { tv_buffer buffer; } payload;
} tv_buffer_allocation;

enum { TV_BUFFER_PUSHED = 0, TV_BUFFER_FULL = 1, TV_BUFFER_INVALID_BYTE = 2 };
enum { TV_BUFFER_VALUE = 0, TV_BUFFER_EMPTY = 1 };
typedef struct { uint32_t tag; int32_t value; } tv_buffer_pop_result;

static inline tv_region *tv_buffer_owner(const tv_buffer *buffer) {
    tv_region_require(buffer != NULL);
    tv_region *region = tv_region_owner(buffer->block);
    tv_region_require(buffer->block.alignment == 1 && buffer->length <= buffer->block.length);
    return region;
}

static inline tv_buffer_allocation tv_buffer_reserve(tv_region *region, int32_t capacity) {
    tv_allocation allocation = tv_region_reserve(region, capacity, 1);
    if (allocation.tag != TV_GRANTED) {
        return (tv_buffer_allocation){.tag = allocation.tag};
    }
    return (tv_buffer_allocation){.tag = TV_GRANTED, .payload.buffer = {
        .block = allocation.payload.block, .length = 0
    }};
}

static inline int32_t tv_buffer_length(const tv_buffer *buffer) {
    (void)tv_buffer_owner(buffer);
    return (int32_t)buffer->length;
}

static inline int32_t tv_buffer_capacity(const tv_buffer *buffer) {
    (void)tv_buffer_owner(buffer);
    return (int32_t)buffer->block.length;
}

static inline tv_byte_read tv_buffer_read(const tv_buffer *buffer, int32_t index) {
    tv_region *region = tv_buffer_owner(buffer);
    if (index < 0 || (size_t)index >= buffer->length) {
        return (tv_byte_read){.tag = TV_READ_OUT_OF_BOUNDS};
    }
    return (tv_byte_read){.tag = TV_READ_VALUE, .value = region->storage[(size_t)index]};
}

static inline uint32_t tv_buffer_write(tv_buffer *buffer, int32_t index, int32_t value) {
    tv_region *region = tv_buffer_owner(buffer);
    if (index < 0 || (size_t)index >= buffer->length) { return TV_WRITE_OUT_OF_BOUNDS; }
    if (value < 0 || value > 255) { return TV_INVALID_BYTE; }
    region->storage[(size_t)index] = (uint8_t)value;
    return TV_WRITTEN;
}

static inline uint32_t tv_buffer_push(tv_buffer *buffer, int32_t value) {
    tv_region *region = tv_buffer_owner(buffer);
    if (buffer->length == buffer->block.length) { return TV_BUFFER_FULL; }
    if (value < 0 || value > 255) { return TV_BUFFER_INVALID_BYTE; }
    region->storage[buffer->length] = (uint8_t)value;
    buffer->length += 1;
    return TV_BUFFER_PUSHED;
}

static inline tv_buffer_pop_result tv_buffer_pop(tv_buffer *buffer) {
    tv_region *region = tv_buffer_owner(buffer);
    if (buffer->length == 0) { return (tv_buffer_pop_result){.tag = TV_BUFFER_EMPTY}; }
    int32_t value = region->storage[buffer->length - 1];
    buffer->length -= 1;
    return (tv_buffer_pop_result){.tag = TV_BUFFER_VALUE, .value = value};
}

static inline int32_t tv_buffer_close(tv_buffer buffer) {
    (void)tv_buffer_owner(&buffer);
    return tv_region_release(buffer.block);
}
#endif
