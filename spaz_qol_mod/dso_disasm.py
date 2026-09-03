#!/usr/bin/env python3
"""
Disassembler for Torque 2D .dso compiled-script files (SPAZ, 32-bit build).

Usage:
    python3 dso_disasm.py <file.dso> [func_name_filter] [max_lines]

Reads the DSO parser from spaz_mods and prints a readable disassembly.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spaz_mods import DSO, OPNAMES

# Operand counts per opcode (32-bit build = 1-slot identifiers).
OPERANDS = [0] * 83
OPERANDS[0] = 6    # FUNC_DECL
OPERANDS[1] = 5    # CREATE_OBJECT
OPERANDS[2] = 1    # ADD_OBJECT
for o in (4, 5, 6, 7, 8, 9, 10):  # jumps
    OPERANDS[o] = 1
for o in (34, 35):  # SETCURVAR, SETCURVAR_CREATE
    OPERANDS[o] = 1
for o in (47, 48):  # SETCURFIELD, SETCURFIELD_ARRAY
    OPERANDS[o] = 1
for o in (64, 65, 67):  # LOADIMMED_UINT/FLT/STR
    OPERANDS[o] = 1
OPERANDS[68] = 1   # DOCBLOCK_STR
OPERANDS[69] = 1   # LOADIMMED_IDENT
for o in (70, 71):  # CALLFUNC_RESOLVE, CALLFUNC
    OPERANDS[o] = 3
OPERANDS[73] = 1   # ADVANCE_STR_APPENDCHAR

IDENT_OPCODES = {34, 35, 47, 48, 69}  # operands that are identifiers
CALL_OPCODES = {70, 71}  # CALLFUNC_RESOLVE, CALLFUNC


def build_ident_map(d):
    """ip (code slot) -> string, from the identifier table."""
    m = {}
    for string_off, ips in d.idents:
        s = d.gstr_at(string_off)
        for ip in ips:
            m[ip] = s
    return m


def resolve(d, op, ident_map, operand_ip, value):
    """Pretty-print a single operand, given its code-slot IP and value."""
    if op in IDENT_OPCODES:
        s = ident_map.get(operand_ip)
        return repr(s) if s is not None else f"IDENT@{operand_ip}"
    if op == 67 or op == 68:  # LOADIMMED_STR / DOCBLOCK_STR (string offset)
        s = d.fstr_at(value)
        if s is None:
            s = d.gstr_at(value)
        return repr(s) if s is not None else f"str@{value}"
    if op == 65:  # LOADIMMED_FLT (float table index)
        parts = []
        if value < len(d.gfloats):
            parts.append(f"g{d.gfloats[value]:g}")
        if value < len(d.ffloats):
            parts.append(f"f{d.ffloats[value]:g}")
        return "/".join(parts) if parts else f"flt#{value}"
    return str(value)


def disassemble(data, func_filter=None, max_lines=None):
    d = DSO(data)
    ident_map = build_ident_map(d)
    code = d.code
    lines = []
    ip = 0
    n = len(code)
    while ip < n:
        op = code[ip]
        if op >= len(OPERANDS):
            lines.append(f"{ip:6d}  ?? op={op}")
            ip += 1
            continue
        name = OPNAMES[op] if op < len(OPNAMES) else f"OP{op}"
        count = OPERANDS[op]
        op_ip = ip          # slot index of the opcode itself
        arg_ips = list(range(ip + 1, ip + 1 + count))
        args = code[ip + 1: ip + 1 + count]
        ip += 1 + count

        if op == 0:  # FUNC_DECL
            fn = ident_map.get(arg_ips[0], args[0])
            ns = ident_map.get(arg_ips[1], args[1])
            pkg = ident_map.get(arg_ips[2], args[2])
            has_body = args[3]
            end_ip = args[4]
            argc = args[5]
            arg_names = [ident_map.get(ip + i, code[ip + i]) for i in range(argc)]
            ip += argc
            lines.append(f"{op_ip:6d}  FUNC_DECL {ns}::{fn}({', '.join(map(str, arg_names))}) argc={argc} endIp={end_ip}")
            continue

        rendered = []
        for j, a in enumerate(args):
            if op in CALL_OPCODES and j < 2:
                s = ident_map.get(arg_ips[j])
                rendered.append(repr(s) if s is not None else f"IDENT@{arg_ips[j]}")
            else:
                rendered.append(resolve(d, op, ident_map, arg_ips[j], a))
        label = f"  {name}"
        if rendered:
            label += " " + ", ".join(rendered)
        lines.append(f"{op_ip:6d}  {label}")

        if max_lines and len(lines) >= max_lines:
            lines.append("... (truncated)")
            break
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    func_filter = sys.argv[2] if len(sys.argv) > 2 else None
    max_lines = int(sys.argv[3]) if len(sys.argv) > 3 else None
    with open(path, "rb") as f:
        data = f.read()
    print(disassemble(data, func_filter, max_lines))


if __name__ == "__main__":
    main()
