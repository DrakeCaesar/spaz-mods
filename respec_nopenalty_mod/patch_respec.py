#!/usr/bin/env python3
"""
SPAZ Respec "No Data Penalty / No Achievement Fail" patcher.

Patches three TorqueScript (.dso) files in Space Pirates and Zombies:

  1. game/gameScripts/researchScreen.cs.dso
       -> DEBT_GetRespecCost() returns 0 (no data penalty on respec)

  2. game/gameScripts/instanceClasses/storyClasses/sector4/sector4InstanceClasses.cs.dso
       -> S4_FinalBossComplete() grants ACH_NO_RESPEC unconditionally

  3. game/gameScripts/specialists.cs.dso
       -> SpecialistDatablock::GetCurrentLevel() always returns Master (all
          specialists promoted to their highest tier without leveling up)

Usage:
    python3 patch_respec.py "/path/to/Space Pirates and Zombies"

This creates:
    <file>.original  (backup, only if it doesn't already exist)
    <file>.patched   (the patched copy)

The live .dso files are NOT modified by this script. You copy the .patched
files over the live files yourself (with the game closed). See README.md.
"""

import os
import struct
import sys

# ---------------------------------------------------------------------------
# TorqueScript opcode names (order matches Torque2D compiler.h CompiledInstructions)
# ---------------------------------------------------------------------------
OPNAMES = [
    "FUNC_DECL", "CREATE_OBJECT", "ADD_OBJECT", "END_OBJECT",
    "JMPIFFNOT", "JMPIFNOT", "JMPIFF", "JMPIF", "JMPIFNOT_NP", "JMPIF_NP",
    "JMP", "RETURN", "CMPEQ", "CMPGR", "CMPGE", "CMPLT", "CMPLE", "CMPNE",
    "XOR", "MOD", "BITAND", "BITOR", "NOT", "NOTF", "ONESCOMPLEMENT",
    "SHR", "SHL", "AND", "OR", "ADD", "SUB", "MUL", "DIV", "NEG",
    "SETCURVAR", "SETCURVAR_CREATE", "SETCURVAR_ARRAY", "SETCURVAR_ARRAY_CREATE",
    "LOADVAR_UINT", "LOADVAR_FLT", "LOADVAR_STR",
    "SAVEVAR_UINT", "SAVEVAR_FLT", "SAVEVAR_STR",
    "SETCUROBJECT", "SETCUROBJECT_NEW", "SETCUROBJECT_INTERNAL",
    "SETCURFIELD", "SETCURFIELD_ARRAY",
    "LOADFIELD_UINT", "LOADFIELD_FLT", "LOADFIELD_STR",
    "SAVEFIELD_UINT", "SAVEFIELD_FLT", "SAVEFIELD_STR",
    "STR_TO_UINT", "STR_TO_FLT", "STR_TO_NONE",
    "FLT_TO_UINT", "FLT_TO_STR", "FLT_TO_NONE",
    "UINT_TO_FLT", "UINT_TO_STR", "UINT_TO_NONE",
    "LOADIMMED_UINT", "LOADIMMED_FLT", "TAG_TO_STR", "LOADIMMED_STR", "DOCBLOCK_STR",
    "LOADIMMED_IDENT", "CALLFUNC_RESOLVE", "CALLFUNC",
    "ADVANCE_STR", "ADVANCE_STR_APPENDCHAR", "ADVANCE_STR_COMMA", "ADVANCE_STR_NUL",
    "REWIND_STR", "TERMINATE_REWIND_STR", "COMPARE_STR",
    "PUSH", "PUSH_FRAME", "BREAK", "INVALID",
]

# Opcode numeric constants used by the patch.
OP_FUNC_DECL = 0
OP_JMPIFNOT = 5
OP_RETURN = 11
OP_CMPEQ = 12
OP_STR_TO_FLT = 56
OP_UINT_TO_STR = 62
OP_LOADIMMED_UINT = 64
OP_LOADIMMED_FLT = 65
OP_LOADIMMED_STR = 67
OP_CALLFUNC_RESOLVE = 70
OP_SETCURVAR = 34
OP_LOADVAR_FLT = 39
OP_CMPGE = 14


