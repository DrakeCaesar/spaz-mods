# SPAZ — Respec "No Data Penalty / No Achievement Fail" mod

This mod patches two things in **Space Pirates and Zombies**:

1. **Removes the Data penalty when respeccing** a research tree. Normally
   `DEBT_GetRespecCost()` charges a "Data Debt" that must be paid back as you
   collect Data. This patch makes the respec cost return `0`.

2. **Disables the "no respec" achievement failure.** Normally the Steam
   achievement `ACH_NO_RESPEC` ("complete the game without respeccing") is only
   granted at game completion if your respec count is still 0. This patch makes
   `ACH_NO_RESPEC` always granted, regardless of how many times you respecced.

---

## Files affected

| File | What changed |
|---|---|
| `game/gameScripts/researchScreen.cs.dso` | `DEBT_GetRespecCost()` now returns `0`. |
| `game/gameScripts/instanceClasses/storyClasses/sector4/sector4InstanceClasses.cs.dso` | `S4_FinalBossComplete()` grants `ACH_NO_RESPEC` unconditionally. |

Both files are compiled TorqueScript (`.dso`) bytecode — **not** the
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

The two patches are **size-preserving** (byte-for-byte same file length), so no
offsets or tables shift.

---

## Requirements

- Python 3 (no third-party packages — uses only the standard library).
- The game **must be closed** before you copy the patched files over the live
  ones.

---

## Usage

### 1. Generate patched copies

From a terminal, run (pointing at the game root):

```bash
python3 patch_respec.py "/path/to/Space Pirates and Zombies"
```

This creates, for each of the two files:

- `<file>.original` — an unmodified backup (created only if missing).
- `<file>.patched`  — the patched copy.

The live `.dso` files are **not** touched by the script.

### 2. Activate (replace the live files)

With the game closed:

```bash
cp "game/gameScripts/researchScreen.cs.dso.patched" "game/gameScripts/researchScreen.cs.dso"
cp "game/gameScripts/instanceClasses/storyClasses/sector4/sector4InstanceClasses.cs.dso.patched" "game/gameScripts/instanceClasses/storyClasses/sector4/sector4InstanceClasses.cs.dso"
```

### 3. Revert

```bash
cp "game/gameScripts/researchScreen.cs.dso.original" "game/gameScripts/researchScreen.cs.dso"
cp "game/gameScripts/instanceClasses/storyClasses/sector4/sector4InstanceClasses.cs.dso.original" "game/gameScripts/instanceClasses/storyClasses/sector4/sector4InstanceClasses.cs.dso"
```

---

## Notes / caveats

- **Steam achievements are synced server-side.** If a save already synced a
  "respecced" state to Steam, `ACH_NO_RESPEC` may already be considered lost for
  that save. The patch guarantees it will be granted at future game completions,
  but cannot retroactively un-fail an already-synced state.
- If the game is updated by Steam, the bytecode layout may change and the patch
  may need re-deriving. The script verifies expected opcodes before writing and
  will refuse to patch (with an error) if they don't match.
- Always keep the `.original` backups.
