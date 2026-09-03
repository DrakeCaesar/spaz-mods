# SPAZ reverse-engineering notes — what I learned

These are the technical findings from reverse-engineering **Space Pirates and
Zombies** (SPAZ) to patch the respec "data debt" penalty, the `ACH_NO_RESPEC`
achievement, and the specialist leveling. They document the engine, the
compiled-script format, and the specifics of how the three effects are
implemented.

---

## 1. Big picture: where the game logic actually lives

SPAZ is a **Torque 2D** engine game. The key architectural fact (and the main
early trap) is:

> **Game logic is in compiled TorqueScript (`.dso`) files, not in `SpazGame.exe`.**

`SpazGame.exe` is just the engine plus Steam integration. If you open the `.exe`
in Binary Ninja (or any disassembler), you will **not** find the respec logic —
only:

- The Torque 2D engine.
- The standard Steamworks `CSteamAchievements` class (the familiar
  `RequestStats` / `SetAchievement` / `ResetStatsAndAchievements` example code).
- The Steam achievement **API name strings** (`ACH_RETIRE_SPEC`,
  `ACH_NO_RESPEC`, `ACH_COMPLETE_INSANE`, …) packed together in `.rdata`.
- A native `SetAchievement(name)` console function that TorqueScript calls.

So the `.exe` holds *which achievements exist*, but the *decision of when to
grant them* is TorqueScript bytecode in the `.dso` files.

**Consequence:** the right place to patch is the `.dso` files, not the binary.

---

## 2. The three effects and where they live

### Data penalty ("Data Debt" / DEBT system)

File: `game/gameScripts/researchScreen.cs.dso`

- `DEBT_GetRespecCost(%categoryLevel, %points)` computes the respec cost:
  ```
  %points = 2.0 / ((1.0 + %categoryLevel) * %categoryLevel)
  %cost   = %points * $DEBT_BaseRespec
  %cost   = mRound(%cost * mSqrt(%respecCount)
                          * mSqrt(XP_GetCurrentLevel())
                          * GetGeneralDifficultyMult())
  return %cost
  ```
- `DEBT_IncRespecCount` increments the global `$DEBT_RespecCount`.
- `DEBT_ChangeDebt`, `DEBT_OnDataAdded`, `$DEBT_DataCount`, `$DEBT_BaseRespec`
  round out the system. "Data Debt" is what gets paid back as you collect Data.

### No-respec achievement

File:
`game/gameScripts/instanceClasses/storyClasses/sector4/sector4InstanceClasses.cs.dso`

- Function `S4_FinalBossComplete` (runs at game end) does, effectively:
  ```
  SetAchievement("ACH_COMPLETE_ANY")
  if (GetDifficultyLevel() == $Difficulty_Expert)  SetAchievement("ACH_COMPLETE_EXPERT")
  if (GetDifficultyLevel() == $Difficulty_Insane)  SetAchievement("ACH_COMPLETE_INSANE")
  if (DEBT_GetRespecCount() == 0)                  SetAchievement("ACH_NO_RESPEC")
  ```

The "failure" is simply that respecing makes `$DEBT_RespecCount` non-zero, so
the final `if` skips `ACH_NO_RESPEC`.

---

## 3. The Torque 2D `.dso` file format (version `0x29` = 41)

Everything is little-endian. The layout, in order:

| # | Field | Size |
|---|-------|------|
| 1 | `version` | `U32` (`0x29` = 41) |
| 2 | `globalStringLen` | `U32` |
| 3 | global string table | `globalStringLen` bytes of null-terminated strings, packed |
| 4 | `functionStringLen` | `U32` |
| 5 | function string table | `functionStringLen` bytes, packed null-terminated |
| 6 | `globalFloatCount` | `U32` |
| 7 | global floats | `globalFloatCount × F64` (8 bytes each) |
| 8 | `functionFloatCount` | `U32` |
| 9 | function floats | `functionFloatCount × F64` |
| 10 | `codeSize` | `U32` |
| 11 | `lineBreakPairCount` | `U32` |
| 12 | bytecode | compressed (see below) |
| 13 | line-break pairs | `lineBreakPairCount × (U32 ip, U32 line)` |
| 14 | identifier table | `U32 count`, then `count × (U32 stringOffset, U32 n, n × U32 ip)` |

**Two string tables.** Global strings (function names, global variable names,
identifiers) live in the global table. String literals used *inside function
bodies* (e.g. `"ACH_NO_RESPEC"`, `"0"`) live in the function table. `OP_LOADIMMED_STR`
reads from whichever table is current (`functionStrings` inside a function,
`globalStrings` at top level).

