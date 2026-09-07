"""AST-only preflight checks; runtime isolation remains the mandatory second layer."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any


ALLOWED_IMPORT_ROOTS = {
    "pandas",
    "numpy",
    "scipy",
    "statsmodels",
    "sklearn",
    "matplotlib",
    "seaborn",
    "pyarrow",
    "openpyxl",
    "sandbox_sdk",
    # Required by the generated runtime contract. File/network APIs remain
    # denied below even when these safe standard-library roots are imported.
    "json",
    "pathlib",
}
BANNED_CALLS = {
    "exec", "eval", "compile", "__import__", "open", "input", "globals", "locals",
    "vars", "dir", "getattr", "setattr", "delattr", "breakpoint", "help", "exit", "quit",
}
BANNED_ATTRIBUTES = {
    "system", "popen", "spawn", "fork", "forkserver", "start", "run", "call", "check_call",
    "check_output", "communicate", "connect", "bind", "listen", "send", "recv", "request",
    "urlopen", "urlretrieve", "getenv", "environ", "read_pickle", "to_pickle", "load", "loads",
    "dump", "dumps", "import_module", "reload", "walk", "glob", "rglob", "unlink", "remove",
    "rename", "replace", "chmod", "chown", "symlink", "mkdir", "rmdir", "write_text", "write_bytes",
    "read_text", "read_bytes", "open", "openat", "read_csv", "read_excel", "read_parquet",
    "read_table", "read_fwf", "read_json", "read_html", "read_xml", "ExcelFile", "HDFStore",
    "memmap", "fromfile", "to_csv", "to_excel", "to_parquet", "to_json", "save", "savez",
    "savez_compressed", "savefig", "imsave", "imread",
    "S3FileSystem", "GcsFileSystem", "AzureFileSystem", "HadoopFileSystem",
}
BANNED_ATTRIBUTE_READS = {
    "environ", "environb", "supports_bytes_environ",
}


@dataclass(frozen=True)
class PolicyViolation:
    rule: str
    message: str
    line: int
    column: int


@dataclass(frozen=True)
class PolicyCheckResult:
    allowed: bool
    violations: list[PolicyViolation]
    node_count: int


class CodePolicyViolation(ValueError):
    def __init__(self, violations: list[PolicyViolation]) -> None:
        super().__init__("Generated code violates sandbox policy")
        self.violations = violations


class CodePolicyChecker(ast.NodeVisitor):
    MAX_SOURCE_CHARS = 50_000
    MAX_AST_NODES = 2_000
    MAX_LOOP_ITERATIONS = 1_000_000

    def __init__(self) -> None:
        self._violations: list[PolicyViolation] = []
        self._node_count = 0
        self._structured_output_seen = False

    def check(self, source: str) -> PolicyCheckResult:
        self._violations = []
        self._node_count = 0
        self._structured_output_seen = False
        if not isinstance(source, str) or not source.strip():
            return PolicyCheckResult(False, [PolicyViolation("source", "Source must be non-empty", 0, 0)], 0)
        if len(source) > self.MAX_SOURCE_CHARS:
            return PolicyCheckResult(False, [PolicyViolation("length", "Source exceeds policy length limit", 0, 0)], 0)
        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError as exc:
            return PolicyCheckResult(False, [PolicyViolation("syntax", exc.msg, exc.lineno or 0, exc.offset or 0)], 0)
        self.visit(tree)
        if self._node_count > self.MAX_AST_NODES:
            self._deny(tree, "complexity", "Source exceeds AST complexity limit")
        if not self._structured_output_seen:
            self._deny(tree, "structured_output", "Code must call sandbox_sdk.emit_result")
        return PolicyCheckResult(not self._violations, list(self._violations), self._node_count)

    def ensure_allowed(self, source: str) -> PolicyCheckResult:
        result = self.check(source)
        if not result.allowed:
            raise CodePolicyViolation(result.violations)
        return result

    def generic_visit(self, node: ast.AST) -> None:
        self._node_count += 1
        super().generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_import(alias.name, node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level or not node.module:
            self._deny(node, "import", "Relative and dynamic imports are forbidden")
        else:
            self._check_import(node.module, node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = self._call_name(node.func)
        if name in BANNED_CALLS:
            self._deny(node, "call", f"Forbidden call: {name}")
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in BANNED_ATTRIBUTES:
                self._deny(node, "attribute_call", f"Forbidden API call: {node.func.attr}")
            if node.func.attr == "emit_result":
                self._structured_output_seen = True
        elif name == "emit_result":
            self._structured_output_seen = True
        if name == "range" and node.args:
            size = self._integer_value(node.args[0])
            if size is not None and abs(size) > self.MAX_LOOP_ITERATIONS:
                self._deny(node, "resource", "range exceeds loop iteration limit")
        for keyword in node.keywords:
            if keyword.arg == "n_jobs":
                workers = self._integer_value(keyword.value)
                if workers != 1:
                    self._deny(node, "process", "n_jobs must be fixed to one worker")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_") or "__" in node.attr:
            self._deny(node, "reflection", "Dunder/private attribute access is forbidden")
        if node.attr in BANNED_ATTRIBUTE_READS:
            self._deny(node, "environment", f"Forbidden environment access: {node.attr}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__"):
            self._deny(node, "reflection", "Dunder name access is forbidden")
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self._deny(node, "loop", "while loops are forbidden in generated code")
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, ast.Mult) and isinstance(node.left, (ast.List, ast.Tuple, ast.Set, ast.Dict, ast.Constant)):
            multiplier = self._integer_value(node.right)
            if multiplier is not None and abs(multiplier) > self.MAX_LOOP_ITERATIONS:
                self._deny(node, "resource", "Potential memory-allocation bomb")
        if isinstance(node.op, ast.Pow):
            value = self._integer_value(node)
            if value is not None and abs(value) > self.MAX_LOOP_ITERATIONS:
                self._deny(node, "resource", "Potential oversized exponentiation")
        self.generic_visit(node)

    def _check_import(self, module: str, node: ast.AST) -> None:
        root = module.split(".", 1)[0]
        if root not in ALLOWED_IMPORT_ROOTS:
            self._deny(node, "import", f"Import is not allowlisted: {module}")

    def _deny(self, node: ast.AST, rule: str, message: str) -> None:
        violation = PolicyViolation(rule, message, getattr(node, "lineno", 0), getattr(node, "col_offset", 0))
        if violation not in self._violations:
            self._violations.append(violation)

    @staticmethod
    def _call_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = CodePolicyChecker._call_name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        return ""

    @staticmethod
    def _integer_value(node: ast.AST) -> int | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            value = CodePolicyChecker._integer_value(node.operand)
            return -value if value is not None else None
        if isinstance(node, ast.BinOp):
            left = CodePolicyChecker._integer_value(node.left)
            right = CodePolicyChecker._integer_value(node.right)
            if left is None or right is None:
                return None
            try:
                if isinstance(node.op, ast.Add): return left + right
                if isinstance(node.op, ast.Sub): return left - right
                if isinstance(node.op, ast.Mult): return left * right
                if isinstance(node.op, ast.Pow) and abs(right) <= 32: return left ** right
            except OverflowError:
                return None
        return None
