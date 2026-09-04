#!/usr/bin/env python3
"""
SPAZ mod manager — patches, applies, and reverts TorqueScript (.dso) mods.

Mods are independent toggles. Several mods may target the same file (the two
specialist tweaks both edit specialists.cs.dso); a file's checksum identifies
exactly which subset is applied. Each mod has a known SHA-256 for its pristine
(original) file, and every enabled-subset has a known combined checksum.

Commands:
    status  [game_dir]                 Show each mod's state (APPLIED / NOT APPLIED).
    patch   [game_dir]                 Capture pristine originals and verify checksums.
    apply   [game_dir] [mod_id ...]    Enable mods (default: all).
    revert  [game_dir] [mod_id ...]    Disable mods (default: all).

If game_dir is omitted it defaults to the directory that contains this script.

store/ (next to this script) holds the pristine originals, so the game folder
itself stays clean.
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


def _find_standalone_string(d, text):
    """Return the gstr offset of a standalone (null-delimited) string, or None."""
    b = text.encode()
    for k in range(len(d.gstr) - len(b) + 1):
        if d.gstr[k:k + len(b)] != b:
            continue
        prev = d.gstr[k - 1] if k > 0 else 0
        nxt = d.gstr[k + len(b)] if k + len(b) < len(d.gstr) else 0
        if prev == 0 and nxt == 0:
            return k
    return None


def patch_hud_font(d, new_size=b'18'):
    """Enlarge the HUD ship-text font (GuiSpaceScrollProfile) so it stays
    legible when the game is upscaled (Special K borderless fullscreen).

    The HUD text (hull / shields / cargo / goons) uses the bitmap font
    "Arial Bold 14"; at higher-than-native resolutions the 14px glyphs get
    stretched and blur. This repoints the profile's fontSize to a larger size.
    """
    prof_off = d.gstr.find(b'GuiSpaceScrollProfile')
    fs_off = d.gstr.find(b'fontSize')
    if prof_off < 0 or fs_off < 0:
        raise RuntimeError("GuiSpaceScrollProfile/fontSize not found")

    imap = {}
    for off, ips in d.idents:
        for ip in ips:
            imap[ip] = off

    def gstr_at(off):
        e = d.gstr.find(b'\x00', off)
        return d.gstr[off:e].decode('latin1') if e >= 0 else None

    # Locate the CREATE_OBJECT that instantiates GuiSpaceScrollProfile.
    # Pattern: LOADIMMED_IDENT 'GuiSpaceScrollProfile' ; PUSH ; CREATE_OBJECT
    create_ip = None
    for ip, off in imap.items():
        if off != prof_off:
            continue
        if ip - 1 < 0 or d.code[ip - 1] != 69:  # LOADIMMED_IDENT
            continue
        if ip + 2 < len(d.code) and d.code[ip + 1] == 79 and d.code[ip + 2] == 1:
            create_ip = ip + 2
            break
    if create_ip is None:
        raise RuntimeError("GuiSpaceScrollProfile CREATE_OBJECT not found")

    fail_off = d.code[create_ip + 5]  # CREATE_OBJECT failOffset = object end

    # Find the fontSize '14' LOADIMMED_STR inside this object and repoint it.
    for ip in range(create_ip + 1, min(fail_off, len(d.code))):
        if d.code[ip] != 47:  # SETCURFIELD
            continue
        if imap.get(ip + 1) != fs_off:
            continue
        for j in range(ip - 1, create_ip, -1):
            if d.code[j] != 67:  # LOADIMMED_STR
                continue
            operand = j + 1
            if gstr_at(d.code[operand]) != '14':
                continue
            new_off = _find_standalone_string(d, new_size.decode())
            if new_off is None:
                raise RuntimeError(f"standalone '{new_size.decode()}' string not found")
            # operand is stored compressed (0xFF + U32); write past the marker.
            return [(d.slot_off[operand] + 1, new_off)]
    raise RuntimeError("fontSize '14' not found in GuiSpaceScrollProfile")


def patch_resolution_cap(d, max_x=3840, max_y=2160):
    """Raise the game's resolution cap ($maxResX/$maxResY) from 1920x1200."""
    edits = []
    for name, new_val in ((b'$maxResX', max_x), (b'$maxResY', max_y)):
        off = d.gstr.find(name)
        if off < 0:
            raise RuntimeError(f"{name.decode()} not found")
        found = False
        for ident_off, ips in d.idents:
            if ident_off != off:
                continue
            for ip in ips:
                if ip - 1 < 0 or d.code[ip - 1] != 35:  # SETCURVAR_CREATE
                    continue
                if ip - 3 < 0 or d.code[ip - 3] != 64:  # LOADIMMED_UINT
                    continue
                edits.append((d.slot_off[ip - 2] + 1, new_val))
                found = True
                break
            if found:
                break
        if not found:
            raise RuntimeError(f"{name.decode()} assignment not found")
    return edits