**Floats are `F64` (8 bytes)**, not the `F32` used by old TGE. (Confirmed by the
8 function floats in `researchScreen.cs.dso` parsing as clean values `1.0, 0.0,
133.0, 110.0, 100.0, 200.0, 10.0, 32.0`.)

### Bytecode compression

Each code slot is one `U32` worth of data, stored as:

- `1 byte` if the value is `< 0xFF`, else
- `0xFF` marker byte followed by a 4-byte `U32`.

This is what makes offset math tricky: to map a *code slot index* to a *file byte
offset* you must walk the compressed stream slot by slot.

### Identifier table

String references in the bytecode are stored on disk as **0 placeholders**, and
patched at load time. The identifier table at the end of the file maps each
string offset to the list of code-slot IPs that should hold that string:

```
U32 count
repeat count:
  U32 stringOffset
  U32 n
  n × U32 ip        # code[ip] = StringTable->insert(string at offset)
```

This is how you resolve a `SETCURVAR` / `CALLFUNC` operand: it's `0` on disk,
and the identifier table tells you what name it really is. It's also why you
can't just repurpose an identifier operand slot without also fixing the
identifier table.

---

## 4. Opcode set

Opcode order matches Torque2D `compiler.h` `CompiledInstructions`:

```
 0 FUNC_DECL      1 CREATE_OBJECT   2 ADD_OBJECT      3 END_OBJECT
 4 JMPIFFNOT      5 JMPIFNOT        6 JMPIFF          7 JMPIF
 8 JMPIFNOT_NP    9 JMPIF_NP       10 JMP            11 RETURN
12 CMPEQ         13 CMPGR          14 CMPGE          15 CMPLT
16 CMPLE         17 CMPNE          18 XOR            19 MOD
20 BITAND        21 BITOR          22 NOT            23 NOTF
24 ONESCOMPLEMENT 25 SHR           26 SHL            27 AND
28 OR            29 ADD            30 SUB            31 MUL
32 DIV           33 NEG            34 SETCURVAR      35 SETCURVAR_CREATE
36 SETCURVAR_ARRAY 37 SETCURVAR_ARRAY_CREATE
38 LOADVAR_UINT  39 LOADVAR_FLT    40 LOADVAR_STR
41 SAVEVAR_UINT  42 SAVEVAR_FLT    43 SAVEVAR_STR
44 SETCUROBJECT  45 SETCUROBJECT_NEW 46 SETCUROBJECT_INTERNAL
47 SETCURFIELD   48 SETCURFIELD_ARRAY
49 LOADFIELD_UINT 50 LOADFIELD_FLT 51 LOADFIELD_STR
52 SAVEFIELD_UINT 53 SAVEFIELD_FLT 54 SAVEFIELD_STR
55 STR_TO_UINT   56 STR_TO_FLT     57 STR_TO_NONE
58 FLT_TO_UINT   59 FLT_TO_STR     60 FLT_TO_NONE
61 UINT_TO_FLT   62 UINT_TO_STR    63 UINT_TO_NONE
64 LOADIMMED_UINT 65 LOADIMMED_FLT 66 TAG_TO_STR
67 LOADIMMED_STR 68 DOCBLOCK_STR   69 LOADIMMED_IDENT
70 CALLFUNC_RESOLVE 71 CALLFUNC
72 ADVANCE_STR   73 ADVANCE_STR_APPENDCHAR 74 ADVANCE_STR_COMMA
75 ADVANCE_STR_NUL 76 REWIND_STR   77 TERMINATE_REWIND_STR
78 COMPARE_STR   79 PUSH           80 PUSH_FRAME
81 BREAK         82 INVALID
```

### Operand counts (32-bit build = 1-slot identifiers)

