#!/usr/bin/env python3
"""
SPAZ mod manager — patches, applies, and reverts TorqueScript (.dso) mods.

Each modded file has a known SHA-256 checksum for its original (unpatched) and
patched states. The tool only patches when the original checksum matches, and it
can report whether the live game files are patched, original, or modified.

Commands:
    status  [game_dir]   Show whether each file is patched, original, or modified.
    patch   [game_dir]   Build the patched files in store/ from the originals.
    apply   [game_dir]   Copy the patched files over the live game files.
    revert  [game_dir]   Restore the original files over the live game files.

If game_dir is omitted it defaults to the directory that contains this script.

store/ (next to this script) holds the pristine originals and the generated
patched copies, so the game folder itself stays clean.
"""

import hashlib
import os
import struct
import sys

# ---------------------------------------------------------------------------
# TorqueScript opcode names (Torque2D compiler.h CompiledInstructions order)
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

# Opcode numeric constants.
OP_FUNC_DECL = 0
OP_JMPIFNOT = 5
OP_RETURN = 11
OP_CMPEQ = 12
OP_CMPGE = 14
OP_SETCURVAR = 34
OP_LOADVAR_FLT = 39
OP_STR_TO_FLT = 56
OP_UINT_TO_STR = 62
OP_LOADIMMED_UINT = 64
OP_LOADIMMED_FLT = 65
OP_LOADIMMED_STR = 67
OP_CALLFUNC_RESOLVE = 70


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

        self.code = []
        self.slot_off = []
        for _ in range(self.codeSize):
            self.slot_off.append(off)
            b = d[off]; off += 1
            if b == 0xFF:
                self.code.append(struct.unpack('<I', d[off:off + 4])[0]); off += 4
            else:
                self.code.append(b)

        self.linePairs = [
            struct.unpack('<II', d[off + i * 8:off + i * 8 + 8])
            for i in range(self.linePairCount)
        ]
        off += self.linePairCount * 8

        ident_count = struct.unpack('<I', d[off:off + 4])[0]; off += 4
        self.idents = []
        for _ in range(ident_count):
            o = struct.unpack('<I', d[off:off + 4])[0]; off += 4
            c = struct.unpack('<I', d[off:off + 4])[0]; off += 4
            ips = [struct.unpack('<I', d[off + i * 4:off + i * 4 + 4])[0]
                   for i in range(c)]; off += c * 4
            self.idents.append((o, ips))

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

    def func_decl_ip(self, name):
        off = self.gstr_offset(name)
        if off < 0:
            return None
        for ident_off, ips in self.idents:
            if ident_off != off:
                continue
            for ip in ips:
                if ip - 1 >= 0 and self.code[ip - 1] == OP_FUNC_DECL:
                    return ip - 1
        return None

    def body_start(self, decl_ip):
        argc = self.code[decl_ip + 6]
        return decl_ip + 7 + argc


# ---------------------------------------------------------------------------
# Patches — each returns a list of (byte_offset, value) edits.
# ---------------------------------------------------------------------------
def patch_data_penalty(d):
    """Make DEBT_GetRespecCost() return 0 immediately."""
    decl = d.func_decl_ip("DEBT_GetRespecCost")
    if decl is None:
        raise RuntimeError("DEBT_GetRespecCost not found")
    body = d.body_start(decl)

    if d.code[body] != OP_LOADIMMED_FLT or d.code[body + 2] != OP_LOADIMMED_FLT:
        raise RuntimeError(
            f"DEBT_GetRespecCost body at slot {body} has unexpected opcodes "
            f"({d.code[body]}, {d.code[body + 2]}); game may have changed"
        )

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

    respec_off = d.gstr_offset("DEBT_GetRespecCount")
    if respec_off < 0:
        raise RuntimeError("DEBT_GetRespecCount not found in string table")

    target_slot = None
    for ident_off, ips in d.idents:
        if ident_off != respec_off:
            continue
        for ip in ips:
            if ip - 1 < body or d.code[ip - 1] != OP_CALLFUNC_RESOLVE:
                continue
            jmp_ip = ip + 2 + 1 + 1 + 1
            if d.code[jmp_ip] != OP_JMPIFNOT:
                continue
            target_slot = jmp_ip + 1
            break
        if target_slot is not None:
            break

    if target_slot is None:
        raise RuntimeError("could not locate the DEBT_GetRespecCount()==0 check")

    new_target = target_slot + 1
    if d.data[d.slot_off[target_slot]] != 0xFF:
        raise RuntimeError("unexpected jump-target encoding")
    return [(d.slot_off[target_slot] + 1, new_target)]


