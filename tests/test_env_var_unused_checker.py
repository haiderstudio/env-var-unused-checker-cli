"""Tests for env_var_unused_checker-cli. Stdlib unittest only."""

import ast
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "env_var_unused_checker.py"
sys.path.insert(0, str(ROOT / "src"))

import env_var_unused_checker as tool


def run_cli(args, stdin_text=None):
    """Run main() in-process and capture stdout, stderr, exit code."""
    old_stdin = sys.stdin
    out = io.StringIO()
    err = io.StringIO()
    try:
        if stdin_text is not None:
            sys.stdin = io.StringIO(stdin_text)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tool.main(args)
    finally:
        sys.stdin = old_stdin
    return code, out.getvalue(), err.getvalue()


class EnvParsingTests(unittest.TestCase):
    def test_basic_lines(self):
        variables = tool.parse_env_text("API_KEY=abc\nDEBUG=false\n")
        self.assertEqual(variables, [("API_KEY", 1), ("DEBUG", 2)])

    def test_comments_and_blank_lines_skipped(self):
        text = "# a comment\n\nAPI_KEY=abc\n   # indented comment\n"
        self.assertEqual(tool.parse_env_text(text), [("API_KEY", 3)])

    def test_export_prefix(self):
        variables = tool.parse_env_text("export API_KEY=abc\n")
        self.assertEqual(variables, [("API_KEY", 1)])

    def test_empty_value_counts_as_defined(self):
        variables = tool.parse_env_text("API_KEY=\n")
        self.assertEqual(variables, [("API_KEY", 1)])

    def test_bare_key_counts_as_defined(self):
        variables = tool.parse_env_text("FLAG\n")
        self.assertEqual(variables, [("FLAG", 1)])

    def test_quoted_values(self):
        text = 'API_KEY="quoted # not a comment"\nOTHER=\'single\'\n'
        variables = tool.parse_env_text(text)
        self.assertEqual(variables, [("API_KEY", 1), ("OTHER", 2)])

    def test_value_containing_equals(self):
        variables = tool.parse_env_text("CONN=a=b=c\n")
        self.assertEqual(variables, [("CONN", 1)])

    def test_spaces_around_equals(self):
        variables = tool.parse_env_text("API_KEY = spaced\n")
        self.assertEqual(variables, [("API_KEY", 1)])

    def test_inline_comment_after_unquoted_value(self):
        variables = tool.parse_env_text("API_KEY=abc # a note\n")
        self.assertEqual(variables, [("API_KEY", 1)])

    def test_invalid_lines_ignored(self):
        text = "not a line\n123BAD=x\n-kebab=x\nAPI_KEY=ok\n"
        self.assertEqual(tool.parse_env_text(text), [("API_KEY", 4)])

    def test_duplicate_name_first_line_wins(self):
        text = "API_KEY=one\nOTHER=x\nAPI_KEY=two\n"
        variables = tool.parse_env_text(text)
        self.assertEqual(variables, [("API_KEY", 1), ("OTHER", 2)])

    def test_lowercase_and_underscore_names(self):
        text = "_PRIVATE=x\nmy_var=y\n"
        variables = tool.parse_env_text(text)
        self.assertEqual(variables, [("_PRIVATE", 1), ("my_var", 2)])


