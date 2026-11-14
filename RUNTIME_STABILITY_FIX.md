Spire Oracle: runtime memory / orb-flicker fix (STS2 v0.107.1 environment)

This updates only Oracle Python code, not the C# STS2MCP mod. It is independent
of the separately provided shop-reopening fix.

FIXES
  1. Avoid duplicate bridge processes / duplicate Claude recommendations.
  2. Give each JSON save a unique temporary file and retry brief Windows
     PermissionError on replacement.
  3. Avoid needlessly resaving the same selected build every 0.3 seconds.
  4. Avoid writing unchanged deck snapshots every poll.
  5. Require three consecutive matching orb readings before using a changed
     queue in a Claude combat prompt. While disputed, pause recommendations.
  6. Display the combat 'waiting' state instead of older text and preserve
     your scroll position when live content changes.
  7. Record process ID in the log and stop duplicating log-handler output.

INSTALL
  1. Save your current run, quit the game and close all running Oracle copies.
     From the active Oracle folder, use stop.bat if necessary.
  2. Extract this ZIP into its own temporary folder.
  3. Double-click INSTALL_ORACLE_FIX.bat.
  4. The installer will refuse to modify an Oracle folder unless it finds both
     data/monster_moves.json and data/reference_cache.json.
  5. It creates backups/<timestamp>/ with originals. The existing runtime/
     directory and config.yaml are never replaced.
  6. Start the game and Oracle normally. After startup there should be only
     one 'bridge.main' process; runtime/advisor.log includes [pid=...].

If the save PermissionError persists, check whether OneDrive/antivirus is
locking files. Moving the complete working installation outside OneDrive can
reduce Windows sync locking. Preserve runtime/ and data/ when relocating.

OFFLINE VALIDATION: 32 Python tests pass. Windows live gameplay is untested.