def patch_zoom_scale(d, new_assumed=3360):
    """Change %assumedNormalResX (1680 -> new_assumed) in CreateLevelLayers.
    scaleFactor = currentResX / assumedNormalResX drives the center/min/max zoom
    and the parallax background — the lever the old 'Crisp Scene Scaling' mod
    actually moved. Raising assumedNormalResX lowers scaleFactor, zooming out."""
    off = d.gstr.find(b'%assumedNormalResX')
    if off < 0:
        raise RuntimeError("%assumedNormalResX not found")
    for ident_off, ips in d.idents:
        if ident_off != off:
            continue
        for ip in ips:
            if ip - 1 < 0 or d.code[ip - 1] != 35:  # SETCURVAR_CREATE
                continue
            if ip - 3 < 0 or d.code[ip - 3] != 64:  # LOADIMMED_UINT
                continue
            if d.code[ip - 2] != 1680:
                raise RuntimeError("expected 1680, got %d" % d.code[ip - 2])
            return [(d.slot_off[ip - 2] + 1, new_assumed)]
    raise RuntimeError("%assumedNormalResX assignment not found")


def _rewrite_map(data):
    """Non-size-preserving rewrite: getWords(getRes(),"0","1") -> Canvas.Extent.
    Makes map scene windows use the actual canvas size instead of the capped
    configured resolution, so they center/fill on enlarged displays."""
    import dso_rewrite
    return dso_rewrite.rewrite(data)


def _rewrite_exe_laa(data):
    """Set IMAGE_FILE_LARGE_ADDRESS_AWARE (the '4GB patch') so the 32-bit exe
    can address up to 4GB of RAM instead of 2GB."""
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    chars_off = e_lfanew + 4 + 18  # Characteristics field in the COFF header
    chars = struct.unpack_from("<H", data, chars_off)[0]
    out = bytearray(data)
    struct.pack_into("<H", out, chars_off, chars | 0x0020)
    return bytes(out)


# ---------------------------------------------------------------------------
# Mod registry — each MOD is an independent toggle. Multiple mods may target
# the same file (the two specialist tweaks both edit specialists.cs.dso); the
# combined file checksum depends on which subset is enabled.
# ---------------------------------------------------------------------------
MODS = [
    {
        "id": "free_respec",
        "title": "Free Respec",
        "path": "game/gameScripts/researchScreen.cs.dso",
        "desc": "Respecing a research tree costs no Data.",
        "patch_fn": patch_data_penalty,
    },
    {
        "id": "single_minded",
        "title": "Single Minded Cheat",
        "path": "game/gameScripts/instanceClasses/storyClasses/sector4/sector4InstanceClasses.cs.dso",
        "desc": "The Single Minded achievement is always granted, even if you respec.",
        "patch_fn": patch_achievement,
    },
    {
        "id": "spec_master",
        "title": "Max-Level Specialists",
        "path": "game/gameScripts/specialists.cs.dso",
        "desc": "All specialists are automatically Master tier.",
        "patch_fn": patch_specialist_master,
    },
    {
        "id": "spec_capacity",
        "title": "Specialist Capacity 99",
        "path": "game/gameScripts/specialists.cs.dso",
        "desc": "Hold up to 99 specialists at every mothership level.",
        "patch_fn": patch_specialist_capacity,
    },
    {
        "id": "res_starmap",
        "title": "Galaxy Map Centering",
        "path": "game/gameScripts/starMap.cs.dso",
        "desc": "Galaxy map uses the actual screen size (not the capped 1920x1200), so it centers on larger displays.",
        "rewrite_fn": _rewrite_map,
    },
    {
        "id": "res_galaxygen",
        "title": "Galaxy Gen Centering",
        "path": "game/gameScripts/galaxyGenGui.cs.dso",
        "desc": "Galaxy-generation screen uses the actual screen size. NOTE: known to hang the game at the title->main-menu transition; keep disabled until fixed.",
        "rewrite_fn": _rewrite_map,
    },
    {
        "id": "res_instancewarp",
        "title": "System Map Centering",
        "path": "game/gameScripts/instanceWarp.cs.dso",
        "desc": "Local-system map uses the actual screen size, so it centers on larger displays.",
        "rewrite_fn": _rewrite_map,
    },
    {
        "id": "hud_font",
        "title": "Larger HUD Text",
        "path": "game/gameScripts/guiProfiles.cs.dso",
        "desc": "Increases the ship HUD text (hull/shields/cargo/goons) size from 14px to 18px.",
        "patch_fn": patch_hud_font,
    },
    {
        "id": "zoom_out",
        "title": "Further Zoom Out",
        "path": "game/gameScripts/levelLoading.cs.dso",
        "desc": "Zooms the camera out further by lowering scaleFactor (assumedNormalResX 1680 -> 3360), which enlarges the center/min/max zoom and the parallax background.",
        "patch_fn": patch_zoom_scale,
    },
    {
        "id": "res_cap",
        "title": "Resolution Cap 4K",
        "path": "common/gameScripts/canvas.cs.dso",
        "desc": "Raises the game's resolution cap from 1920x1200 to 3840x2160, so you can select a higher resolution in the launcher instead of upscaling.",
        "patch_fn": patch_resolution_cap,
    },
    {
        "id": "exe_laa",
        "title": "4GB Patch (Large Address Aware)",
        "path": "SpazGame.exe",
        "desc": "Sets the Large Address Aware flag so the 32-bit exe can address up to 4GB of RAM instead of 2GB. (Patches SpazGame.exe, not a .dso file.)",
        "rewrite_fn": _rewrite_exe_laa,
    },
]