| Opcode(s) | Operands | Meaning |
|-----------|----------|---------|
| `FUNC_DECL` (0) | 6 | `fnName, namespace, package, hasBody, endIp, argc` |
| `CREATE_OBJECT` (1) | 5 | `parentObject, structDecl, isInternal, isMessage, failOffset` |
| `ADD_OBJECT` (2) | 1 | `placeAtRoot` |
| `JMPIFFNOT/JMPIFNOT/JMPIFF/JMPIF/JMPIFNOT_NP/JMPIF_NP/JMP` | 1 | jump target |
| `SETCURVAR*` (34–37) | 1 | variable-name identifier |
| `SETCUROBJECT*` (44–46) | 0 | reads the object from the string stack (no operand) |
| `SETCURFIELD*` (47–48) | 1 | field-name identifier |
| `LOADIMMED_UINT/FLT/STR` (64/65/67) | 1 | immediate / float index / string offset |
| `LOADIMMED_IDENT` (69) | 1 | identifier |
| `CALLFUNC_RESOLVE/CALLFUNC` (70/71) | 3 | `funcName, namespace, callType` |
| `ADVANCE_STR_APPENDCHAR` (73) | 1 | char |
| everything else | 0 | operate on the eval stacks |

---

## 5. Key structures

### `OP_FUNC_DECL`

```
[ip+0] OP_FUNC_DECL
[ip+1] fnName        (identifier)
[ip+2] namespace
[ip+3] package
[ip+4] hasBody
[ip+5] endIp         (next top-level statement = jump target)
[ip+6] argc
[ip+7 .. ip+6+argc]  argument names (1 slot each)
body starts at ip+7+argc
... then the compiler appends an extra OP_RETURN after the body
```

So `body_start = decl_ip + 7 + argc`. This is what `spaz_mods.py` uses to
find `DEBT_GetRespecCost`'s body.

### Function call (`OP_CALLFUNC_RESOLVE` / `OP_CALLFUNC`)

```
OP_PUSH_FRAME
<arg> OP_PUSH   <arg> OP_PUSH ...
OP_CALLFUNC_RESOLVE  funcName  namespace  callType
```

- `funcName` and `namespace` are identifier slots.
- `callType` is `FunctionCall` / `MethodCall` / `ParentCall`.
- After the call, an optional conversion (`OP_STR_TO_FLT`, `OP_STR_TO_NONE`,
  etc.) consumes the result.

---

## 6. Gotchas I hit (and how to avoid them)

1. **1-slot vs 2-slot identifiers.** Torque2D 4.0's *source* (64-bit) reserves
   2 slots per identifier (`STEtoCode(...); ip += 2`), but SPAZ is a **32-bit**
   build, so identifiers are **1 slot**. I initially mis-read the header/opcodes
   and got garbage function names until I realized this. Verified empirically by
   the 11-slot repeating pattern of the top-level `$array[...] = ...` init code.

2. **Two string tables, not one.** The `"ACH_*"` literals weren't in the global
   string table — they're in the *function* string table (used only inside
   `S4_FinalBossComplete`). Searching only the global table finds nothing.

3. **`CALLFUNC_RESOLVE` takes 3 operands, not 1.** Forgetting `namespace` and
   `callType` causes the disassembler to drift out of alignment and emit
   spurious `FUNC_DECL`/`?557` lines.

4. **`CREATE_OBJECT` takes 5 operands on 32-bit** (the source shows `ip += 6`
   for 64-bit, but 32-bit is 1-slot parent + 4 scalar flags). Object-creation
   sections are the easiest place to misalign.

5. **Identifier placeholders are 0 on disk.** `SETCURVAR`/`CALLFUNC` operands
   are stored as `0` and resolved via the identifier table. If you repurpose an
   identifier operand slot (e.g. turn `SETCURVAR %x` into `LOADIMMED_UINT`),
   the identifier table will still patch that slot at load time and corrupt it —
   you must either avoid identifier slots or fix the table. My final patch
   sidestepped this entirely by overwriting the function body's *first two
   `LOADIMMED_FLT` instructions* (float-table-index operands, **not**
   identifiers).

6. **Bytecode is compressed.** Jump targets and string offsets `>= 0xFF` are
   stored as `0xFF + U32`. Both my patches were chosen to be **size-preserving**
   (single-byte opcodes for the data patch; a `0xFF+U32` jump target rewritten
   in place for the achievement patch), so no offsets or tables shifted.

7. **`SETCUROBJECT*` takes no operand.** It reads the target object from the
   string stack (the object's id/name was just evaluated). I initially gave it
   a 1-operand count, which desynced field-access disassembly —
   `%this.someField` compiles to `LOADVAR_STR ; SETCUROBJECT ; SETCURFIELD field ;
   LOADFIELD_*`. Field access via `%this.someField` is the common pattern to
   recognize when disassembling method bodies.

---

## 7. The actual patches

### Data penalty (`researchScreen.cs.dso`)

Overwrite the first 4 slots of `DEBT_GetRespecCost`'s body (originally
`LOADIMMED_FLT 2.0 ; LOADIMMED_FLT 1.0`) with:

