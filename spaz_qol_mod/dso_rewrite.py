#!/usr/bin/env python3
"""
DSO code rewriter: replace `getWords(getRes(), "0", "1")` with `Canvas.Extent`
in map scene-window setup, so the maps use the ACTUAL canvas size instead of the
configured (capped) resolution. This makes them fill/center on enlarged screens.

This is NOT size-preserving (expression shrinks 17 slots -> 6 slots), so the
rewriter rebuilds the bytecode stream and shifts all downstream references
(identifier-table IPs, line pairs, FUNC_DECL endIp, jump targets).
"""
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spaz_mods import DSO, OP_FUNC_DECL, OP_CALLFUNC_RESOLVE, OP_LOADIMMED_STR

# Opcode constants used by the replacement.
OP_LOADIMMED_IDENT = 69
OP_SETCUROBJECT = 44
OP_SETCURFIELD = 47
OP_LOADFIELD_STR = 51
OP_LOADIMMED_UINT = 64
OP_LOADIMMED_FLT = 65
OP_PUSH = 79
OP_PUSH_FRAME = 80

# Opcodes that carry an absolute code-slot operand (jump targets / func decl).
JUMP_OPS = {4, 5, 6, 7, 8, 9, 10}  # JMPIFFNOT..JMP


def _ident_map(d):
    """ip (slot) -> string offset (global string table)."""
    m = {}
    for off, ips in d.idents:
        for ip in ips:
            m[ip] = off
    return m


def _ident_by_off(d):
    """string offset -> list of ips."""
    m = {}
    for off, ips in d.idents:
        m[off] = list(ips)
    return m


def find_pattern(d):
    """Find the slot span [start, end) of `getWords(getRes(), "0", "1")`.
    Returns (start, end) or raises."""
    imap = _ident_map(d)
    getres_off = d.gstr.find(b'getRes')
    getwords_off = d.gstr.find(b'getWords')
    if getres_off < 0 or getwords_off < 0:
        raise RuntimeError("getRes/getWords string not found")
    code = d.code
    n = len(code)
    for ip in range(n - 1):
        if code[ip] != OP_CALLFUNC_RESOLVE:
            continue
        # funcName operand at ip+1
        if imap.get(ip + 1) != getres_off:
            continue
        # getRes call: expect PUSH_FRAME PUSH_FRAME before it.
        if ip < 2 or code[ip - 1] != OP_PUSH_FRAME or code[ip - 2] != OP_PUSH_FRAME:
            continue
        start = ip - 2
        # Now walk forward to the getWords call:
        # ... CALLFUNC_RESOLVE(getRes) PUSH LOADIMMED_STR PUSH LOADIMMED_STR PUSH CALLFUNC_RESOLVE(getWords)
        p = ip + 4  # skip getRes's 3 operands
        # p should be PUSH
        if code[p] != OP_PUSH:
            continue
        if code[p + 1] != OP_LOADIMMED_STR:
            continue
        if code[p + 3] != OP_PUSH:
            continue
        if code[p + 4] != OP_LOADIMMED_STR:
            continue
        if code[p + 6] != OP_PUSH:
            continue
        if code[p + 7] != OP_CALLFUNC_RESOLVE:
            continue
        if imap.get(p + 8) != getwords_off:
            continue
        end = p + 7 + 4  # end of getWords call (3 operands)
        return start, end
    raise RuntimeError("pattern getWords(getRes(), '0','1') not found")