class StripCommentsTests(unittest.TestCase):
    def test_hash_comment_only_line(self):
        text = "# API_KEY lives here\nx = 1\n"
        stripped = tool.strip_comments(text, ".py")
        self.assertNotIn("API_KEY", stripped)
        self.assertEqual(stripped.count("\n"), 2)

    def test_hash_comment_after_code(self):
        text = 'x = API_KEY  # trailing note\n'
        stripped = tool.strip_comments(text, ".py")
        self.assertIn("API_KEY", stripped)
        self.assertNotIn("trailing", stripped)

    def test_hash_inside_string_kept(self):
        text = 'x = "a#b"\n'
        stripped = tool.strip_comments(text, ".py")
        self.assertIn('"a#b"', stripped)

    def test_slash_comment_only_line(self):
        text = "// API_KEY lives here\nconst a = 1;\n"
        stripped = tool.strip_comments(text, ".js")
        self.assertNotIn("API_KEY", stripped)

    def test_slash_comment_after_code(self):
        text = "const a = API_KEY; // trailing note\n"
        stripped = tool.strip_comments(text, ".js")
        self.assertIn("API_KEY", stripped)
        self.assertNotIn("trailing", stripped)

    def test_url_double_slash_not_a_comment(self):
        text = 'const u = "https://example.com/" + API_KEY;\n'
        stripped = tool.strip_comments(text, ".js")
        self.assertIn("API_KEY", stripped)
        self.assertIn("https://example.com/", stripped)

    def test_division_double_slash_kept_when_unspaced(self):
        text = "const q = total//count;\n"
        stripped = tool.strip_comments(text, ".js")
        self.assertIn("total//count", stripped)

    def test_spaced_double_slash_is_a_comment(self):
        # Known limit, stated in the README: a '//' after whitespace
        # starts a comment, so a division written with spaces around
        # '//' is read as a comment start. Divisions written without
        # spaces (total//count) are kept.
        text = "const q = total // count;\n"
        stripped = tool.strip_comments(text, ".js")
        self.assertNotIn("count", stripped)

    def test_block_comment(self):
        text = "/* API_KEY lives here */\nconst a = 1;\n"
        stripped = tool.strip_comments(text, ".js")
        self.assertNotIn("API_KEY", stripped)
        self.assertEqual(stripped.count("\n"), 2)

    def test_block_comment_spanning_lines(self):
        text = "/* start\nAPI_KEY in the middle\nend */\nconst a = API_KEY;\n"
        stripped = tool.strip_comments(text, ".js")
        self.assertEqual(stripped.count("API_KEY"), 1)
        self.assertEqual(stripped.count("\n"), 4)

    def test_block_comment_markers_inside_string_kept(self):
        text = 'const s = "/* not a comment */";\n'
        stripped = tool.strip_comments(text, ".js")
        self.assertIn("/* not a comment */", stripped)

    def test_html_comment(self):
        text = "<!-- API_KEY -->\n<p>API_KEY</p>\n"
        stripped = tool.strip_comments(text, ".html")
        self.assertEqual(stripped.count("API_KEY"), 1)

    def test_shell_hash_comment(self):
        text = "# API_KEY was here\necho $API_KEY\n"
        stripped = tool.strip_comments(text, ".sh")
        self.assertEqual(stripped.count("API_KEY"), 1)

    def test_escaped_quote_in_string(self):
        text = 'x = "say \\"API_KEY\\" loud"\n'
        stripped = tool.strip_comments(text, ".py")
        self.assertIn("API_KEY", stripped)


