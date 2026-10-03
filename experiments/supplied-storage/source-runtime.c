/* Internal adapter to checked nominal Talven outcomes. Test hooks are trusted C only. */
#ifdef TV_REGION_SOURCE_TEST
extern void tv_region_source_event(uint32_t operation, tv_region *region,
                                   const tv_block *block, int32_t first, int32_t second,
                                   uint32_t tag, int32_t value);
#define TV_SOURCE_EVENT(op, r, b, a, c, t, v) tv_region_source_event(op, r, b, a, c, t, v)
#else
#define TV_SOURCE_EVENT(op, r, b, a, c, t, v) ((void)0)
#endif
void tv_source_init(tv_region *region, uint8_t *storage, size_t capacity) {
    tv_region_init(region, storage, capacity);
    TV_SOURCE_EVENT(0, region, NULL, (int32_t)capacity, 0, 0, 0);
}
struct tv_s_Allocation tv_source_reserve(tv_region *region, int32_t size, int32_t alignment) {
    tv_allocation result = tv_region_reserve(region, size, alignment);
    TV_SOURCE_EVENT(1, region, result.tag == TV_GRANTED ? &result.payload.block : NULL,
                    size, alignment, result.tag, 0);
    if (result.tag == TV_GRANTED) {
        return (struct tv_s_Allocation){.tv_tag = 0, .tv_payload.tv_m_Granted = result.payload.block};
    }
    tv_region_require(result.tag == TV_INVALID_REQUEST || result.tag == TV_EXHAUSTED);
    return (struct tv_s_Allocation){.tv_tag = result.tag};
}
int32_t tv_source_release(tv_block block) {
    int32_t result = tv_region_release(block);
    TV_SOURCE_EVENT(2, block.origin, &block, 0, 0, 0, result);
    return result;
}
struct tv_s_ByteRead tv_source_read(const tv_block *block, int32_t index) {
    tv_byte_read result = tv_region_read(block, index);
    TV_SOURCE_EVENT(3, block->origin, block, index, 0, result.tag, result.value);
    if (result.tag == TV_READ_VALUE) {
        return (struct tv_s_ByteRead){.tv_tag = 0, .tv_payload.tv_m_Value = result.value};
    }
    tv_region_require(result.tag == TV_READ_OUT_OF_BOUNDS);
    return (struct tv_s_ByteRead){.tv_tag = 1};
}
struct tv_s_ByteWrite tv_source_write(tv_block *block, int32_t index, int32_t value) {
    uint32_t tag = tv_region_write(block, index, value);
    TV_SOURCE_EVENT(4, block->origin, block, index, value, tag, 0);
    tv_region_require(tag <= TV_INVALID_BYTE);
    return (struct tv_s_ByteWrite){.tv_tag = tag};
}
#undef TV_SOURCE_EVENT
