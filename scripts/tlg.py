# -*- coding: utf-8 -*-
"""
TLG (Kirikiri) → PNG 解码器，支持 TLG0.0 容器 + TLG6.0 编码。
解码核心算法移植自 https://github.com/Forlos/tlg.py （去除 kaitai 依赖，纯 struct 解析）。

    from tlg import tlg_to_image
    img = tlg_to_image('xxx.tlg')   # -> PIL.Image (RGBA)
"""
import array
import struct

from PIL import Image

TLG0_MAGIC = b"TLG0.0\x00sds\x1a"
TLG6_MAGIC = b"TLG6.0\x00raw\x1A"

TVP_TLG6_GOLOMB_N_COUNT = 4
W_BLOCK_SIZE = 8
H_BLOCK_SIZE = 8
LEADING_ZERO_TABLE_BITS = 12
LEADING_ZERO_TABLE_SIZE = 1 << LEADING_ZERO_TABLE_BITS

LEADING_ZERO_TABLE = list(bytes(LEADING_ZERO_TABLE_SIZE))
GOLOMB_BIT_LENGTH_TABLE = list(
    [list(bytes(TVP_TLG6_GOLOMB_N_COUNT)) for _ in range(TVP_TLG6_GOLOMB_N_COUNT * 2 * 128)]
)

TRANSFORMERS = [
    lambda r, g, b: ((r) & 0xFF, (g) & 0xFF, (b) & 0xFF),
    lambda r, g, b: ((r + g) & 0xFF, (g) & 0xFF, (b + g) & 0xFF),
    lambda r, g, b: ((r + g + b) & 0xFF, (g + b) & 0xFF, (b) & 0xFF),
    lambda r, g, b: ((r) & 0xFF, (g + r) & 0xFF, (b + r + g) & 0xFF),
    lambda r, g, b: ((r + r + g + b) & 0xFF, (g + b + r) & 0xFF, (b + r) & 0xFF),
    lambda r, g, b: ((r) & 0xFF, (g + b + r) & 0xFF, (b + r) & 0xFF),
    lambda r, g, b: ((r) & 0xFF, (g) & 0xFF, (b + g) & 0xFF),
    lambda r, g, b: ((r) & 0xFF, (g + b) & 0xFF, (b) & 0xFF),
    lambda r, g, b: ((r + g) & 0xFF, (g) & 0xFF, (b) & 0xFF),
    lambda r, g, b: ((r + b) & 0xFF, (g + r + b) & 0xFF, (b + r + b + g) & 0xFF),
    lambda r, g, b: ((r) & 0xFF, (g + r) & 0xFF, (b + r) & 0xFF),
    lambda r, g, b: ((r + b) & 0xFF, (g + b) & 0xFF, (b) & 0xFF),
    lambda r, g, b: ((r + b) & 0xFF, (g + r + b) & 0xFF, (b) & 0xFF),
    lambda r, g, b: ((r + b + g) & 0xFF, (g + r + b + g) & 0xFF, (b + g) & 0xFF),
    lambda r, g, b: ((r + b + g + r) & 0xFF, (g + r) & 0xFF, (b + g + r) & 0xFF),
    lambda r, g, b: ((r + (b << 1)) & 0xFF, (g + (b << 1)) & 0xFF, (b) & 0xFF),
]

_table_inited = False


def _init_table():
    global _table_inited
    if _table_inited:
        return
    golomb_compression_table = [
        [3, 7, 15, 27, 63, 108, 223, 448, 130],
        [3, 5, 13, 24, 51, 95, 192, 384, 257],
        [2, 5, 12, 21, 39, 86, 155, 320, 384],
        [2, 3, 9, 18, 33, 61, 129, 258, 511],
    ]
    for i in range(LEADING_ZERO_TABLE_SIZE):
        count = 0
        j = 1
        while j != LEADING_ZERO_TABLE_SIZE and not (i & j):
            j <<= 1
            count += 1
        count += 1
        if j == LEADING_ZERO_TABLE_SIZE:
            count = 0
        LEADING_ZERO_TABLE[i] = count
    for n in range(TVP_TLG6_GOLOMB_N_COUNT):
        a = 0
        for i in range(9):
            for _ in range(golomb_compression_table[n][i]):
                GOLOMB_BIT_LENGTH_TABLE[a][n] = i
                a += 1
    _table_inited = True


