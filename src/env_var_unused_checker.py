"""env-var-unused-checker-cli: find env vars defined in .env but never used in the code.

Reads one .env file and one or more source files or folders, and
reports every variable that appears in no source file, with the
variable name and the .env line number. Report-only: it never
rewrites a file. Exit 0 when every variable is used, 1 when any
variable is unused, 2 for a usage error.

A variable counts as used when its name appears as a whole word
in the scanned code — os.environ["API_KEY"], os.getenv("API_KEY"),
process.env.API_KEY, ${API_KEY} and $API_KEY are all the same
name to this tool. A name mentioned only in a comment does not
count: comments are stripped before matching, so a variable that
survives only in a comment is reported as unused. A name inside
a string literal does count — os.getenv("API_KEY") is real usage.
"""

import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

__version__ = "1.0.0"

DEFAULT_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
    ".sh", ".bash", ".rb", ".go", ".java", ".php", ".rs",
    ".c", ".h", ".cpp", ".hpp", ".cs",
    ".html", ".htm", ".css", ".scss", ".xml",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
}

# Comment styles by file extension. A '#' starts a comment in the
# first group, '//' in the second, and the third group also has
# a block comment form.
HASH_COMMENT_EXTS = {
    ".py", ".sh", ".bash", ".rb", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf",
}
SLASH_COMMENT_EXTS = {
    ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".go", ".java",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".rs", ".scss",
}
BLOCK_COMMENT_EXTS = {
    ".js": ("/*", "*/"), ".ts": ("/*", "*/"), ".jsx": ("/*", "*/"),
    ".tsx": ("/*", "*/"), ".mjs": ("/*", "*/"), ".cjs": ("/*", "*/"),
    ".go": ("/*", "*/"), ".java": ("/*", "*/"), ".c": ("/*", "*/"),
    ".h": ("/*", "*/"), ".cpp": ("/*", "*/"), ".hpp": ("/*", "*/"),
    ".cs": ("/*", "*/"), ".php": ("/*", "*/"), ".rs": ("/*", "*/"),
    ".css": ("/*", "*/"), ".scss": ("/*", "*/"),
    ".html": ("<!--", "-->"), ".htm": ("<!--", "-->"),
    ".xml": ("<!--", "-->"),
}

# Folders never walked when scanning a folder.
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", "target", ".tox", ".pytest_cache",
}

ENV_LINE_RE = re.compile(
    r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?:=(.*))?$")


class Problem:
    """One problem in one file: path, line number, plain reason."""

    def __init__(self, path, line, reason):
        self.path = path
        self.line = line
        self.reason = reason

    def text(self):
        return f"{self.path}:{self.line}: {self.reason}"

    def as_dict(self):
        return {"file": self.path, "line": self.line, "reason": self.reason}


def strip_comments(text, ext):
    """Remove comments from source text, keeping line numbers.

    Line comments and block comments are replaced with spaces, so
    nothing after them on the line moves and line numbers stay
    right. A name inside a string literal is kept — the string is
    real code. A '//' only starts a comment after whitespace or
    one of ;{}(),=, so a URL such as https://... is left alone.
    Known limit: a division written with spaces around '//'
    (total // count) is read as a comment start; a division
    written without spaces (total//count) is kept.
    A docstring mention counts as used: the tool cannot tell a
    docstring from a string literal, and says so in the README.
    """
    line_markers = []
    if ext in HASH_COMMENT_EXTS:
        line_markers.append("#")
    if ext in SLASH_COMMENT_EXTS:
        line_markers.append("//")
    block = BLOCK_COMMENT_EXTS.get(ext)
    out = []
    i, n = 0, len(text)
    state = None  # None, "'", '"', "`", "line", "block"
    while i < n:
        ch = text[i]
        if state == "line":
            if ch == "\n":
                state = None
                out.append(ch)
            else:
                out.append(" ")
            i += 1
            continue
        if state == "block":
            if block and text.startswith(block[1], i):
                out.append(" " * len(block[1]))
                i += len(block[1])
                state = None
            else:
                out.append("\n" if ch == "\n" else " ")
                i += 1
            continue
        if state in ("'", '"', "`"):
            if ch == "\\":
                out.append(ch)
                if i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                else:
                    i += 1
                continue
            if ch == state or (state in ("'", '"') and ch == "\n"):
                out.append(ch)
                state = None
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if block and text.startswith(block[0], i):
            out.append(" " * len(block[0]))
            i += len(block[0])
            state = "block"
            continue
        if "#" in line_markers and ch == "#":
            out.append(" ")
            i += 1
            state = "line"
            continue
        if "//" in line_markers and text.startswith("//", i):
            prev = text[i - 1] if i > 0 else " "
            if prev in " \t\n;{}(),=":
                out.append("  ")
                i += 2
                state = "line"
                continue
        if ch in ("'", '"', "`"):
            state = ch
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def parse_env_text(text):
    """Parse a .env document. Returns a list of (name, lineno).

    First definition wins when a name appears twice. Blank lines
    and '#' comment lines are skipped. A line that is not a
    VAR=value assignment is ignored — checking .env format is
    dotenv-format-checker-cli's job, not this one.
    """
    variables = []
    seen = set()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_LINE_RE.match(line)
        if not match:
            continue
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        variables.append((name, lineno))
    return variables


