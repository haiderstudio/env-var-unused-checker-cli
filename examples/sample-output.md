```text
OK — 3 file(s) checked, all 3 variable(s) are used.
examples/unused.env:3: unused variable 'OLD_TOKEN'
examples/unused.env:5: unused variable 'LEGACY_MODE'
Checked 3 file(s), 2 problem(s) in 1 file(s).
examples/configs/app.env:2: unused variable 'STALE_FLAG'
Checked 3 file(s), 1 problem(s) in 1 file(s).
```

Output of `sh examples/run-example.sh` — the checker on the bundled examples. It exits 1 on the files with unused variables on purpose; the script itself exits 0.