def _lzss_decompress(state, input_buf, input_size, output_buf):
    output_buff_index = 0
    state_offset = 0
    flags = 0
    i = 0
    while i < input_size:
        flags >>= 1
        if (flags & 0x100) != 0x100:
            flags = input_buf[i] | 0xFF00
            i += 1
        if (flags & 1) == 1:
            x0 = input_buf[i]
            i += 1
            x1 = input_buf[i]
            i += 1
            position = x0 | ((x1 & 0xF) << 8)
            length = 3 + ((x1 & 0xF0) >> 4)
            if length == 18:
                length += input_buf[i]
                i += 1
            for _ in range(length):
                c = state[position]
                output_buf[output_buff_index] = c
                output_buff_index += 1
                state[state_offset] = c
                state_offset += 1
                state_offset &= 0xFFF
                position += 1
                position &= 0xFFF
        else:
            c = input_buf[i]
            i += 1
            output_buf[output_buff_index] = c
            output_buff_index += 1
            state[state_offset] = c
            state_offset += 1
            state_offset &= 0xFFF
    return output_buf


def _decompress_filter_types(filter_types, x_block_count, y_block_count):
    output = bytearray(x_block_count * y_block_count)
    state = bytearray(4096)
    state_index = 0
    for i in range(32):
        for j in range(16):
            for _ in range(4):
                state[state_index] = i
                state_index += 1
            for _ in range(4):
                state[state_index] = j
                state_index += 1
    _lzss_decompress(state, filter_types, len(filter_types), output)
    return output


def _decode_golomb(pixel_buf, start_index, pixel_count, bit_pool):
    bit_pool_index = 0
    pixel_buf_index = start_index
    n = TVP_TLG6_GOLOMB_N_COUNT - 1
    a = 0
    bit_pos = 1
    zero = bit_pool[0] & 1 == 0
    while pixel_buf_index < pixel_count * 4:
        count = 0
        t = int.from_bytes(bit_pool[bit_pool_index:bit_pool_index + 4], "little") >> bit_pos
        b = LEADING_ZERO_TABLE[t & (LEADING_ZERO_TABLE_SIZE - 1)]
        bit_count = b
        while not b:
            bit_count += LEADING_ZERO_TABLE_BITS
            bit_pos += LEADING_ZERO_TABLE_BITS
            bit_pool_index += bit_pos >> 3
            bit_pos &= 7
            t = int.from_bytes(bit_pool[bit_pool_index:bit_pool_index + 4], "little") >> bit_pos
            b = LEADING_ZERO_TABLE[t & (LEADING_ZERO_TABLE_SIZE - 1)]
            bit_count += b
        bit_pos += b
        bit_pool_index += bit_pos >> 3
        bit_pos &= 7
        bit_count -= 1
        count = 1 << bit_count
        t = int.from_bytes(bit_pool[bit_pool_index:bit_pool_index + 4], "little")
        count += (t >> bit_pos) & (count - 1)
        bit_pos += bit_count
        bit_pool_index += bit_pos >> 3
        bit_pos &= 7
        if zero:
            while True:
                pixel_buf[pixel_buf_index] = 0
                pixel_buf_index += 4
                count -= 1
                if count <= 0:
                    break
        else:
            while True:
                bit_count = 0
                b = 0
                t = int.from_bytes(bit_pool[bit_pool_index:bit_pool_index + 4], "little") >> bit_pos
                if t:
                    b = LEADING_ZERO_TABLE[t & (LEADING_ZERO_TABLE_SIZE - 1)]
                    bit_count = b
                    while not b:
                        bit_count += LEADING_ZERO_TABLE_BITS
                        bit_pos += LEADING_ZERO_TABLE_BITS
                        bit_pool_index += bit_pos >> 3
                        bit_pos &= 7
                        t = int.from_bytes(bit_pool[bit_pool_index:bit_pool_index + 4], "little") >> bit_pos
                        b = LEADING_ZERO_TABLE[t & (LEADING_ZERO_TABLE_SIZE - 1)]
                        bit_count += b
                    bit_count -= 1
                else:
                    bit_pool_index += 5
                    bit_count = bit_pool[bit_pool_index - 1]
                    bit_pos = 0
                    t = int.from_bytes(bit_pool[bit_pool_index:bit_pool_index + 4], "little")
                    b = 0
                k = GOLOMB_BIT_LENGTH_TABLE[a][n]
                v = (bit_count << k) + ((t >> b) & ((1 << k) - 1))
                sign = (v & 1) - 1
                v >>= 1
                a += v
                pixel_buf[pixel_buf_index] = ((v ^ sign) + sign + 1) & 0xFF
                pixel_buf_index += 4
                bit_pos += b
                bit_pos += k
                bit_pool_index += bit_pos >> 3
                bit_pos &= 7
                n -= 1
                if n < 0:
                    a >>= 1
                    n = TVP_TLG6_GOLOMB_N_COUNT - 1
                count -= 1
                if count <= 0:
                    break
        zero = not zero