class DSO:
    """Minimal parser for the Torque 2D .dso compiled-script format."""

    def __init__(self, data):
        self.data = data
        self.parse()

    def parse(self):
        d = self.data
        self.version = struct.unpack('<I', d[0:4])[0]
        off = 4
        gl = struct.unpack('<I', d[off:off + 4])[0]; off += 4
        self.gstr = d[off:off + gl]; off += gl
        fl = struct.unpack('<I', d[off:off + 4])[0]; off += 4
        self.fstr = d[off:off + fl]; off += fl

        gfc = struct.unpack('<I', d[off:off + 4])[0]; off += 4
        self.gfloats = [struct.unpack('<d', d[off + i * 8:off + i * 8 + 8])[0]
                        for i in range(gfc)]; off += gfc * 8
        ffc = struct.unpack('<I', d[off:off + 4])[0]; off += 4
        self.ffloats = [struct.unpack('<d', d[off + i * 8:off + i * 8 + 8])[0]
                        for i in range(ffc)]; off += ffc * 8

        self.codeSize = struct.unpack('<I', d[off:off + 4])[0]; off += 4
        self.linePairCount = struct.unpack('<I', d[off:off + 4])[0]; off += 4

        # Decompress the bytecode, recording the file byte offset of each slot.
        self.code = []
        self.slot_off = []
        for _ in range(self.codeSize):
            self.slot_off.append(off)
            b = d[off]; off += 1
            if b == 0xFF:
                self.code.append(struct.unpack('<I', d[off:off + 4])[0]); off += 4
            else:
                self.code.append(b)

        # Line-break pairs.
        self.linePairs = [
            struct.unpack('<II', d[off + i * 8:off + i * 8 + 8])
            for i in range(self.linePairCount)
        ]
        off += self.linePairCount * 8

        # Identifier table: string offset -> list of code-slot IPs to patch.
        ident_count = struct.unpack('<I', d[off:off + 4])[0]; off += 4
        self.idents = []
        for _ in range(ident_count):
            o = struct.unpack('<I', d[off:off + 4])[0]; off += 4
            c = struct.unpack('<I', d[off:off + 4])[0]; off += 4
            ips = [struct.unpack('<I', d[off + i * 4:off + i * 4 + 4])[0]
                   for i in range(c)]; off += c * 4
            self.idents.append((o, ips))

    # -- string helpers ----------------------------------------------------
    def gstr_at(self, off):
        if off >= len(self.gstr):
            return None
        e = self.gstr.find(b'\x00', off)
        return self.gstr[off:e].decode('latin1') if e >= 0 else None

    def fstr_at(self, off):
        if off >= len(self.fstr):
            return None
        e = self.fstr.find(b'\x00', off)
        return self.fstr[off:e].decode('latin1') if e >= 0 else None

    def gstr_offset(self, name):
        return self.gstr.find(name.encode())

    # -- function location -------------------------------------------------
    def func_decl_ip(self, name):
        """Return the code-slot index of the OP_FUNC_DECL for `name`."""
        off = self.gstr_offset(name)
        if off < 0:
            return None
        for ident_off, ips in self.idents:
            if ident_off != off:
                continue
            for ip in ips:
                # fnName ident is at slot ip; the FUNC_DECL opcode is one slot
                # before it.
                if ip - 1 >= 0 and self.code[ip - 1] == OP_FUNC_DECL:
                    return ip - 1
        return None

    def body_start(self, decl_ip):
        """Body start slot for a FUNC_DECL at `decl_ip` (32-bit layout)."""
        argc = self.code[decl_ip + 6]
        return decl_ip + 7 + argc


# ---------------------------------------------------------------------------
# Patches
# ---------------------------------------------------------------------------
def patch_data_penalty(d):
    """Make DEBT_GetRespecCost() return 0 immediately."""
    decl = d.func_decl_ip("DEBT_GetRespecCost")
    if decl is None:
        raise RuntimeError("DEBT_GetRespecCost not found")
    body = d.body_start(decl)

    # Original body begins with: LOADIMMED_FLT 2.0 ; LOADIMMED_FLT 1.0 ; ...
    if d.code[body] != OP_LOADIMMED_FLT or d.code[body + 2] != OP_LOADIMMED_FLT:
        raise RuntimeError(
            f"DEBT_GetRespecCost body at slot {body} has unexpected opcodes "
            f"({d.code[body]}, {d.code[body + 2]}); game may have changed"
        )

    # Replace with: LOADIMMED_UINT 0 ; UINT_TO_STR ; RETURN  (all 1-byte ops)
    return [
        (d.slot_off[body], OP_LOADIMMED_UINT),
        (d.slot_off[body + 1], 0),
        (d.slot_off[body + 2], OP_UINT_TO_STR),
        (d.slot_off[body + 3], OP_RETURN),
    ]


def patch_achievement(d):
    """Make S4_FinalBossComplete() grant ACH_NO_RESPEC unconditionally."""
    decl = d.func_decl_ip("S4_FinalBossComplete")
    if decl is None:
        raise RuntimeError("S4_FinalBossComplete not found")
    body = d.body_start(decl)

    # Find the CALLFUNC_RESOLVE to DEBT_GetRespecCount within the body.
    respec_off = d.gstr_offset("DEBT_GetRespecCount")
    if respec_off < 0:
        raise RuntimeError("DEBT_GetRespecCount not found in string table")

    target_slot = None
    for ident_off, ips in d.idents:
        if ident_off != respec_off:
            continue
        for ip in ips:
            # CALLFUNC_RESOLVE opcode is one slot before its fnName ident (ip).
            if ip - 1 < body or d.code[ip - 1] != OP_CALLFUNC_RESOLVE:
                continue
            # CALLFUNC_RESOLVE layout: opcode, fnName(ip), ns(ip+1), callType(ip+2).
            # Then the check is: STR_TO_FLT, CMPEQ, JMPIFNOT, <target>.
            jmp_ip = ip + 2 + 1 + 1 + 1
            if d.code[jmp_ip] != OP_JMPIFNOT:
                continue
            target_slot = jmp_ip + 1
            break
        if target_slot is not None:
            break

    if target_slot is None:
        raise RuntimeError("could not locate the DEBT_GetRespecCount()==0 check")

    new_target = target_slot + 1  # jump to the instruction right after JMPIFNOT

    # The jump target is stored as a U32 (0xFF + 4 bytes) since it is >= 0xFF.
    if d.data[d.slot_off[target_slot]] != 0xFF:
        raise RuntimeError("unexpected jump-target encoding")
    return [(d.slot_off[target_slot] + 1, new_target)]