def rewrite(data):
    """Return new .dso bytes with the map viewport source switched to Canvas.Extent."""
    d = DSO(data)
    code = list(d.code)
    start, end = find_pattern(d)

    # New code: LOADIMMED_IDENT Canvas ; SETCUROBJECT ; SETCURFIELD Extent ; LOADFIELD_STR
    # (identifier operands are 0 placeholders on disk, resolved via ident table)
    new_code = [OP_LOADIMMED_IDENT, 0, OP_SETCUROBJECT, OP_SETCURFIELD, 0, OP_LOADFIELD_STR]
    delta = len(new_code) - (end - start)  # negative

    # 1. Rebuild code stream.
    newcode = code[:start] + new_code + code[end:]

    canvas_off = d.gstr.find(b'Canvas')
    extent_off = d.gstr.find(b'Extent')
    if canvas_off < 0 or extent_off < 0:
        raise RuntimeError("Canvas/Extent string not found")

    # New identifier operand slots (in the NEW code indexing):
    canvas_slot = start + 1        # LOADIMMED_IDENT operand
    extent_slot = start + 4        # SETCURFIELD operand

    # 2. Rebuild identifier table.
    #    - drop the getRes and getWords operand IPs (inside [start,end))
    #    - add Canvas/Extent new IPs
    #    - shift IPs >= end by delta
    getres_off = d.gstr.find(b'getRes')
    getwords_off = d.gstr.find(b'getWords')
    new_idents = []
    for off, ips in d.idents:
        new_ips = []
        for ip in ips:
            if start <= ip < end:
                continue  # removed (inside replaced expression)
            if ip >= end:
                ip += delta
            new_ips.append(ip)
        if new_ips:
            new_idents.append((off, new_ips))
    # Add Canvas & Extent operand IPs.
    def add_ident(off, ip):
        for i, (o, ips) in enumerate(new_idents):
            if o == off:
                ips.append(ip)
                ips.sort()
                return
        new_idents.append((off, [ip]))
    add_ident(canvas_off, canvas_slot)
    add_ident(extent_off, extent_slot)

    # 3. Adjust absolute code-slot references (jump targets, FUNC_DECL endIp/argc).
    #    Walk the NEW code and shift operands that point past `end`.
    i = 0
    n = len(newcode)
    while i < n:
        op = newcode[i]
        if op == OP_FUNC_DECL:
            # operands: fnName,ns,pkg,hasBody,endIp,argc + argc arg names
            endip_operand = i + 5
            if newcode[endip_operand] >= end:
                newcode[endip_operand] += delta
            argc = newcode[i + 6]
            i += 7 + argc
            continue
        if op in JUMP_OPS:
            target = i + 1
            if newcode[target] >= end:
                newcode[target] += delta
            i += 2
            continue
        if op == OP_CALLFUNC_RESOLVE or op == 71:  # CALLFUNC
            i += 4
            continue
        if op == 1:  # CREATE_OBJECT
            i += 6
            continue
        if op == 2:  # ADD_OBJECT
            i += 2
            continue
        if op in (34, 35, 47, 48, 64, 65, 67, 68, 69, 73):  # 1-operand
            i += 2
            continue
        i += 1

    # 4. Adjust line pairs.
    new_line_pairs = []
    for ip, line in d.linePairs:
        if ip >= end:
            ip += delta
        new_line_pairs.append((ip, line))

    # 5. Rebuild the file.
    # Reuse the same string tables / float tables unchanged (orphaned "0","1","getRes" strings stay).
    out = bytearray()
    out += struct.pack('<I', d.version)
    out += struct.pack('<I', len(d.gstr))
    out += d.gstr
    out += struct.pack('<I', len(d.fstr))
    out += d.fstr
    gfc = len(d.gfloats)
    out += struct.pack('<I', gfc)
    for f in d.gfloats:
        out += struct.pack('<d', f)
    ffc = len(d.ffloats)
    out += struct.pack('<I', ffc)
    for f in d.ffloats:
        out += struct.pack('<d', f)

    # Encode code stream (with 0xFF compression).
    code_bytes = bytearray()
    for v in newcode:
        if v < 0xFF:
            code_bytes.append(v)
        else:
            code_bytes.append(0xFF)
            code_bytes += struct.pack('<I', v)
    out += struct.pack('<I', len(newcode))
    out += struct.pack('<I', len(new_line_pairs))
    out += bytes(code_bytes)
    for ip, line in new_line_pairs:
        out += struct.pack('<II', ip, line)
    out += struct.pack('<I', len(new_idents))
    for off, ips in new_idents:
        out += struct.pack('<I', off)
        out += struct.pack('<I', len(ips))
        for ip in ips:
            out += struct.pack('<I', ip)
    return bytes(out)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, 'rb') as f:
        data = f.read()
    new = rewrite(data)
    with open(dst, 'wb') as f:
        f.write(new)
    print(f"rewrote {src} -> {dst} ({len(data)} -> {len(new)} bytes)")


if __name__ == '__main__':
    main()
