"""Read route generators using Python's AST without importing application code.

Only literal dictionaries, conditions and string expressions are evaluated.
Unknown record values become a marker; no database, auth, API or app starts.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

DYNAMIC = "__DYNAMIC__"


def value(node, env):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id, DYNAMIC)
    if isinstance(node, (ast.Tuple, ast.List)):
        return [value(item, env) for item in node.elts]
    if isinstance(node, ast.Dict):
        return {value(key, env): value(item, env) for key, item in zip(node.keys, node.values)}
    if isinstance(node, ast.JoinedStr):
        return "".join(str(value(item.value, env) if isinstance(item, ast.FormattedValue) else value(item, env)) for item in node.values)
    if isinstance(node, ast.Subscript):
        collection, key = value(node.value, env), value(node.slice, env)
        return collection.get(key, DYNAMIC) if isinstance(collection, dict) else DYNAMIC
    if isinstance(node, ast.IfExp):
        test = value(node.test, env)
        return value(node.body if test is True else node.orelse, env) if isinstance(test, bool) else DYNAMIC
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        left, right = value(node.left, env), value(node.comparators[0], env)
        if left == DYNAMIC or right == DYNAMIC:
            return DYNAMIC
        if isinstance(node.ops[0], ast.Eq):
            return left == right
        if isinstance(node.ops[0], ast.In):
            return left in right
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in {"str", "quote"}:
            return value(node.args[0], env)
        if isinstance(node.func, ast.Name) and node.func.id == "canonical_kind":
            kind = value(node.args[0], env)
            return env.get("KIND_ALIASES", {}).get(kind, kind)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            collection = value(node.func.value, env)
            if isinstance(collection, dict):
                return collection.get(value(node.args[0], env), value(node.args[1], env) if len(node.args) > 1 else None)
    return DYNAMIC


def literal_assignment(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"Required source dictionary {name} not found")


def target(file, node, source, pattern, kind, entity_type):
    return {"file": file, "line": node.lineno, "source": "backend", "kind": kind,
            "entityType": entity_type, "expression": ast.get_source_segment(source, node),
            "variants": [{"pattern": pattern, "unresolved": DYNAMIC in pattern, "parameterized": DYNAMIC in pattern}]}


def inventory(repo: Path):
    names = ["backend/services/workspace_contexts.py", "backend/services/global_search.py", "backend/services/portfolio_scope.py"]
    sources = {name: (repo / name).read_text(encoding="utf-8-sig") for name in names}
    trees = {name: ast.parse(source, filename=name) for name, source in sources.items()}
    contexts_name, search_name, scope_name = names
    contexts = literal_assignment(trees[contexts_name], "CONTEXTS")
    aliases = literal_assignment(trees[contexts_name], "KIND_ALIASES")
    resources = literal_assignment(trees[scope_name], "RESOURCE_ALIASES")
    resolver = next(node for node in trees[contexts_name].body if isinstance(node, ast.FunctionDef) and node.name == "resolve_context")
    # This section is pure URL generation after the source has been authorized.
    start = next(index for index, node in enumerate(resolver.body) if isinstance(node, ast.With))
    body = resolver.body[start].body
    first_path = next(index for index, node in enumerate(body) if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "paths" for t in node.targets))
    targets = []
    for raw_kind, table in resources.items():
        kind = aliases.get(raw_kind, raw_kind)
        parent_kinds = ["property", "unit"] if kind == "entity_photo" else [DYNAMIC]
        for parent_kind in parent_kinds:
            context = next((key for key, candidate in contexts.items() if candidate[0] == kind), table)
            env = {"kind": kind, "context": context, "table_name": table, "entity_id": DYNAMIC,
                   "parent_kind": parent_kind, "KIND_ALIASES": aliases,
                   "values": {key: DYNAMIC for key in ["meter_id", "handover_id", "billing_period_id", "thread_id", "listing_id", "entity_id"]}}
            env["values"]["entity_type"] = parent_kind
            last_href = None

            def execute(nodes):
                nonlocal last_href
                for node in nodes:
                    if isinstance(node, ast.Assign):
                        for dest in node.targets:
                            if not isinstance(dest, ast.Name) or dest.id == "context":
                                continue
                            env[dest.id] = value(node.value, env)
                            if dest.id == "href":
                                last_href = node
                    elif isinstance(node, ast.If):
                        condition = value(node.test, env)
                        if isinstance(condition, bool):
                            execute(node.body if condition else node.orelse)
            execute(body[first_path:])
            if last_href is None or not isinstance(env.get("href"), str):
                raise ValueError(f"Cannot statically derive workspace URL for {kind}")
            targets.append(target(contexts_name, last_href, sources[contexts_name], env["href"], "workspace-context", raw_kind + (":" + parent_kind if kind == "entity_photo" else "")))
    search_tree = trees[search_name]
    focused = next(node for node in search_tree.body if isinstance(node, ast.FunctionDef) and node.name == "_focused")
    focused_lambda = next(node for node in ast.walk(focused) if isinstance(node, ast.Lambda))
    parameter_default = ast.literal_eval(focused.args.defaults[0])
    for node in ast.walk(search_tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "SearchType":
            continue
        kind = ast.literal_eval(node.args[0])
        url = node.args[-1]
        if isinstance(url, ast.Lambda):
            pattern = value(url.body, {})
        elif isinstance(url, ast.Call) and isinstance(url.func, ast.Name) and url.func.id == "_focused":
            env = {"path": ast.literal_eval(url.args[0]), "parameter": ast.literal_eval(url.args[1]) if len(url.args) > 1 else parameter_default}
            pattern = value(focused_lambda.body, env)
        else:
            pattern = DYNAMIC
        targets.append(target(search_name, url, sources[search_name], pattern, "global-search", kind))
    return {"targets": targets, "files": [{"file": name, "sha256": hashlib.sha256(source.encode()).hexdigest()} for name, source in sources.items()],
            "limitations": ["Pure string generator AST only; record values remain dynamic and must be runtime tested.",
                            "Parent entity-photo targets are enumerated for supported property/unit branches.",
                            "Workspace generic aliases retain their source-level context fallback, making unmapped resource routes visible."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(inventory(args.repo), ensure_ascii=True))