# Pristine (unmodded) SHA-256 checksum for each game-relative path.
ORIGINALS = {
    "game/gameScripts/researchScreen.cs.dso":
        "e3ba3596b9e0f08e23806d2715e407841683e742e4c89994284dc5ab2214422a",
    "game/gameScripts/instanceClasses/storyClasses/sector4/sector4InstanceClasses.cs.dso":
        "acbb641da52d36825de0480f0ff996df97b25591deaed7e7b8af8bc8eb49067f",
    "game/gameScripts/specialists.cs.dso":
        "4ce318785ccd0f9c582c453c146283ea39158b50e3555e373ad8654ca8c03449",
    "game/gameScripts/starMap.cs.dso":
        "0b783fe051595c38bf949f5870959dafc3c53781b1daf89946fbcfcc4113e951",
    "game/gameScripts/galaxyGenGui.cs.dso":
        "87165a51b91abd7a23c9fc838a95bb3e92c61309353bbc3a1f7867676a5b7d16",
    "game/gameScripts/instanceWarp.cs.dso":
        "fe0e6cdedd8f808346aacc5fade0f60b8b14d8770f22cd09693f16a8c8b2676b",
    "game/gameScripts/guiProfiles.cs.dso":
        "4b50b9b6765a47d05f2be1d704d15e411d221766e6265862bfe0e72174c0c115",
    "game/gameScripts/levelLoading.cs.dso":
        "12d87621626cc8086a3895d3d9789018cbb93bc1f28902226c53414333bb9105",
    "common/gameScripts/canvas.cs.dso":
        "f97f9342b7c9611460821764670526d97f5746bbff9874ed2e19219cb0082e5f",
    "SpazGame.exe":
        "980c30064f2629d4850c2d19711371aa178c8ae1ce733e397d5058e4ddf8bd1a",
}

