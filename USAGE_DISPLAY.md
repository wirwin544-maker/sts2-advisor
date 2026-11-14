# Claude usage display (5-hour and 7-day)

The Spire Oracle overlay now includes a **Claude limits** line and a **Usage** button.
The Usage button opens [Claude's official usage page](https://claude.ai/settings/usage),
which is the authoritative live account reading.

## Where the numbers come from

Claude Code sends verified `rate_limits.five_hour` and `rate_limits.seven_day`
usage percentages plus reset timestamps to **interactive Claude Code** custom
status-line commands. This is supported for eligible Pro/Max/Ultra accounts after
an API response. Spire Oracle's background `claude -p` calls **do not expose
these percentages**. The overlay cannot independently query a live total.

The included optional helper captures those official status-line values into
`runtime/claude_usage.json`, storing only: a timestamp, utilized percentages,
and reset times. It does **not** read OAuth credentials or make any network
requests. The overlay shows percentage used, percentage remaining, reset time,
and age of the last successful snapshot. Readings older than 5 minutes are
prominently marked **STALE**, not represented as current. Expired windows are
never shown with their pre-reset percentages.

**While gaming exclusively through Spire Oracle, the official snapshot may
become stale.** To refresh the snapshot, use an interactive Claude Code session
or the Usage button. Running `/usage` within Claude Code presents live limits
but does not directly feed the overlay unless the status-line hook receives a
new interactive status-line event.

## Opt in to the status-line bridge (Windows)

From the repository root in PowerShell:

```powershell
python .\tools\install_usage_statusline.py
```

The installer edits only `%USERPROFILE%\.claude\settings.json`, backing it up
first when it exists. Other Claude settings are retained. If you already have a
custom `statusLine`, the installer **refuses to overwrite it**. Review your
existing status line before deliberately replacing it with:

```powershell
python .\tools\install_usage_statusline.py --replace
```

To test:

1. Open a **new interactive** Claude Code terminal with `claude` (not `claude -p`).
2. Send a normal question. After Claude replies, the configured status line
   should capture the current rate-limit windows. You can use `/usage` to
   compare against the authoritative status.
3. Check `runtime\claude_usage.json` and restart Spire Oracle, or allow the overlay
   5 seconds to refresh. The file is ignored by Git and has no secrets.

If your account is billed by API key, the CLI does not provide Pro/Max subscription
percentages; the overlay correctly displays **unavailable**. For account plans
where a particular window is absent, it is omitted rather than simulated.

The extra `Oracle completed advice this run` count is derived from the locally
saved run journal. It is **not** a quota percentage, may omit discarded/failed
requests, and does not include other Claude applications.

## Tests

```powershell
python -m unittest discover -s tests -v
```