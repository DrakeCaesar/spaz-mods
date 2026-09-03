# SPAZ QoL Mod

This is a set of ten independent, toggleable mods for **Space Pirates and
Zombies**:

1. **Free Respec** — removes the Data penalty when respeccing a research tree.
   Normally `DEBT_GetRespecCost()` charges a "Data Debt" that must be paid back
   as you collect Data; this makes the respec cost return `0`.

2. **Single Minded Cheat** — disables the "no respec" achievement failure. Normally
   the Steam achievement `ACH_NO_RESPEC` ("complete the game without
   respeccing") is only granted at game completion if your respec count is
   still 0; this makes `ACH_NO_RESPEC` always granted, regardless of how many
   times you respecced.

3. **Max-Level Specialists** — every specialist is automatically promoted to
   Master tier (the best stats), with no leveling required.

4. **Specialist Capacity 99** — raises the specialist capacity to 99 at every
   mothership level, so you can hold up to 99 specialists at once.

5. **Galaxy Map Centering** — the galaxy map uses the actual screen size
   instead of the capped 1920x1200 resolution, so it centers on displays larger
   than 1080p (e.g. with Special K borderless fullscreen).

6. **Galaxy Gen Centering** — same fix for the galaxy-generation screen.
   *(Known issue: hangs at the title→main-menu transition — leave disabled until fixed.)*

7. **System Map Centering** — same fix for the local-system (warp) map.

8. **Larger HUD Text** — increases the ship HUD text (hull / shields / cargo /
   goons) size from 14px to 18px.

9. **Further Zoom Out** — raises the maximum zoom-out (`%baseMaxZoom` 1.5 →
   3.0) in `CreateLevelLayers`, so you can zoom out further and see more of
   the map.

10. **Resolution Cap 4K** — raises the game's hardcoded resolution cap from
    1920x1200 to 3840x2160, so you can select your native resolution (e.g.
    2560x1440) in the launcher instead of relying on upscaling.

---

## Files affected

| File | Mods |
|---|---|
| `game/gameScripts/researchScreen.cs.dso` | Free Respec — `DEBT_GetRespecCost()` now returns `0`. |
| `game/gameScripts/instanceClasses/storyClasses/sector4/sector4InstanceClasses.cs.dso` | Single Minded Cheat — `S4_FinalBossComplete()` grants `ACH_NO_RESPEC` unconditionally. |
| `game/gameScripts/specialists.cs.dso` | Max-Level Specialists (`GetCurrentLevel()` always Master) **and** Specialist Capacity 99 (`$MaxSpecialists` = 99). |
| `game/gameScripts/starMap.cs.dso` | Galaxy Map Centering — `getWords(getRes(),…)` → `Canvas.Extent`. |
| `game/gameScripts/galaxyGenGui.cs.dso` | Galaxy Gen Centering — same change (known to hang; keep disabled). |
| `game/gameScripts/instanceWarp.cs.dso` | System Map Centering — same change. |
| `game/gameScripts/guiProfiles.cs.dso` | Larger HUD Text — `GuiSpaceScrollProfile` fontSize 14 → 18. |
| `game/gameScripts/levelLoading.cs.dso` | Further Zoom Out — `%baseMaxZoom` 1.5 → 3.0. |
| `common/gameScripts/canvas.cs.dso` | Resolution Cap 4K — `$maxResX`/`$maxResY` 1920×1200 → 3840×2160. |

The two specialist mods edit the **same** file and are fully independent — you
can apply either one, both, or neither. The file's SHA-256 checksum is a
function of *which* subset is applied, so the tool tells them apart (see
[Combination checksums](#combination-checksums) below).

All files are compiled TorqueScript (`.dso`) bytecode — **not** the
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

All patches are **size-preserving** (byte-for-byte same file length), so no
offsets or tables shift.

---

## Combination checksums

`specialists.cs.dso` is shared by two mods, so it has four possible states. The
tool knows all four SHA-256 checksums and uses them to report exactly which
mods are applied (bit `0` = Max-Level Specialists, bit `1` = Capacity 99):

| Enabled | Meaning | SHA-256 |
|---|---|---|
| `00` | original (neither mod) | `4ce318785ccd0f9c582c453c146283ea39158b50e3555e373ad8654ca8c03449` |
| `01` | Max-Level Specialists only | `b405a6ba29b0399f6b09003d916fccb99b2f886a3593ddc557cddc016840111f` |
| `10` | Capacity 99 only | `8c72d6e59190f4f440a8c0bf79f949c8bad6f773f9d1b0cdd4806dbfdba44cad` |
| `11` | both | `c3a5546b77dbae4a172883872d8388ac9127135b1748da64bdaf5a070a3db402` |

## Requirements

- Python 3 (no third-party packages — uses only the standard library).
- The game **must be closed** before running `apply` or `revert`.

---

## GUI

There's a graphical front-end too. Run:

```bash
python3 spaz_qol_mod/spaz_mods_gui.py
```

It shows each file's status (color-coded), lets you pick the game folder, and has
**Patch / Apply / Revert / Refresh** buttons plus a log — same checksum
verification as the CLI, just point-and-click.

---

## Usage

Run `spaz_mods.py` with a command. It defaults the game root to the folder that
contains the script, so you can usually just run it from anywhere.

```bash
python3 spaz_qol_mod/spaz_mods.py <command>
```

| Command | What it does |
|---|---|
| `status` | Report each mod's state: `APPLIED`, `NOT APPLIED`, `MISSING`, or `MODIFIED`. |
| `patch`  | Capture pristine originals into `store/` and verify every combination checksum. |
| `apply [mod ...]`  | Enable mods (default: all). Pass a mod id/title to apply just that one. |
| `revert [mod ...]` | Disable mods (default: all). Pass a mod id/title to revert just that one. |

Mod ids: `free_respec`, `single_minded`, `spec_master`, `spec_capacity`.

Typical workflow (game closed):

```bash
python3 spaz_qol_mod/spaz_mods.py status                  # see current state
python3 spaz_qol_mod/spaz_mods.py apply                   # apply all mods
python3 spaz_qol_mod/spaz_mods.py apply spec_capacity     # apply just one
# ... play ...
python3 spaz_qol_mod/spaz_mods.py revert spec_master      # revert just one
python3 spaz_qol_mod/spaz_mods.py revert                  # revert all
```

### The `store/` folder

`store/` (next to the script) holds the pristine originals (`*.original`). The
game folder itself stays clean — no extra files are left next to the live
`.dso` files.

Patched files are built on the fly from the pristine original plus the selected
mods, so there is no `*.patched` file to keep in sync. Every mod's original
checksum and every enabled-combination checksum are recorded in the script, so
`patch`/`apply`/`revert` verify integrity before touching anything. If a file
doesn't match an expected checksum (e.g. a Steam update changed it), the tool
refuses to patch it and reports the mismatch.

---

## Notes / caveats

- **Steam achievements are synced server-side.** If a save already synced a
  "respecced" state to Steam, `ACH_NO_RESPEC` may already be considered lost for
  that save. The patch guarantees it will be granted at future game completions,
  but cannot retroactively un-fail an already-synced state.
- **Specialist tier is computed from `GetCurrentLevel()`.** The Master mod
  changes only what tier is *reported* (always Master); the internal
  `specLevelupCount` is left alone, so the leveling UI/flow is otherwise
  untouched. Existing specialists show as Master immediately after loading.
- **The Capacity 99 mod raises only the *total* capacity (`$MaxSpecialists`),
  not the number of simultaneously *active* specialists (`$SPECMAN_Max`).**
- If the game is updated by Steam, the bytecode layout may change and the patch
  may need re-deriving. The script verifies expected opcodes before writing and
  will refuse to patch (with an error) if they don't match.
- Always keep the `.original` backups.