# Expected SHA-256 for every enabled-subset of mods on a given path.
# Bit `i` = the i-th mod for that path in MODS order.
#   specialists.cs.dso: bit0 = Max-Level Specialists, bit1 = Capacity 99
#   -> 0b00 original, 0b01 master only, 0b10 capacity only, 0b11 both.
COMBINATIONS = {
    "game/gameScripts/researchScreen.cs.dso": {
        0b0: "e3ba3596b9e0f08e23806d2715e407841683e742e4c89994284dc5ab2214422a",
        0b1: "3b2caae8fcfcd84185020d89536bbf111e15ababb9cbf425843f04b95074ca98",
    },
    "game/gameScripts/instanceClasses/storyClasses/sector4/sector4InstanceClasses.cs.dso": {
        0b0: "acbb641da52d36825de0480f0ff996df97b25591deaed7e7b8af8bc8eb49067f",
        0b1: "b2cea5e4afdd1305dc29ecd3945baeb56cc58df0db20f38881877e8f5ac1452e",
    },
    "game/gameScripts/specialists.cs.dso": {
        0b00: "4ce318785ccd0f9c582c453c146283ea39158b50e3555e373ad8654ca8c03449",
        0b01: "b405a6ba29b0399f6b09003d916fccb99b2f886a3593ddc557cddc016840111f",
        0b10: "8c72d6e59190f4f440a8c0bf79f949c8bad6f773f9d1b0cdd4806dbfdba44cad",
        0b11: "c3a5546b77dbae4a172883872d8388ac9127135b1748da64bdaf5a070a3db402",
    },
    "game/gameScripts/starMap.cs.dso": {
        0b0: "0b783fe051595c38bf949f5870959dafc3c53781b1daf89946fbcfcc4113e951",
        0b1: "e88d1a08edd44f14a53425e8a26dd6510401be63309be5cf300fc075460803a8",
    },
    "game/gameScripts/galaxyGenGui.cs.dso": {
        0b0: "87165a51b91abd7a23c9fc838a95bb3e92c61309353bbc3a1f7867676a5b7d16",
        0b1: "d06be941fb43d44aab5762d3cb17bd034f5b3766046d29f5adcc78beef940595",
    },
    "game/gameScripts/instanceWarp.cs.dso": {
        0b0: "fe0e6cdedd8f808346aacc5fade0f60b8b14d8770f22cd09693f16a8c8b2676b",
        0b1: "e847a52d24f016a471f1e95ac271dda4e1e04fbe0f45c51045e93c45cae5f6ff",
    },
    "game/gameScripts/guiProfiles.cs.dso": {
        0b0: "4b50b9b6765a47d05f2be1d704d15e411d221766e6265862bfe0e72174c0c115",
        0b1: "68ccb1611bcb322e675c8e5e8a82eef09508ddbfab1dc382f512eabf93984f23",
    },
    "game/gameScripts/levelLoading.cs.dso": {
        0b0: "12d87621626cc8086a3895d3d9789018cbb93bc1f28902226c53414333bb9105",
        0b1: "03af24b36b401c5533700c252be0c54db85e7a0ba248f3bbdee14e872f3a358e",
    },
    "common/gameScripts/canvas.cs.dso": {
        0b0: "f97f9342b7c9611460821764670526d97f5746bbff9874ed2e19219cb0082e5f",
        0b1: "5f70eb5de9ab9a4aa8f3c88e3e12e0e4aff8d86ee576300a70646bb5ae79060e",
    },
    "SpazGame.exe": {
        0b0: "980c30064f2629d4850c2d19711371aa178c8ae1ce733e397d5058e4ddf8bd1a",
        0b1: "4f0e107a077cefa9357ded060014155bb5b403701898109004c5507d1fe9ef7b",
    },
}

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


def mods_for_path(path):
    return [m for m in MODS if m["path"] == path]


def bit_for(path, mod_id):
    for i, m in enumerate(mods_for_path(path)):
        if m["id"] == mod_id:
            return i
    raise KeyError(mod_id)


def store_original_path(path):
    return os.path.join(STORE_DIR, os.path.basename(path) + ".original")


def checksum_to_mask(path, h):
    """Map a live-file checksum to the enabled-mod bitmask (None if unknown)."""
    for mask, expected in COMBINATIONS[path].items():
        if h == expected:
            return mask
    return None


def apply_edits(original_bytes, patch_fn):
    """Apply a patch function to bytes and return the result (size-preserving)."""
    d = DSO(original_bytes)
    edits = patch_fn(d)
    data = bytearray(original_bytes)
    for byte_off, value in edits:
        if 0 <= value < 0xFF:
            data[byte_off] = value
        else:
            data[byte_off:byte_off + 4] = struct.pack('<I', value)
    return bytes(data)


def build_bytes(path, mask):
    """Build the file for `path` with exactly the mods in `mask` enabled."""
    data = read(store_original_path(path))
    for i, m in enumerate(mods_for_path(path)):
        if mask & (1 << i):
            if "rewrite_fn" in m:
                data = m["rewrite_fn"](data)
            else:
                data = apply_edits(data, m["patch_fn"])
    return data


def _ensure_original(game_dir, path):
    """Make sure the pristine original for `path` is in the store; return it."""
    sp = store_original_path(path)
    if os.path.isfile(sp):
        orig = read(sp)
        if sha256(orig) != ORIGINALS[path]:
            raise RuntimeError(f"store original for {path} has wrong checksum")
        return orig
    live = os.path.join(game_dir, path)
    if not os.path.isfile(live):
        raise RuntimeError(f"no game file at {path} to capture")
    data = read(live)
    if sha256(data) != ORIGINALS[path]:
        raise RuntimeError(
            f"{path} is not the known pristine original "
            f"(already patched/modified?) — restore the original first"
        )
    write(sp, data)
    return data


