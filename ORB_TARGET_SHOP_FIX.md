Slay the Spire 2 v0.107.1 - TWO FIXES

1. Shop reopening (STS2MCP C# mod):
   Save & Quit game and exit Oracle. Open shop/ and run INSTALL_SHOP_FIX.bat.
   The original shop fix failed because its backups were placed INSIDE the
   STS2MCP C# project. The new script moves any old backups to a sibling folder
   such as C:\Users\hunte\STS2MCP-v107-backups, and writes future backups there.
   It then compiles, installs DLL only after success, and leaves game saves alone.
   Default sources: C:\Users\hunte\STS2MCP-v107
   Default game: C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2

   CLI preview: python shop\fix_sts2mcp_shop.py --dry-run
   CLI install: python shop\fix_sts2mcp_shop.py

2. Orb logic and enemy numbering (Oracle Python overlay):
   Open oracle/ and run INSTALL_ORACLE_FIX.bat. Choose the active Oracle folder
   containing data\reference_cache.json and data\monster_moves.json.
   This updates ONLY bridge/combat.py, overlay/overlay.py,
   prompts/combat_prompt.md, and tests/test_coaching.py.
   No settings, local reference data, runtime files or saves are overwritten.

   CLI preview: python oracle\apply_oracle_fix.py "C:\path\to\your active oracle" --dry-run
   CLI install: python oracle\apply_oracle_fix.py "C:\path\to\your active oracle"

New Oracle combat display:
  Enemies shown as Enemy 1: Wriggler (18 HP), Enemy 2: Wriggler (6 HP).
  Internal entity IDs WRIGGLER_0 and WRIGGLER_1 stay internal for validation.
  Cards shown as Card 1, Card 2, ... rather than [0], [1], ...
  Orbs are displayed LEFT to RIGHT. Next orb to evoke is the RIGHTMOST one.
  Dualcast requires Claude to identify that rightmost orb correctly.
  If Claude predicts the wrong orb, the plan is rejected rather than shown.

STS2MCP mod's OrbQueue.Orbs API order is oldest first, which corresponds to
screen RIGHT to LEFT; Oracle reverses it before giving it to Claude. This is
independent of which orb is darkest/strongest.

Tests: 26 Oracle regression tests and 6 C# patcher source tests passed offline.
The STS2MCP build and live combat/merchant behavior have NOT yet been tested on
this user's Windows installation.

Developer note: the previous shop patch copied *.cs source into `STS2MCP-v107/backups`;
.NET's glob compiled that code a second time (37 CS0111 errors). This script
moves the legacy backups to a sibling directory BEFORE running dotnet build.

GitHub repo contains the patch source only. The source workbook stays local.
