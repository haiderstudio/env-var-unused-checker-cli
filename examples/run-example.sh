#!/bin/sh
# Run the checker on the bundled examples and show the report.
# The checker exits 1 on the files with unused variables; that is
# the point of the examples, so this script exits 0.
cd "$(dirname "$0")/.." || exit 2
python3 src/env_var_unused_checker.py examples/example.env examples/src
python3 src/env_var_unused_checker.py examples/unused.env examples/src || true
python3 src/env_var_unused_checker.py examples/configs/app.env examples/src || true