class UsageTests(unittest.TestCase):
    def check(self, variables, texts):
        return tool.find_unused(variables, texts)

    def test_os_environ_brackets(self):
        unused = self.check([("API_KEY", 1)],
                            ['x = os.environ["API_KEY"]\n'])
        self.assertEqual(unused, [])

    def test_os_getenv(self):
        unused = self.check([("DATABASE_URL", 1)],
                            ['u = os.getenv("DATABASE_URL")\n'])
        self.assertEqual(unused, [])

    def test_process_env(self):
        unused = self.check([("API_KEY", 1)],
                            ["const k = process.env.API_KEY;\n"])
        self.assertEqual(unused, [])

    def test_dollar_brace_and_plain_dollar(self):
        unused = self.check(
            [("APP_NAME", 1), ("DATABASE_URL", 2)],
            ['echo "Starting ${APP_NAME} with $DATABASE_URL"\n'])
        self.assertEqual(unused, [])

    def test_bare_word_counts(self):
        unused = self.check([("DEBUG", 1)], ["if DEBUG:\n    pass\n"])
        self.assertEqual(unused, [])

    def test_string_literal_counts_as_used(self):
        unused = self.check([("API_KEY", 1)],
                            ['print("API_KEY")\n'])
        self.assertEqual(unused, [])

    def test_longer_name_does_not_use_shorter(self):
        unused = self.check(
            [("DATABASE_URL", 1)],
            ["x = DATABASE_URL_BACKUP\n"])
        self.assertEqual(unused, [("DATABASE_URL", 1)])

    def test_number_suffix_does_not_use_base(self):
        unused = self.check([("API_KEY", 1)], ["x = API_KEY2\n"])
        self.assertEqual(unused, [("API_KEY", 1)])

    def test_case_matters(self):
        unused = self.check([("API_KEY", 1)], ["x = api_key\n"])
        self.assertEqual(unused, [("API_KEY", 1)])

    def test_comment_only_is_unused(self):
        code = tool.strip_comments("# API_KEY was here\n", ".py")
        unused = self.check([("API_KEY", 1)], [code])
        self.assertEqual(unused, [("API_KEY", 1)])

    def test_empty_code_means_all_unused(self):
        unused = self.check([("API_KEY", 1), ("DEBUG", 2)], [""])
        self.assertEqual(unused, [("API_KEY", 1), ("DEBUG", 2)])

    def test_used_in_second_file(self):
        unused = self.check([("API_KEY", 1)],
                            ["nothing here\n", "x = API_KEY\n"])
        self.assertEqual(unused, [])


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_folder_walk_scans_source_extensions_only(self):
        self.write("app.py", "x = API_KEY\n")
        self.write("notes.md", "API_KEY\n")
        self.write("data.json", '{"API_KEY": 1}\n')
        checked, texts, problems = tool.collect_code(
            [str(self.root)], tool.DEFAULT_EXTENSIONS)
        names = {p.name for p in checked}
        self.assertEqual(names, {"app.py"})
        self.assertEqual(problems, [])

    def test_git_and_node_modules_skipped(self):
        self.write(".git/hook.py", "x = API_KEY\n")
        self.write("node_modules/dep/index.js", "API_KEY\n")
        self.write("__pycache__/mod.py", "API_KEY\n")
        self.write("app.py", "x = OTHER\n")
        checked, texts, problems = tool.collect_code(
            [str(self.root)], tool.DEFAULT_EXTENSIONS)
        names = {str(p.relative_to(self.root)) for p in checked}
        self.assertEqual(names, {"app.py"})

    def test_env_files_never_scanned_as_code(self):
        self.write(".env", "API_KEY=abc\n")
        self.write("sub/.env.local", "API_KEY=abc\n")
        self.write("app.py", "x = 1\n")
        checked, texts, problems = tool.collect_code(
            [str(self.root)], tool.DEFAULT_EXTENSIONS)
        names = {p.name for p in checked}
        self.assertEqual(names, {"app.py"})

    def test_no_recursive(self):
        self.write("top.py", "x = 1\n")
        self.write("sub/nested.py", "x = 2\n")
        checked, texts, problems = tool.collect_code(
            [str(self.root)], tool.DEFAULT_EXTENSIONS, recursive=False)
        names = {p.name for p in checked}
        self.assertEqual(names, {"top.py"})

    def test_exclude_pattern(self):
        self.write("app.py", "x = 1\n")
        self.write("generated.py", "x = 2\n")
        checked, texts, problems = tool.collect_code(
            [str(self.root)], tool.DEFAULT_EXTENSIONS,
            exclude=["generated.py"])
        names = {p.name for p in checked}
        self.assertEqual(names, {"app.py"})

    def test_direct_file_any_name(self):
        path = self.write("weirdname", "x = API_KEY\n")
        checked, texts, problems = tool.collect_code(
            [str(path)], tool.DEFAULT_EXTENSIONS)
        self.assertEqual([p.name for p in checked], ["weirdname"])
        self.assertEqual(texts, ["x = API_KEY\n"])

    def test_missing_path_is_a_problem(self):
        checked, texts, problems = tool.collect_code(
            [str(self.root / "nope")], tool.DEFAULT_EXTENSIONS)
        self.assertEqual(len(problems), 1)
        self.assertIn("no such file or folder", problems[0].reason)

    def test_non_utf8_and_null_byte_skipped(self):
        binary = self.root / "bad.py"
        binary.write_bytes(b"x = \x00\xff\n")
        good = self.write("good.py", "x = 1\n")
        checked, texts, problems = tool.collect_code(
            [str(self.root)], tool.DEFAULT_EXTENSIONS)
        self.assertEqual(len(problems), 1)
        self.assertIn("bad.py", problems[0].path)
        self.assertEqual(len(texts), 1)

    def test_extensions_override(self):
        self.write("app.py", "x = 1\n")
        self.write("app.txt", "x = 2\n")
        checked, texts, problems = tool.collect_code(
            [str(self.root)], {".txt"})
        names = {p.name for p in checked}
        self.assertEqual(names, {"app.txt"})


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_clean_exit_0(self):
        env = self.write(".env", "API_KEY=x\n")
        self.write("app.py", 'x = os.environ["API_KEY"]\n')
        code, out, err = run_cli([str(env), str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("OK — 1 file(s) checked, all 1 variable(s) are used.",
                      out)

    def test_unused_exit_1(self):
        env = self.write(".env", "API_KEY=x\nDEAD=y\n")
        self.write("app.py", 'x = os.environ["API_KEY"]\n')
        code, out, err = run_cli([str(env), str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("unused variable 'DEAD'", out)
        self.assertIn("Checked 1 file(s), 1 problem(s) in 1 file(s).", out)

    def test_missing_env_file_exit_1(self):
        self.write("app.py", "x = 1\n")
        code, out, err = run_cli([str(self.root / ".env"), str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("cannot read file", out)

    def test_no_args_exit_2(self):
        with self.assertRaises(SystemExit) as caught:
            run_cli([])
        self.assertEqual(caught.exception.code, 2)

    def test_env_only_exit_2(self):
        env = self.write(".env", "API_KEY=x\n")
        with self.assertRaises(SystemExit) as caught:
            run_cli([str(env)])
        self.assertEqual(caught.exception.code, 2)

    def test_stdin(self):
        self.write("app.py", 'x = os.environ["API_KEY"]\n')
        code, out, err = run_cli(["--stdin", str(self.root)],
                                 stdin_text="API_KEY=x\nDEAD=y\n")
        self.assertEqual(code, 1)
        self.assertIn("<stdin>:2: unused variable 'DEAD'", out)

    def test_stdin_clean(self):
        self.write("app.py", "x = API_KEY\n")
        code, out, err = run_cli(["--stdin", str(self.root)],
                                 stdin_text="API_KEY=x\n")
        self.assertEqual(code, 0)
        self.assertIn("all 1 variable(s) are used", out)

    def test_json(self):
        env = self.write(".env", "API_KEY=x\nDEAD=y\n")
        self.write("app.py", 'x = os.environ["API_KEY"]\n')
        code, out, err = run_cli([str(env), str(self.root), "--json"])
        self.assertEqual(code, 1)
        result = json.loads(out)
        self.assertEqual(result["variables_checked"], 2)
        self.assertEqual(result["files_checked"], 1)
        self.assertEqual(len(result["problems"]), 1)
        self.assertEqual(result["problems"][0]["reason"],
                         "unused variable 'DEAD'")
        self.assertEqual(result["files_with_problems"], 1)
        self.assertIn("unused variable 'DEAD'", err)

    def test_version(self):
        with self.assertRaises(SystemExit) as caught:
            run_cli(["--version"])
        self.assertEqual(caught.exception.code, 0)

    def test_extensions_flag(self):
        env = self.write(".env", "API_KEY=x\n")
        self.write("app.txt", "x = API_KEY\n")
        code, out, err = run_cli(
            [str(env), str(self.root), "--extensions", "txt"])
        self.assertEqual(code, 0)
        self.assertIn("1 file(s) checked", out)


class ExampleTests(unittest.TestCase):
    def test_run_example_matches_sample_output(self):
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        sample = (ROOT / "examples" / "sample-output.md").read_text()
        block = sample.split("```text\n")[1].split("```")[0]
        self.assertEqual(result.stdout, block)

    def test_readme_quoted_outputs_are_real(self):
        readme = (ROOT / "README.md").read_text()
        for block in [
            "OK — 3 file(s) checked, all 3 variable(s) are used.",
            "examples/unused.env:3: unused variable 'OLD_TOKEN'",
            "examples/unused.env:5: unused variable 'LEGACY_MODE'",
            "Checked 3 file(s), 2 problem(s) in 1 file(s).",
            "examples/configs/app.env:2: unused variable 'STALE_FLAG'",
            "<stdin>:2: unused variable 'OLD_TOKEN'",
        ]:
            self.assertIn(block, readme, f"README is missing real output: {block!r}")

    def test_readme_json_block_is_real(self):
        # Relative paths, as the README uses them: run from the repo
        # root so the file names in the output match the README.
        old_cwd = os.getcwd()
        try:
            os.chdir(ROOT)
            code, out, err = run_cli(
                ["examples/configs/app.env", "examples/src", "--json"])
        finally:
            os.chdir(old_cwd)
        result = json.loads(out)
        readme = (ROOT / "README.md").read_text()
        block = readme.split("```json\n")[1].split("```")[0]
        self.assertEqual(json.loads(block), result)


class HygieneTests(unittest.TestCase):
    def test_gitignore_first_line_is_env(self):
        lines = (ROOT / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[0], ".env")

    def test_no_banned_words_outside_tests(self):
        banned = ["TODO", "FIXME", "XXX", "lorem", "coming soon"]
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if "tests" in path.parts:
                continue
            text = path.read_text(errors="replace")
            for word in banned:
                self.assertNotIn(word, text,
                                 f"{word} found in {path.relative_to(ROOT)}")

    def test_no_absolute_paths(self):
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if "tests" in path.parts:
                continue
            text = path.read_text(errors="replace")
            self.assertNotIn("/home/hatch", text,
                             f"absolute path in {path.relative_to(ROOT)}")
            self.assertNotIn("/Users/", text,
                             f"absolute path in {path.relative_to(ROOT)}")
            self.assertNotIn("/tmp/", text,
                             f"absolute path in {path.relative_to(ROOT)}")

    def test_stdlib_only_imports(self):
        allowed_src = {
            "argparse", "fnmatch", "json", "os", "re", "sys", "pathlib",
        }
        allowed_tests = allowed_src | {
            "io", "subprocess", "tempfile", "unittest", "ast",
            "contextlib", "os", "env_var_unused_checker",
        }
        for path, allowed in [(SRC, allowed_src),
                              (Path(__file__), allowed_tests)]:
            tree = ast.parse(path.read_text())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imported.add(node.module.split(".")[0])
            self.assertTrue(imported <= allowed,
                            f"{path.name} imports non-stdlib: "
                            f"{imported - allowed}")
            self.assertNotIn("yaml", imported)

    def test_no_yaml_import_in_source(self):
        # The word "yaml" appears in the source as a file extension
        # this tool scans (".yaml", ".yml") — that is not an import.
        # What must never appear is a yaml import.
        text = SRC.read_text()
        self.assertNotIn("import yaml", text)
        self.assertNotIn("from yaml", text)

    def test_no_secrets_in_repo(self):
        # "api_key" is deliberately NOT a marker here: API_KEY is the
        # example variable NAME used throughout, and every value
        # assigned to it in the examples is visibly fake
        # (example-key-123, dead-token-456). Real secret markers only.
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if "tests" in path.parts:
                continue
            text = path.read_text(errors="replace").lower()
            for marker in ["password =", "secret =", "passwd",
                           "ghp_", "gho_", "sk-", "akia"]:
                self.assertNotIn(marker, text,
                                 f"possible secret in {path.relative_to(ROOT)}")


if __name__ == "__main__":
    unittest.main()
