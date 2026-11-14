"""Best-effort syntax-aware symbol extraction. Source remains untrusted data."""
import ast
from pathlib import PurePosixPath

EXTENSION_LANGUAGE = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "tsx", ".go": "go", ".rs": "rust", ".java": "java", ".c": "c",
    ".h": "c", ".cpp": "cpp", ".cs": "c_sharp", ".rb": "ruby", ".php": "php",
}

def extract_symbols(path: str, source: str) -> list[dict]:
    ext = PurePosixPath(path).suffix.lower()
    if ext == ".py":
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        rows = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                args = ""
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = ast.unparse(node.args)
                rows.append({"name": node.name, "kind": kind,
                    "start_line": int(node.lineno), "end_line": int(getattr(node, "end_lineno", node.lineno) or node.lineno),
                    "signature": f"{node.name}({args})" if kind == "function" else f"class {node.name}"})
        return rows
    language = EXTENSION_LANGUAGE.get(ext)
    if not language:
        return []
    try:
        from tree_sitter_language_pack import get_parser
        parser = get_parser(language)
        tree = parser.parse(source.encode("utf-8", errors="replace"))
    except Exception:
        return []
    rows = []
    kinds = {"function_definition": "function", "function_declaration": "function",
             "method_definition": "method", "method_declaration": "method",
             "class_definition": "class", "class_declaration": "class",
             "interface_declaration": "interface", "struct_item": "struct"}
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in kinds:
            name_node = node.child_by_field_name("name")
            name = source.encode("utf-8")[name_node.start_byte:name_node.end_byte].decode("utf-8", "replace") if name_node else node.type
            rows.append({"name": name[:255], "kind": kinds[node.type],
                "start_line": node.start_point.row + 1, "end_line": node.end_point.row + 1,
                "signature": source.encode("utf-8")[node.start_byte:min(node.end_byte, node.start_byte + 300)].decode("utf-8", "replace").splitlines()[0][:300]})
        stack.extend(reversed(node.children))
    return rows
