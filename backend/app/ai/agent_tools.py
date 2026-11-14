"""Allowlisted, bounded repository investigation tools. Never executes repository code."""
import ast
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import RepositoryFile, RepositorySymbol
from app.rag.retrieval import retrieve

ALLOWED_TOOLS = {"search_code", "find_symbols", "read_file", "inspect_imports"}
MAX_STEPS = 4
MAX_FILE_CHARS = 18000

def run_tool(db: Session, repository_id: int, tool: str, args: dict) -> tuple[dict, list[dict]]:
    if tool not in ALLOWED_TOOLS:
        return {"error": "Tool is not allowlisted"}, []
    if tool == "search_code":
        query = str(args.get("query", ""))[:300]
        if len(query) < 2: return {"error": "Search query is too short"}, []
        hits = retrieve(db, repository_id, query, limit=5)
        return {"matches": [{"path":h["path"],"start_line":h["start_line"],"end_line":h["end_line"],"score":h["score"]} for h in hits]}, hits
    if tool == "find_symbols":
        query = str(args.get("query", ""))[:100]
        if len(query) < 2: return {"error": "Symbol query is too short"}, []
        rows = db.scalars(select(RepositorySymbol).where(RepositorySymbol.repository_id == repository_id,
            RepositorySymbol.name.ilike(f"%{query}%")).limit(20)).all()
        evidence=[]
        for row in rows:
            file = db.scalar(select(RepositoryFile).where(RepositoryFile.repository_id == repository_id,
                RepositoryFile.path == row.file_path))
            if not file: continue
            lines = file.content.splitlines()
            start, end = max(1,row.start_line-4), min(len(lines),row.end_line+4)
            evidence.append({"path":row.file_path,"language":file.language,"start_line":start,
                "end_line":end,"content":"\n".join(lines[start-1:end]),"score":0.5,"retrieval":"symbol"})
        return {"symbols":[{"name":r.name,"kind":r.kind,"path":r.file_path,
            "start_line":r.start_line,"end_line":r.end_line} for r in rows]}, evidence
    path = str(args.get("path", ""))[:1024]
    file = db.scalar(select(RepositoryFile).where(RepositoryFile.repository_id == repository_id,
        RepositoryFile.path == path))
    if not file: return {"error": "File path is not present in this repository"}, []
    if tool == "read_file":
        lines = file.content.splitlines()
        try: requested_start = int(args.get("start_line", 1))
        except (TypeError, ValueError): requested_start = 1
        start = max(1, min(requested_start, max(1,len(lines))))
        end = min(len(lines), start + 180)
        evidence = [{"path":file.path,"language":file.language,"start_line":start,
            "end_line":end,"content":"\n".join(lines[start-1:end])[:MAX_FILE_CHARS],
            "score":0.4,"retrieval":"file_read"}]
        return {"path":path,"start_line":start,"end_line":end,"content":evidence[0]["content"]}, evidence
    imports=[]
    if file.path.endswith(".py"):
        try:
            tree=ast.parse(file.content)
            for node in ast.walk(tree):
                if isinstance(node,ast.Import): imports.extend(alias.name for alias in node.names)
                elif isinstance(node,ast.ImportFrom): imports.append(node.module or "")
        except SyntaxError:
            return {"path":path,"imports":[],"warning":"Python source could not be parsed"}, []
    else:
        import re
        imports = re.findall(r"(?:import|from)\s+([\w./@-]+)",file.content)[:100]
    return {"path":path,"imports":sorted(set(imports))[:100]}, []