def resolve_mods(args):
    """Turn a list of mod ids/titles (empty = all) into a list of mod dicts."""
    if not args:
        return list(MODS)
    by_id = {m["id"]: m for m in MODS}
    by_title = {m["title"].lower(): m for m in MODS}
    out = []
    for a in args:
        m = by_id.get(a) or by_title.get(a.lower())
        if m is None:
            raise RuntimeError(f"unknown mod: {a}")
        out.append(m)
    return out


# ---------------------------------------------------------------------------
# Operations — return lists of (name, message) so the CLI and GUI share logic.
# ---------------------------------------------------------------------------
def get_statuses(game_dir):
    out = []
    seen = {}
    for mod in MODS:
        path = mod["path"]
        if path not in seen:
            live = os.path.join(game_dir, path)
            if not os.path.isfile(live):
                seen[path] = "missing"
            else:
                seen[path] = checksum_to_mask(path, sha256(read(live)))
        state = seen[path]
        title = mod["title"]
        if state == "missing":
            out.append((title, "MISSING"))
        elif state is None:
            out.append((title, "MODIFIED (unknown)"))
        elif state & (1 << bit_for(path, mod["id"])):
            out.append((title, "APPLIED"))
        else:
            out.append((title, "NOT APPLIED"))
    return out


def _toggle(game_dir, mods, enable):
    out = []
    by_path = {}
    for m in mods:
        by_path.setdefault(m["path"], []).append(m)

    for path, ms in by_path.items():
        try:
            _ensure_original(game_dir, path)
        except RuntimeError as e:
            for m in ms:
                out.append((m["title"], f"ERROR: {e}"))
            continue

        live = os.path.join(game_dir, path)
        if os.path.isfile(live):
            cur = checksum_to_mask(path, sha256(read(live)))
        else:
            cur = 0
        if cur is None:
            for m in ms:
                out.append((m["title"], "ERROR: file not in a known state — revert first"))
            continue

        new_mask = cur
        for m in ms:
            bit = 1 << bit_for(path, m["id"])
            new_mask = (new_mask | bit) if enable else (new_mask & ~bit)

        if new_mask == cur:
            verb = "already applied" if enable else "already not applied"
            for m in ms:
                out.append((m["title"], verb))
            continue

        write(live, build_bytes(path, new_mask))
        verb = "applied" if enable else "reverted"
        for m in ms:
            out.append((m["title"], verb))
    return out


def run_apply(game_dir, mods=None):
    return _toggle(game_dir, resolve_mods(mods), True)


def run_revert(game_dir, mods=None):
    return _toggle(game_dir, resolve_mods(mods), False)


def run_patch(game_dir):
    """Capture pristine originals and self-verify every combination checksum."""
    out = []
    for path in ORIGINALS:
        base = os.path.basename(path)
        try:
            _ensure_original(game_dir, path)
        except RuntimeError as e:
            out.append((base, f"ERROR: {e}"))
            continue
        for mask, expected in COMBINATIONS[path].items():
            built = build_bytes(path, mask)
            if sha256(built) != expected:
                out.append((base, f"ERROR: combination {mask:b} checksum mismatch"))
                break
        else:
            out.append((base, "originals captured, combinations verified"))
    return out


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------
def cmd_status(game_dir):
    for name, status in get_statuses(game_dir):
        print(f"{name:28s} {status}")


def cmd_patch(game_dir):
    for name, msg in run_patch(game_dir):
        print(f"{name:28s} {msg}")


def cmd_apply(game_dir, mods):
    for name, msg in run_apply(game_dir, mods):
        print(f"{name:28s} {msg}")


def cmd_revert(game_dir, mods):
    for name, msg in run_revert(game_dir, mods):
        print(f"{name:28s} {msg}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    rest = sys.argv[2:]

    def is_mod(a):
        return any(a == m["id"] or a.lower() == m["title"].lower() for m in MODS)

    game_dir = os.path.dirname(SCRIPT_DIR)
    mods = []
    if rest:
        if is_mod(rest[0]):
            mods = rest
        else:
            game_dir = rest[0]
            mods = rest[1:]

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

    if command in ("apply", "revert"):
        commands[command](game_dir, mods)
    else:
        commands[command](game_dir)


if __name__ == "__main__":
    main()
