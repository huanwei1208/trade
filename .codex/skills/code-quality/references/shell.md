# Shell rules

- Use Bash intentionally and begin executable repository scripts with a valid
  shebang plus `set -euo pipefail` unless documented control flow requires otherwise.
- Quote expansions, use arrays for argv, use `--` before untrusted paths, and avoid
  `eval`, word-splitting command strings, and parsing `ls` output.
- Keep shell as orchestration. Move non-trivial parsing/domain behavior to an owned
  Python/C++/Java module with tests.
- Use `command -v` and actionable failure messages for required tools. Never install
  or download from a read-only check.
- Preserve exit codes deliberately; do not hide failures with broad `|| true`.

Run:

```bash
bash -n <changed scripts>
shellcheck -- <changed scripts>
./trade dev check
```

Test argument forwarding, paths containing spaces/leading dashes, missing tools, and
nonzero child exits when shell behavior changes.
