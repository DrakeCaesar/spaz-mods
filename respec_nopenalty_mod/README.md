# SPAZ — Respec / Specialist Quality-of-Life mod

This mod patches three things in **Space Pirates and Zombies**:

1. **Removes the Data penalty when respeccing** a research tree. Normally
   `DEBT_GetRespecCost()` charges a "Data Debt" that must be paid back as you
   collect Data. This patch makes the respec cost return `0`.

2. **Disables the "no respec" achievement failure.** Normally the Steam
   achievement `ACH_NO_RESPEC` ("complete the game without respeccing") is only
   granted at game completion if your respec count is still 0. This patch makes
   `ACH_NO_RESPEC` always granted, regardless of how many times you respecced.

3. **Promotes all specialists to their highest tier (Master) automatically.**
   Normally a specialist starts at Rookie and must be kept active and leveled
   up to reach Veteran, then Master (which have better stats). This patch makes
   every specialist report as Master tier, so they get the best bonuses without
   any leveling up.

---

## Files affected

| File | What changed |
|---|---|
| `game/gameScripts/researchScreen.cs.dso` | `DEBT_GetRespecCost()` now returns `0`. |
| `game/gameScripts/instanceClasses/storyClasses/sector4/sector4InstanceClasses.cs.dso` | `S4_FinalBossComplete()` grants `ACH_NO_RESPEC` unconditionally. |
| `game/gameScripts/specialists.cs.dso` | `SpecialistDatablock::GetCurrentLevel()` always returns Master. |

All three files are compiled TorqueScript (`.dso`) bytecode — **not** the
`SpazGame.exe` executable. The game logic lives in these `.dso` files, which is
why the patch edits them directly rather than the binary.

---

## How the patch works (technical)

The `.dso` files use the Torque 2D compiled-script format (version `0x29`):

```
U32 version
U32 globalStringLen  + null-terminated global strings
U32 functionStringLen + null-terminated function strings
U32 globalFloatCount + F64 floats
U32 functionFloatCount + F64 floats
U32 codeSize
U32 lineBreakPairCount
[bytecode: each op is 1 byte (<0xFF) or 0xFF + U32]
[line-break pairs: U32 ip, U32 line]
[identifier table: string offset -> list of code-slot IPs]
```

Identifier/string references inside the bytecode are 1 code-slot wide (32-bit
build). Function declarations (`OP_FUNC_DECL`) are followed by:
`fnName, namespace, package, hasBody, endIp, argc`, then `argc` argument names,
then the body.

All three patches are **size-preserving** (byte-for-byte same file length), so no
offsets or tables shift.

---

## Requirements

- Python 3 (no third-party packages — uses only the standard library).
- The game **must be closed** before running `apply` or `revert`.

---

## Usage

Run `spaz_mods.py` with a command. It defaults the game root to the folder that
contains the script, so you can usually just run it from anywhere.

```bash
python3 respec_nopenalty_mod/spaz_mods.py <command>
```

| Command | What it does |
|---|---|
| `status` | Report whether each file is `ORIGINAL`, `PATCHED`, `MISSING`, or `MODIFIED`. |
| `patch`  | Build the patched files in `store/` from the originals (only if the original checksum matches). |
| `apply`  | Copy the patched files from `store/` over the live game files. |
| `revert` | Restore the original files from `store/` over the live game files. |

Typical workflow (game closed):

```bash
python3 respec_nopenalty_mod/spaz_mods.py status     # see current state
python3 respec_nopenalty_mod/spaz_mods.py patch      # build patched files in store/
python3 respec_nopenalty_mod/spaz_mods.py apply      # put them in the game
# ... play ...
python3 respec_nopenalty_mod/spaz_mods.py revert     # put the originals back
```

### The `store/` folder

`store/` (next to the script) holds the pristine originals (`*.original`) and the
generated patched copies (`*.patched`). The game folder itself stays clean — no
extra files are left next to the live `.dso` files.

Each file's original and patched SHA-256 checksums are recorded in the script,
so `patch`/`apply`/`revert` verify integrity before touching anything. If a file
doesn't match the expected checksum (e.g. a Steam update changed it), the tool
refuses to patch it and reports the mismatch.

---

## Notes / caveats

- **Steam achievements are synced server-side.** If a save already synced a
  "respecced" state to Steam, `ACH_NO_RESPEC` may already be considered lost for
  that save. The patch guarantees it will be granted at future game completions,
  but cannot retroactively un-fail an already-synced state.
- **Specialist tier is computed from `GetCurrentLevel()`.** This patch changes
  only what tier is *reported* (always Master); the internal `specLevelupCount`
  is left alone, so the leveling UI/flow is otherwise untouched. Existing
  specialists will show as Master immediately after loading.
- If the game is updated by Steam, the bytecode layout may change and the patch
  may need re-deriving. The script verifies expected opcodes before writing and
  will refuse to patch (with an error) if they don't match.
- Always keep the `.original` backups.