def patch_specialists(d):
    """Make SpecialistDatablock::GetCurrentLevel() always return Master."""
    # In GetCurrentLevel the specialist's levelup count is compared against
    # $SPEC_MasterLevelups; if it falls short, a JMPIFNOT skips the
    # "return $SPEC_Level_Master" branch. Redirect that jump to the very next
    # instruction so it always falls through to the Master return.
    off = d.gstr.find(b'$SPEC_MasterLevelups')
    if off < 0:
        raise RuntimeError("$SPEC_MasterLevelups not found")

    target_slot = None
    for ident_off, ips in d.idents:
        if ident_off != off:
            continue
        for ip in ips:
            # Pattern around ident slot ip (the Master threshold reference):
            #   [ip-1]=SETCURVAR [ip+1]=LOADVAR_FLT [ip+2]=SETCURVAR
            #   [ip+4]=LOADVAR_FLT [ip+5]=CMPGE [ip+6]=JMPIFNOT [ip+7]=target
            if ip - 1 < 0 or d.code[ip - 1] != OP_SETCURVAR:
                continue
            if d.code[ip + 1] != OP_LOADVAR_FLT or d.code[ip + 2] != OP_SETCURVAR:
                continue
            if d.code[ip + 4] != OP_LOADVAR_FLT or d.code[ip + 5] != OP_CMPGE:
                continue
            if d.code[ip + 6] != OP_JMPIFNOT:
                continue
            target_slot = ip + 7
            break
        if target_slot is not None:
            break

    if target_slot is None:
        raise RuntimeError("could not locate the specialist level check")

    new_target = target_slot + 1  # instruction right after JMPIFNOT (Master return)

    if d.data[d.slot_off[target_slot]] != 0xFF:
        raise RuntimeError("unexpected jump-target encoding")
    return [(d.slot_off[target_slot] + 1, new_target)]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    game_dir = sys.argv[1]
    targets = [
        os.path.join(game_dir, "game", "gameScripts", "researchScreen.cs.dso"),
        os.path.join(
            game_dir, "game", "gameScripts", "instanceClasses",
            "storyClasses", "sector4", "sector4InstanceClasses.cs.dso",
        ),
        os.path.join(game_dir, "game", "gameScripts", "specialists.cs.dso"),
    ]

    for path in targets:
        if not os.path.isfile(path):
            print(f"ERROR: not found: {path}")
            sys.exit(1)

        with open(path, "rb") as f:
            data = bytearray(f.read())

        d = DSO(bytes(data))
        if d.version != 0x29:
            print(f"WARNING: unexpected DSO version 0x{d.version:x} in {path}")

        # Make a .original backup if one doesn't already exist.
        original_path = path + ".original"
        if not os.path.isfile(original_path):
            with open(original_path, "wb") as f:
                f.write(data)
            print(f"backup -> {os.path.basename(original_path)}")

        # Choose the patch based on filename.
        base = os.path.basename(path)
        if base == "researchScreen.cs.dso":
            edits = patch_data_penalty(d)
            desc = "data penalty (DEBT_GetRespecCost -> 0)"
        elif base == "sector4InstanceClasses.cs.dso":
            edits = patch_achievement(d)
            desc = "ACH_NO_RESPEC always granted"
        elif base == "specialists.cs.dso":
            edits = patch_specialists(d)
            desc = "specialists always Master tier"
        else:
            print(f"SKIP (unexpected file): {path}")
            continue

        # Apply.
        for byte_off, value in edits:
            if 0 <= value < 0xFF:
                data[byte_off] = value
            else:
                # value >= 0xFF is written as a U32 over the existing 0xFF marker's payload.
                data[byte_off:byte_off + 4] = struct.pack('<I', value)

        patched_path = path + ".patched"
        with open(patched_path, "wb") as f:
            f.write(data)

        # Verify the result re-parses and that the length is unchanged.
        d2 = DSO(bytes(data))
        if len(data) != len(d.data):
            print(f"ERROR: size changed for {base} (should be length-preserving)")
            sys.exit(1)

        print(f"patched -> {os.path.basename(patched_path)}  ({desc})")
        print(f"           size {len(data)} bytes (unchanged), version 0x{d2.version:x}")

    print("\nDone. Copy the .patched files over the live .dso files with the game closed.")
    print("See README.md for the exact cp commands and how to revert.")


if __name__ == "__main__":
    main()