def patch_specialist_master(d):
    """Make SpecialistDatablock::GetCurrentLevel() always return Master."""
    off = d.gstr.find(b'$SPEC_MasterLevelups')
    if off < 0:
        raise RuntimeError("$SPEC_MasterLevelups not found")

    target_slot = None
    for ident_off, ips in d.idents:
        if ident_off != off:
            continue
        for ip in ips:
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

    new_target = target_slot + 1
    if d.data[d.slot_off[target_slot]] != 0xFF:
        raise RuntimeError("unexpected jump-target encoding")
    return [(d.slot_off[target_slot] + 1, new_target)]


def patch_specialist_capacity(d):
    """Set specialist capacity ($MaxSpecialists) to 99 at every level."""
    off = d.gstr.find(b'$MaxSpecialists')
    if off < 0:
        raise RuntimeError("$MaxSpecialists not found")
    edits = []
    for ident_off, ips in d.idents:
        if ident_off != off:
            continue
        for ip in ips:
            # A write is: LOADIMMED_UINT(v) ; LOADIMMED_IDENT(arr) ; ...
            # The value is the immediate of LOADIMMED_UINT, at slot ip-2.
            if ip - 3 >= 0 and d.code[ip - 3] == OP_LOADIMMED_UINT:
                edits.append((d.slot_off[ip - 2], 99))
    if not edits:
        raise RuntimeError("could not locate $MaxSpecialists writes")
    return edits


def patch_specialists(d):
    """Combined specialist tweaks: always Master tier + 99 capacity."""
    return patch_specialist_master(d) + patch_specialist_capacity(d)


