# -*- coding: utf-8 -*-
"""
XP3 (Kirikiri) 解包器，支持本游戏 xp3filter.tjs 的 XOR 提取过滤算法。

用法：
    python scripts/xp3.py list   <archive.xp3> [前缀过滤]
    python scripts/xp3.py extract <archive.xp3> <输出目录> [前缀过滤] [--limit N]

XP3 格式：
    文件头: 'XP3\\r\\n \\n\\x1a\\x8bg\\x01' (11 字节) + 索引偏移(8 字节)
    索引:   若干 chunk: 名称(4) + 大小(8) + 数据
    File chunk: 子 chunk 'info'(哈希+UTF16文件名), 'segm'(段表), 'adlr'
    段表项: 标志(4, 1=zlib压缩) + 偏移(8) + 原始大小(8) + 压缩大小(8)
"""
import struct
import sys
import zlib
from pathlib import Path

XP3_MAGIC = b'XP3\r\n \n\x1a\x8bg\x01'


def make_filter(h):
    """复刻 xp3filter.tjs 的 XOR 密钥流（每字节用密钥表低字节）"""
    k = ((h & 1) << 31) | (h & 0x7FFFFFFF)
    t = []
    for _ in range(31):
        t.append(k & 0xFF)
        k = ((k & 0x1FE) << 23) | (k >> 8)
    return t


def apply_filter(buf: bytearray, h: int, base_offset: int = 0):
    t = make_filter(h)
    for i in range(len(buf)):
        buf[i] ^= t[(base_offset + i) % 31]
    return buf


def parse_index(path):
    """返回 [(name, hash, [(flag, offset, size, csize), ...]), ...]

    兼容本游戏的 XP3 v2 变体：索引明文存放在文件末尾，
    通过回溯验证「连续的 File chunk 链恰好到达 EOF」来定位索引起点。
    """
    import mmap
    f = open(path, 'rb')
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    if mm[:11] != XP3_MAGIC:
        raise ValueError(f'不是 XP3 文件: {path}')
    size_total = len(mm)

    def chain_reaches_eof(start):
        pos = start
        while pos + 12 <= size_total:
            if mm[pos:pos + 4] != b'File':
                return None
            csize = struct.unpack('<Q', mm[pos + 4:pos + 12])[0]
            pos += 12 + csize
            if pos > size_total:
                return None
            if pos == size_total:
                return True
        return None

    # 从后往前找 File 出现位置，取能链到 EOF 的最小起点
    index_start = None
    pos = size_total
    while True:
        i = mm.rfind(b'File', 0, pos)
        if i < 0:
            break
        if chain_reaches_eof(i):
            index_start = i
            pos = i
        else:
            break

    if index_start is None:
        raise ValueError('找不到有效索引')

    index = mm[index_start:]
    f.close()

    files = []
    pos = 0
    while pos < len(index):
        if pos + 12 > len(index):
            break
        name = index[pos:pos + 4]
        size = struct.unpack('<Q', index[pos + 4:pos + 12])[0]
        body = index[pos + 12:pos + 12 + size]
        pos += 12 + size
        if name != b'File':
            continue
        # 解析子 chunk
        finfo = {'name': None, 'adlr': 0, 'segs': []}
        sp = 0
        while sp + 12 <= len(body):
            sname = body[sp:sp + 4]
            ssize = struct.unpack('<Q', body[sp + 4:sp + 12])[0]
            sbody = body[sp + 12:sp + 12 + ssize]
            sp += 12 + ssize
            if sname == b'info':
                # info: protect_flag(4) + 大小(8) + 哈希(8) + 文件名长度(2) + UTF16 文件名
                nlen = struct.unpack('<H', sbody[20:22])[0]
                finfo['name'] = sbody[22:22 + nlen * 2].decode('utf-16-le', errors='replace')
            elif sname == b'segm':
                segs = []
                for i in range(0, len(sbody), 28):
                    flag, off, sz, csz = struct.unpack('<IQQQ', sbody[i:i + 28])
                    segs.append((flag, off, sz, csz))
                finfo['segs'] = segs
            elif sname == b'adlr':
                # 本游戏把 XOR 过滤器种子存在 adlr chunk 里
                finfo['adlr'] = struct.unpack('<I', sbody[:4])[0]
        if finfo['name']:
            files.append((finfo['name'], finfo['adlr'], finfo['segs']))
    return files


def extract_file(archive_path, entry, out_path):
    name, h, segs = entry
    out = bytearray()
    with open(archive_path, 'rb') as f:
        for flag, off, sz, csz in segs:
            f.seek(off)
            raw = f.read(csz if flag else sz)
            seg = bytearray(zlib.decompress(raw) if flag else raw)
            apply_filter(seg, h, len(out))
            out += seg
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'wb') as f:
        f.write(out)
    return len(out)


def main():
    cmd = sys.argv[1]
    archive = sys.argv[2]
    files = parse_index(archive)
    if cmd == 'list':
        prefix = sys.argv[3] if len(sys.argv) > 3 else ''
        matched = [n for n, _, _ in files if n.startswith(prefix)]
        print(f'共 {len(files)} 个文件，匹配 {len(matched)} 个')
        for n in matched:
            print(n)
    elif cmd == 'extract':
        outdir = sys.argv[3]
        prefix = sys.argv[4] if len(sys.argv) > 4 else ''
        limit = None
        if '--limit' in sys.argv:
            limit = int(sys.argv[sys.argv.index('--limit') + 1])
        count = 0
        for entry in files:
            if prefix and not entry[0].startswith(prefix):
                continue
            size = extract_file(archive, entry, Path(outdir) / entry[0])
            count += 1
            if count % 200 == 0:
                print(f'已提取 {count} 个...', flush=True)
            if limit and count >= limit:
                break
        print(f'完成，共提取 {count} 个文件')


if __name__ == '__main__':
    main()
