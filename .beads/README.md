# beads (xr)

issue ledger for this repo. prefix **`xr`**.

`br` (this host: **0.5.11**) is the only interface. `bd` and `dolt` are
deliberately uninstalled here — do not install them, and do not hand-edit
`issues.jsonl` while sqlite is live.

| | |
|---|---|
| truth | `.beads/beads.db` (sqlite, local — the binary is not committed) |
| committed | `issues.jsonl`, `config.yaml`, `metadata.json`, `.gitignore`, this file |

`br` auto-flushes `issues.jsonl` on every mutation; run `br sync --flush-only`
before committing so the committed mirror matches sqlite. Never hand-edit it
while sqlite is live — export over it, or `br sync` will disagree.

```sh
br where                  # resolves .beads by walking up from cwd
br ready --json           # claimable front
br create -t task "…" --json
br update <id> --claim --json
br close <id> -r "reason" --json
br sync --flush-only      # optional jsonl mirror refresh
br doctor health --json   # expect healthy, schema 17/17
```

No daemon, no remote: direct mode only.

## gotcha: discovery walks up from the cwd

`br where` searches upward and uses the nearest `.beads/`. From this repo (or
any subdirectory, e.g. `experiments/monado-viture/`) that is the `xr` store.
From a directory with no store above it — `~`, `/tmp` — `br` errors with
`Beads not initialized` instead of guessing.

That error is the good outcome. The failure mode it prevents is real: a stray
`/home/sf/.beads` used to exist, and a session that ran `br create` with
cwd `$HOME` wrote its bead into that orphan ledger (one closed bead,
`br-z6n` "cpa-hdu.1") rather than into any project's board. Check `br where`
before the first mutation of a session.