# ---------------------------------------------------------------------------
# Manifest — each entry has the game-relative path, known checksums, and the
# patch function that transforms the original into the patched file.
# ---------------------------------------------------------------------------
FILES = [
    {
        "name": "researchScreen.cs.dso",
        "title": "Free Respec",
        "path": "game/gameScripts/researchScreen.cs.dso",
        "desc": "Respecing a research tree costs no Data.",
        "original": "e3ba3596b9e0f08e23806d2715e407841683e742e4c89994284dc5ab2214422a",
        "patched": "3b2caae8fcfcd84185020d89536bbf111e15ababb9cbf425843f04b95074ca98",
        "patch_fn": patch_data_penalty,
    },
    {
        "name": "sector4InstanceClasses.cs.dso",
        "title": "Single Minded",
        "path": "game/gameScripts/instanceClasses/storyClasses/sector4/sector4InstanceClasses.cs.dso",
        "desc": "The Single Minded achievement is always granted, even if you respec.",
        "original": "acbb641da52d36825de0480f0ff996df97b25591deaed7e7b8af8bc8eb49067f",
        "patched": "b2cea5e4afdd1305dc29ecd3945baeb56cc58df0db20f38881877e8f5ac1452e",
        "patch_fn": patch_achievement,
    },
    {
        "name": "specialists.cs.dso",
        "title": "Specialist Tweaks",
        "path": "game/gameScripts/specialists.cs.dso",
        "desc": "Specialists are always Master tier, and you can hold up to 99.",
        "original": "4ce318785ccd0f9c582c453c146283ea39158b50e3555e373ad8654ca8c03449",
        "patched": "c3a5546b77dbae4a172883872d8388ac9127135b1748da64bdaf5a070a3db402",
        "patch_fn": patch_specialists,
    },
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STORE_DIR = os.path.join(SCRIPT_DIR, "store")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    with open(path, "rb") as f:
        return f.read()


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def store_path(entry, suffix):
    return os.path.join(STORE_DIR, entry["name"] + suffix)


def apply_edits(original_bytes, patch_fn):
    """Apply a patch function to the original bytes and return the result."""
    d = DSO(original_bytes)
    edits = patch_fn(d)
    data = bytearray(original_bytes)
    for byte_off, value in edits:
        if 0 <= value < 0xFF:
            data[byte_off] = value
        else:
            data[byte_off:byte_off + 4] = struct.pack('<I', value)
    return bytes(data)


def classify(h):
    """Return a human status for a live-file checksum."""
    for entry in FILES:
        if h == entry["patched"]:
            return "PATCHED"
        if h == entry["original"]:
            return "ORIGINAL"
    return "MODIFIED (unknown)"


# ---------------------------------------------------------------------------
# Operations — return lists of (name, message) so the CLI and GUI share logic.
# ---------------------------------------------------------------------------
def get_statuses(game_dir):
    out = []
    for entry in FILES:
        path = os.path.join(game_dir, entry["path"])
        if not os.path.isfile(path):
            out.append((entry["title"], "MISSING"))
            continue
        h = sha256(read(path))
        out.append((entry["title"], classify(h)))
    return out


def run_patch(game_dir):
    out = []
    for entry in FILES:
        name = entry["title"]
        sp_orig = store_path(entry, ".original")
        sp_patch = store_path(entry, ".patched")

        # 1. Ensure we have the original in the store.
        if not os.path.isfile(sp_orig):
            live = os.path.join(game_dir, entry["path"])
            if not os.path.isfile(live):
                out.append((name, "SKIP: no original available (game file missing)"))
                continue
            h = sha256(read(live))
            if h != entry["original"]:
                out.append((name, "SKIP: game file is not the known original (patched/modified?)"))
                continue
            write(sp_orig, read(live))
            out.append((name, "captured original from game"))

        # 2. Verify original checksum.
        orig = read(sp_orig)
        if sha256(orig) != entry["original"]:
            out.append((name, "ERROR: original checksum mismatch"))
            continue

        # 3. Build and verify the patched file.
        patched = apply_edits(orig, entry["patch_fn"])
        if sha256(patched) != entry["patched"]:
            out.append((name, "ERROR: patched checksum mismatch"))
            continue
        write(sp_patch, patched)
        out.append((name, "patched -> store"))
    return out


def run_apply(game_dir):
    out = []
    for entry in FILES:
        name = entry["title"]
        sp_patch = store_path(entry, ".patched")
        if not os.path.isfile(sp_patch):
            out.append((name, "SKIP: no patched file in store (run patch first)"))
            continue
        patched = read(sp_patch)
        if sha256(patched) != entry["patched"]:
            out.append((name, "ERROR: patched checksum mismatch in store"))
            continue
        write(os.path.join(game_dir, entry["path"]), patched)
        out.append((name, "applied"))
    return out


def run_revert(game_dir):
    out = []
    for entry in FILES:
        name = entry["title"]
        sp_orig = store_path(entry, ".original")
        if not os.path.isfile(sp_orig):
            out.append((name, "SKIP: no original in store"))
            continue
        orig = read(sp_orig)
        if sha256(orig) != entry["original"]:
            out.append((name, "ERROR: original checksum mismatch in store"))
            continue
        write(os.path.join(game_dir, entry["path"]), orig)
        out.append((name, "reverted"))
    return out


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------
def cmd_status(game_dir):
    for name, status in get_statuses(game_dir):
        print(f"{name:32s} {status}")


def cmd_patch(game_dir):
    for name, msg in run_patch(game_dir):
        print(f"{name:32s} {msg}")


def cmd_apply(game_dir):
    for name, msg in run_apply(game_dir):
        print(f"{name:32s} {msg}")


def cmd_revert(game_dir):
    for name, msg in run_revert(game_dir):
        print(f"{name:32s} {msg}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    game_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(SCRIPT_DIR)

    commands = {
        "status": cmd_status,
        "patch": cmd_patch,
        "apply": cmd_apply,
        "revert": cmd_revert,
    }
    if command not in commands:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

    if command in ("apply", "revert"):
        print("NOTE: make sure the game is closed before applying/reverting.")
    commands[command](game_dir)


if __name__ == "__main__":
    main()