def read_env_file(path):
    """Read one .env file. Returns (variables, problems)."""
    label = str(path)
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        return [], [Problem(label, 1,
                            f"cannot read file: {exc.strerror or exc}")]
    if b"\x00" in data:
        return [], [Problem(label, 1,
                            "file contains a null byte, not a .env file")]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [], [Problem(label, 1, "file is not valid UTF-8")]
    return parse_env_text(text), []


def read_code_file(path):
    """Read one code file and strip its comments.

    Returns (stripped_text, error). The error is None on success.
    """
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        return None, f"cannot read file: {exc.strerror or exc}"
    if b"\x00" in data:
        return None, "file contains a null byte, not a text file"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, "file is not valid UTF-8"
    return strip_comments(text, path.suffix.lower()), None


def is_env_name(path):
    """True when a file name looks like a .env file."""
    return path.name == ".env" or path.name.startswith(".env.")


def collect_code(paths, extensions, recursive=True, exclude=()):
    """Gather the code files to scan and their stripped text.

    A file given directly is always scanned, whatever its name
    (except a file named .env*, which is never code — it would
    match every variable by definition). A folder is walked for
    files with the chosen extensions, recursively by default.
    Skipped folders are never walked, and directory links are
    never followed.

    Returns (checked, texts, problems): the files checked, their
    comment-stripped text in the same order, and any problems
    (missing paths, unreadable files).
    """
    checked = []
    texts = []
    problems = []
    for given in paths:
        path = Path(given)
        if path.is_file():
            if is_env_name(path):
                continue
            checked.append(path)
            text, error = read_code_file(path)
            if error is not None:
                problems.append(Problem(str(path), 1, error))
            else:
                texts.append(text)
        elif path.is_dir():
            for root, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = [d for d in dirs
                           if d not in SKIP_DIRS
                           and not any(fnmatch.fnmatch(d, pat)
                                       for pat in exclude)]
                for name in sorted(files):
                    candidate = Path(root) / name
                    if candidate.suffix.lower() not in extensions:
                        continue
                    if is_env_name(candidate):
                        continue
                    if any(fnmatch.fnmatch(name, pat) for pat in exclude):
                        continue
                    checked.append(candidate)
                    text, error = read_code_file(candidate)
                    if error is not None:
                        problems.append(Problem(str(candidate), 1, error))
                    else:
                        texts.append(text)
                if not recursive:
                    break
        else:
            problems.append(Problem(str(given), 1, "no such file or folder"))
    return checked, texts, problems


def find_unused(variables, texts):
    """Return the (name, lineno) pairs with no whole-word use."""
    unused = []
    for name, lineno in variables:
        pattern = re.compile(r"\b" + re.escape(name) + r"\b")
        if not any(pattern.search(text) for text in texts):
            unused.append((name, lineno))
    return unused


def parse_extensions(value):
    """Parse a comma-separated extension list into a set."""
    extensions = set()
    for part in value.split(","):
        part = part.strip().lower()
        if not part:
            continue
        if not part.startswith("."):
            part = "." + part
        extensions.add(part)
    return extensions


def main(argv=None):
    """Entry point. Returns the exit code: 0 clean, 1 problems, 2 usage."""
    parser = argparse.ArgumentParser(
        prog="env_var_unused_checker",
        description="Find env vars defined in a .env file but never "
                    "used in the code.")
    parser.add_argument("paths", nargs="*", metavar="PATH",
                        help=".env file first, then the source files or "
                             "folders to scan (with --stdin, every path "
                             "is a source file or folder)")
    parser.add_argument("--stdin", action="store_true",
                        help="read the .env file from standard input")
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON "
                             "(human lines go to standard error)")
    parser.add_argument("--no-recursive", action="store_true",
                        help="do not walk into subfolders")
    parser.add_argument("--exclude", action="append", default=[],
                        metavar="PATTERN",
                        help="skip files and folders matching this name pattern")
    parser.add_argument("--extensions", default=None, metavar="LIST",
                        help="comma-separated file extensions to scan in "
                             "folders, e.g. py,js,sh (default: common "
                             "source extensions)")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if args.stdin:
        if not args.paths:
            parser.error("give at least one file or folder to scan")
        env_label = "<stdin>"
        env_text = sys.stdin.read()
        variables = parse_env_text(env_text)
        env_problems = []
        code_paths = args.paths
    else:
        if len(args.paths) < 2:
            parser.error("give a .env file and at least one file or "
                         "folder to scan")
        env_label = args.paths[0]
        variables, env_problems = read_env_file(args.paths[0])
        code_paths = args.paths[1:]

    extensions = (parse_extensions(args.extensions)
                  if args.extensions else DEFAULT_EXTENSIONS)
    checked, texts, problems = collect_code(
        code_paths, extensions,
        recursive=not args.no_recursive, exclude=args.exclude)
    problems = env_problems + problems

    unused = find_unused(variables, texts)
    for name, lineno in unused:
        problems.append(Problem(
            env_label, lineno, f"unused variable '{name}'"))

    files_with_problems = len({p.path for p in problems})
    if args.json:
        result = {
            "variables_checked": len(variables),
            "files_checked": len(checked),
            "problems": [p.as_dict() for p in problems],
            "files_with_problems": files_with_problems,
        }
        print(json.dumps(result, indent=2))
        for problem in problems:
            print(problem.text(), file=sys.stderr)
    else:
        for problem in problems:
            print(problem.text())
        if problems:
            print(f"Checked {len(checked)} file(s), "
                  f"{len(problems)} problem(s) in {files_with_problems} file(s).")
        else:
            print(f"OK — {len(checked)} file(s) checked, "
                  f"all {len(variables)} variable(s) are used.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