```
LOADIMMED_UINT 0     ; push int 0
UINT_TO_STR          ; -> "0"
RETURN               ; return "0"
```

The rest of the body becomes dead code. All four values are `< 0xFF`, so each is
a 1-byte write — no size change, no identifier-table fix needed.

### Achievement (`sector4InstanceClasses.cs.dso`)

In `S4_FinalBossComplete`, the check compiles to:

```
LOADIMMED_FLT 0.0
PUSH_FRAME ; CALLFUNC_RESOLVE DEBT_GetRespecCount ; STR_TO_FLT
CMPEQ
JMPIFNOT <skip>       ; skip SetAchievement if respec count != 0
... SetAchievement("ACH_NO_RESPEC") ...
<skip>: RETURN
```

Change the `JMPIFNOT` target from `<skip>` to the **next instruction** (the
`SetAchievement` block). Now both branches fall through to the grant, so
`ACH_NO_RESPEC` is always awarded.

### Specialists always Master (`specialists.cs.dso`)

Specialists have a level (`Rookie` / `Veteran` / `Master`) that gates their stat
bonuses. `SpecialistDatablock::GetCurrentLevel()` computes it:

```
%currentCount = %this.specLevelupCount
if (%currentCount >= $SPEC_MasterLevelups)   return $SPEC_Level_Master
if (%currentCount >= $SPEC_VeteranLevelups)  return $SPEC_Level_Veteran
return $SPEC_Level_Rookie
```

The thresholds live in globals `$SPEC_MasterLevelups` / `$SPEC_VeteranLevelups`
(set in the init code); the levelup counter is the datablock field
`specLevelupCount` (incremented by `IncLevelupCount`, applied by `OnLevelup`).

The patch redirects the first `JMPIFNOT` (the Master check) to the **next
instruction** — i.e. the `return $SPEC_Level_Master` branch — so the function
always returns Master regardless of `specLevelupCount`. Same size-preserving
`0xFF+U32` jump-target rewrite as the achievement patch.

Key strings: `$MaxSpecLevel`, `$SPEC_Level_Rookie/Veteran/Master`,
`$SPEC_MasterLevelups`, `$SPEC_VeteranLevelups`, `specLevelupCount`,
`SPEC_Activate` (activates a specialist), `SPEC_OnLevelup` (global levelup hook),
`SPEC_UpdateBoostCharacteristics` (applies active specialists' bonuses).

### Specialist capacity 99 (`specialists.cs.dso`)

Total specialist capacity is the global `$MaxSpecialists` array, keyed by
mothership level. The init code writes:

```
$MaxSpecialists["0"] = 0
$MaxSpecialists["1"] = 0
$MaxSpecialists["2"] = 4
$MaxSpecialists["3"] = 8
$MaxSpecialists["4"] = 12
```

Each line compiles to `LOADIMMED_UINT <value> ; LOADIMMED_IDENT $MaxSpecialists ;
ADVANCE_STR ; LOADIMMED_STR "<key>" ; REWIND_STR ; SETCURVAR_ARRAY_CREATE ;
SAVEVAR_UINT ; UINT_TO_NONE`. The patch overwrites the five `LOADIMMED_UINT`
immediates with `99` (all `< 0xFF`, so single-byte, size-preserving writes).

The *active* count is a separate array `$SPECMAN_Max` (`0,0,1,2,3`) and is
deliberately left unchanged — this mod raises only the total capacity, not the
number of simultaneously active specialists.

---

## 8. Useful reference strings / offsets (current build)

- DSO version: `0x29` (41).
- Achievement API names (`.exe` `.rdata`, packed): `ACH_RETIRE_SPEC`,
  `ACH_MAX_SPEC`, `ACH_CLEAN_SWEEP`, `ACH_HARD_WARPGATE`, `ACH_NO_RESPEC`,
  `ACH_COMPLETE_INSANE`, `ACH_COMPLETE_EXPERT`, `ACH_COMPLETE_ANY`,
  `ACH_ESCAPE_EARTH`, … (full list in the executable).
- `SetAchievement` / `ResetStatsAndAchievements` / `StoreStats` /
  `RequestStats` are Steam API method names visible as strings in the `.exe`
  (from the standard Steamworks example class).

If Steam updates the game, the bytecode layout may shift; `spaz_mods.py`
verifies expected opcodes before writing and errors out rather than corrupting
anything.