def _gt_mask(a, b):
    x = ~b
    y = ((a & x) + (((a ^ x) >> 1) & 0x7F7F7F7F)) & 0x80808080
    return ((y >> 7) + 0x7F7F7F7F) ^ 0x7F7F7F7F


def _packed_bytes_add(a, b):
    return a + b - ((((a & b) << 1) + ((a ^ b) & 0xFEFEFEFE)) & 0x01010100)


def _med(a, b, c, v):
    mask = _gt_mask(a, b)
    ab = (a ^ b) & mask
    aa = ab ^ a
    bb = ab ^ b
    a_mask = _gt_mask(aa, c)
    b_mask = _gt_mask(c, bb)
    m = ~(a_mask | b_mask)
    return (_packed_bytes_add((b_mask & aa) | (a_mask & bb) | ((bb & m) - (c & m) + (aa & m)), v) & 0xFFFFFFFF)


def _avg(a, b, c, v):
    return (_packed_bytes_add((a & b) + (((a ^ b) & 0xFEFEFEFE) >> 1) + ((a ^ b) & 0x01010101), v) & 0xFFFFFFFF)


def _decode_line(prev_line, cur_line, width, start_block, block_limit, filter_types,
                 skip_block_bytes, input_buf, initialp, odd_skip, dir, channel_count):
    if start_block:
        prev_line_index = start_block * W_BLOCK_SIZE
        cur_line_index = start_block * W_BLOCK_SIZE
        up = prev_line[prev_line_index - 1]
        p = cur_line[cur_line_index - 1]
    else:
        prev_line_index = 0
        cur_line_index = 0
        p = up = initialp
    input_buf_index = (skip_block_bytes * start_block) * 4
    step = 1 if (dir & 1) else -1
    for i in range(start_block, block_limit):
        w = width - i * W_BLOCK_SIZE
        if w > W_BLOCK_SIZE:
            w = W_BLOCK_SIZE
        ww = w
        if step == -1:
            input_buf_index += (ww - 1) * 4
        if i & 1:
            input_buf_index += (odd_skip * ww) * 4
        filter_fn = _avg if (filter_types[i] & 1) else _med
        transformer_fn = TRANSFORMERS[filter_types[i] >> 1]
        while True:
            a = input_buf[input_buf_index + 3]
            r = input_buf[input_buf_index + 2]
            g = input_buf[input_buf_index + 1]
            b = input_buf[input_buf_index]
            r, g, b = transformer_fn(r, g, b)
            u = prev_line[prev_line_index]
            p = filter_fn(p, u, up,
                          (0xFF0000 & (b << 16)) + (0xFF00 & (g << 8)) + (0xFF & r) + (a << 24))
            if channel_count == 3:
                p |= 0xFF000000
            up = u
            cur_line[cur_line_index] = p
            cur_line_index += 1
            prev_line_index += 1
            input_buf_index += step * 4
            w -= 1
            if w <= 0:
                break
        input_buf_index += (skip_block_bytes + (-ww if step == 1 else 1)) * 4
        if i & 1:
            input_buf_index -= (odd_skip * ww) * 4


