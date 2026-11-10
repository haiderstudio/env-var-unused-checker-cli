# env-var-unused-checker-cli

Find env vars defined but never used, fail CI on an unused var.

[![CI](https://github.com/haiderstudio/env-var-unused-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/env-var-unused-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`env_var_unused_checker` reads one `.env` file and one or more
source files or folders, and reports every variable that appears
in no source file — with the variable name and the `.env` line
number. It exits 1 when any variable is unused, so it can fail
a CI run. A clean file exits 0.

- A variable counts as used when its name appears as a whole
  word in the scanned code. `os.environ["API_KEY"]`,
  `os.getenv("API_KEY")`, `process.env.API_KEY`, `${API_KEY}`
  and `$API_KEY` are all the same name to this tool — the access
  style does not matter, only the name.
- A name mentioned only in a comment does **not** count as used.
  Comments are stripped before matching (`#`, `//`, `/* */`,
  `<!-- -->`), so a variable that survives only in a comment is
  reported as unused. A `//` only starts a comment after
  whitespace or one of `;{}(),=` — a URL such as `https://...`
  is left alone. One honest limit: a division written with
  spaces around `//` (`total // count`) is read as a comment
  start; a division written without spaces (`total//count`)
  is kept.
- A name inside a string literal **does** count as used:
  `os.getenv("API_KEY")` is real usage. A name inside a
  docstring counts too — the tool cannot tell a docstring from
  a string literal, and says so here instead of pretending
  otherwise.
- Matching is exact and case-sensitive: `api_key` in code does
  not use `API_KEY` in the `.env` file. A longer name does not
  use a shorter one either: `DATABASE_URL_BACKUP` does not use
  `DATABASE_URL`.
- The `.env` file may use `export`, quoted values, empty values,
  and bare keys (`KEY` with no `=` counts as defined). Comments
  and blank lines are skipped, and a name listed twice is
  checked once, at its first line. A line that is not a
  `VAR=value` assignment is ignored — checking `.env` format
  is dotenv-format-checker-cli's job, not this one.
- A folder is walked for common source extensions (`.py`,
  `.js`, `.ts`, `.sh`, `.go`, `.java`, `.php`, `.rb`, `.html`,
  `.yaml`, `.toml`, and the rest — see `--extensions`),
  recursively by default (`--no-recursive` stops at the top
  level). `.git`, `node_modules`, `__pycache__`, `.venv`,
  `dist`, `build`, and the other skipped folders are never
  walked, and directory links are never followed. `--exclude`
  skips files and folders by name pattern. A file given
  directly is always scanned, whatever its name — except a
  file named `.env*`, which is never treated as code (it
  would match every variable by definition).
- `--json` prints the result as JSON (the human-readable
  lines go to standard error), and `--stdin` reads the
  `.env` file from standard input.

## Who it is for

Anyone with a `.env` file that has grown over time — Python
and JavaScript developers, teams onboarding new developers,
and anyone who has ever been afraid to delete a variable
because nobody knows whether anything still reads it.

## What it does NOT do

- It does not check whether a variable is *missing* from the
  `.env` file — that is repo #3, env-example-sync-cli, which
  checks code → `.env.example` for missing vars. This tool
  checks the other direction: `.env` → code for unused vars.
  Missing and unused are two different checks on the same
  file.
- It does not check `.env` format (bad lines, bad quotes) —
  that is dotenv-format-checker-cli. A malformed line is
  ignored here, not reported.
- It does not check whether a variable's *value* is right, or
  whether a variable is a secret that should not be committed.
  That is a scanner's job, not an unused-var check.
- It does not delete or rewrite anything. It is report-only,
  and it never touches the network.

## How this differs

- gotocartik/unused-env-checker (0 stars) is a small
  JavaScript CLI that does the exact job — one script, one
  test file, no CI. kriskimmerle/envsync (0 stars) is a
  Python checker that finds missing, unused, and
  unprotected variables, and CloudCorpRecords/envdoc (0
  stars) diffs code usage against `.env.example`. All three
  are 0-star tools with no test or CI claim. This tool is
  unused-vars only, one job, with a test suite, per-variable
  file-and-line reporting, comment-aware matching, a folder
  walk, and a CI exit code.
- There is no exact-name rival: a GitHub search for
  `"env-var-unused-checker-cli"` returns 0 results
  (checked Nov 8, 2026).

## Install

Python 3.10 or newer, nothing else to install.

```sh
git clone https://github.com/haiderstudio/env-var-unused-checker-cli.git
cd env-var-unused-checker-cli
```

## Usage

Check a clean file:

```sh
python3 src/env_var_unused_checker.py examples/example.env examples/src
```

```text
OK — 3 file(s) checked, all 3 variable(s) are used.
```

Check a file with unused variables:

```sh
python3 src/env_var_unused_checker.py examples/unused.env examples/src
```

```text
examples/unused.env:3: unused variable 'OLD_TOKEN'
examples/unused.env:5: unused variable 'LEGACY_MODE'
Checked 3 file(s), 2 problem(s) in 1 file(s).
```

The exit code is 1, so a CI run fails. `OLD_TOKEN` and
`LEGACY_MODE` appear only in comments in the sample code —
`OLD_TOKEN` in a Python `#` comment, `LEGACY_MODE` in a
JavaScript `//` comment — so they do not count as used.

Check a second file in a subfolder:

```sh
python3 src/env_var_unused_checker.py examples/configs/app.env examples/src
```

```text
examples/configs/app.env:2: unused variable 'STALE_FLAG'
Checked 3 file(s), 1 problem(s) in 1 file(s).
```

Check a `.env` file from standard input:

```sh
printf 'API_KEY=x\nOLD_TOKEN=y\n' | python3 src/env_var_unused_checker.py --stdin examples/src
```

```text
<stdin>:2: unused variable 'OLD_TOKEN'
Checked 3 file(s), 1 problem(s) in 1 file(s).
```

Machine-readable output:

```sh
python3 src/env_var_unused_checker.py examples/configs/app.env examples/src --json
```

```json
{
  "variables_checked": 2,
  "files_checked": 3,
  "problems": [
    {
      "file": "examples/configs/app.env",
      "line": 2,
      "reason": "unused variable 'STALE_FLAG'"
    }
  ],
  "files_with_problems": 1
}
```

## Examples

- `examples/example.env` — a clean `.env` file. Passes.
- `examples/unused.env` — two unused variables: `OLD_TOKEN`
  and `LEGACY_MODE`, each mentioned only in a comment in the
  sample code. Fails with exit 1.
- `examples/configs/app.env` — one unused variable in a
  subfolder. Fails with exit 1.
- `examples/src/app.py`, `examples/src/server.js`,
  `examples/src/deploy.sh` — the sample code the variables
  are checked against: `os.environ` / `os.getenv` in Python,
  `process.env` in JavaScript, `$VAR` in shell.
- `sh examples/run-example.sh` runs the checker on the whole
  `examples/` folder. Its output is in
  `examples/sample-output.md`.

## How it is tested

```sh
python3 tests/test_env_var_unused_checker.py
```

The tests cover: `.env` parsing (export prefix, quoted
values, empty values, bare keys, comments and blank lines,
inline comments, spaces around `=`, values containing `=`,
invalid lines ignored, duplicate names), usage matching
(`os.environ`, `os.getenv`, `process.env`, `${VAR}`, `$VAR`,
bare words, string literals counting as used, longer names
and case differences not matching), comment handling (a
variable only in a `#`, `//`, `/* */`, or `<!-- -->`
comment is unused; code after a comment on the same line
still counts; a `//` inside a URL does not start a
comment), folder walking (extensions only, `.git` and
`node_modules` skipped, `.env` files never scanned as code,
`--no-recursive`, `--exclude`, `--extensions`), `--stdin`,
`--json`, exit codes 0/1/2, unreadable and non-UTF-8 files,
and the bundled examples (the sample output is compared
byte-for-byte against a fresh run, and the outputs quoted
in this README are checked against real runs).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. Checking a
`.env` file against the code is a common idea; the code, the
wording, and the tests are original.
