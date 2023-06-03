cpdef char crc8(char *data, char polynomial):
    cdef char result, b
    result = 0xFF

    for b in data[:2]:
        result ^= b
        for bit in range(8):
            if result & 0x80:
                result <<= 1
                result ^= polynomial
            else:
                result <<= 1
    return result & 0xFF