class Tlg6Image:
    def __init__(self, data: bytes):
        if data[:11] != TLG6_MAGIC:
            raise ValueError('不是 TLG6 数据')
        pos = 11
        self.colors, self.data_flag, self.color_type, self.external_golomb = data[pos:pos + 4]
        pos += 4
        self.width, self.height, self.max_bit_length = struct.unpack_from('<III', data, pos)
        pos += 12
        ft_size = struct.unpack_from('<I', data, pos)[0]
        pos += 4
        self.filter_types = data[pos:pos + ft_size]
        pos += ft_size
        self.x_block_count = (self.width - 1) // W_BLOCK_SIZE + 1
        self.y_block_count = (self.height - 1) // H_BLOCK_SIZE + 1
        self.main_count = self.width // W_BLOCK_SIZE
        self.fraction = self.width - self.main_count * W_BLOCK_SIZE
        line_count = (self.height + H_BLOCK_SIZE - 1) // H_BLOCK_SIZE
        self.lines = []
        for _ in range(line_count):
            chans = []
            for _ in range(self.colors):
                length = struct.unpack_from('<I', data, pos)[0]
                pos += 4
                method = (length >> 30) & 3
                raw_len = length & 0x3FFFFFFF
                byte_len = (raw_len + H_BLOCK_SIZE - 1) // H_BLOCK_SIZE
                bit_pool = data[pos:pos + byte_len]
                pos += byte_len
                chans.append((method, bit_pool))
            self.lines.append(chans)

    def decode(self) -> Image:
        _init_table()
        pixels = array.array("I")
        filter_types = _decompress_filter_types(self.filter_types, self.x_block_count, self.y_block_count)
        pixel_buf = bytearray(4 * W_BLOCK_SIZE * self.width)  # 8 行块缓冲
        zero_line = array.array("I")
        zero_line.frombytes(bytes(4 * self.width))
        prev_line = zero_line
        for i, chans in enumerate(self.lines):
            y = i * H_BLOCK_SIZE
            y_lim = min(y + H_BLOCK_SIZE, self.height)
            pixel_count = (y_lim - y) * self.width
            for c, (method, bit_pool) in enumerate(chans):
                if method == 0:
                    _decode_golomb(pixel_buf, c, pixel_count, bit_pool)
                else:
                    raise ValueError(f'不支持的压缩方式: {method}')
            ft = filter_types[(y // H_BLOCK_SIZE) * self.x_block_count:]
            skip_bytes = (y_lim - y) * W_BLOCK_SIZE
            for yy in range(y, y_lim):
                cur_line = array.array("I")
                cur_line.frombytes(bytearray(4 * self.width))
                dir_ = (yy & 1) ^ 1
                odd_skip = (y_lim - yy - 1) - (yy - y)
                initialp = 0xFF000000 if self.colors == 3 else 0
                if self.main_count:
                    start = min(self.width, W_BLOCK_SIZE) * (yy - y)
                    _decode_line(prev_line, cur_line, self.width, 0, self.main_count,
                                 ft, skip_bytes, pixel_buf[start * 4:], initialp,
                                 odd_skip, dir_, self.colors)
                if self.main_count != self.x_block_count:
                    ww = min(self.fraction, W_BLOCK_SIZE)
                    start = ww * (yy - y)
                    _decode_line(prev_line, cur_line, self.width, self.main_count,
                                 self.x_block_count, ft, skip_bytes, pixel_buf[start * 4:],
                                 initialp, odd_skip, dir_, self.colors)
                pixels.extend(cur_line)
                prev_line = cur_line
        return Image.frombytes("RGBA", (self.width, self.height), pixels.tobytes())


def tlg_to_image(path) -> Image:
    """读取 TLG 文件（TLG0 容器 + TLG6 编码），返回 PIL RGBA 图像"""
    with open(path, 'rb') as f:
        data = f.read()
    if data[:11] == TLG0_MAGIC:
        raw_length = struct.unpack_from('<I', data, 11)[0]
        data = data[15:15 + raw_length]
    if data[:11] != TLG6_MAGIC:
        raise ValueError(f'不支持的 TLG 格式: {data[:11]}')
    return Tlg6Image(data).decode()
