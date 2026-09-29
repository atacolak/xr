# beads (xr)

issue ledger for this repo. prefix **`xr`**.

`br` (this host: **0.5.11**) is the only interface. `bd` and `dolt` are
deliberately uninstalled here — do not install them, and do not hand-edit
`issues.jsonl` while sqlite is live.

| | |
|---|---|
| truth | `.beads/beads.db` (sqlite, local, not committed) |
| committed | `config.yaml`, `metadata.json`, `.gitignore`, this file |
| local only | `issues.jsonl` mirror (gitignored, as in voicecat / speech-core) |

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

## gotcha: discovery walks up to `$HOME`

`br where` walks up from the cwd. A session started in `~` or `~/workspace`
with no store nearer resolves silently to **`/home/sf/.beads`** (prefix `br`),
not this repo — that is how a mutation lands in the wrong ledger. Run bead
commands from inside the repo, and check `br where` before the first mutation
of a session.
