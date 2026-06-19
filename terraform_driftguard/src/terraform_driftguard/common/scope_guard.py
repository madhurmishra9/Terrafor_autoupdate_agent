"""Scope guard — confine a generated patch to one product's blast radius.

When DriftGuard updates, say, Spanner, the patch must touch ONLY Spanner's
resources — never the IAM, KMS, or networking blocks that happen to live in the
same module file. This guard makes that a hard, deterministic rule rather than a
skill instruction the model might ignore:

  - It parses the candidate HCL and finds every `resource "<type>" "<name>"`
    block.
  - In-family resource types (the product's manifest resources +
    related_resources) are eligible for edits; everything else is out of scope.
  - Out-of-scope resource blocks are STRIPPED from the patch (kept exactly as
    they were / removed from the change set), so only in-family changes ship.
  - The patch's target file is checked against the product's module_paths; an
    edit outside those paths is rejected.

This keeps the change blast radius equal to the product, which is the single
biggest lever for update accuracy.
"""
from __future__ import annotations

import re
from typing import Any

from .logging_setup import get_logger
from .product_registry import registry

logger = get_logger(__name__)

# Matches `resource "type" "name" {` and captures type + name + the brace.
_RESOURCE_RE = re.compile(
    r'resource\s+"(?P<type>[a-zA-Z0-9_]+)"\s+"(?P<name>[a-zA-Z0-9_-]+)"\s*\{',
)


def _iter_resource_blocks(hcl: str):
    """Yield (type, name, start, end) for each top-level resource block.

    Brace-matches from each `resource` header to its closing brace so nested
    blocks are handled correctly.
    """
    for m in _RESOURCE_RE.finditer(hcl):
        start = m.start()
        brace_open = hcl.index("{", m.start())
        depth = 0
        i = brace_open
        while i < len(hcl):
            c = hcl[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    yield m.group("type"), m.group("name"), start, i + 1
                    break
            i += 1


def list_patch_resources(hcl: str) -> list[dict[str, str]]:
    """Return [{type, name}] for every resource block in the patch."""
    return [{"type": t, "name": n} for t, n, _, _ in _iter_resource_blocks(hcl)]


def check_scope(product: str, hcl: str, file_path: str = "") -> dict[str, Any]:
    """Classify a patch's resource blocks as in- or out-of-family for a product.

    Returns:
      {
        "product": str, "known": bool, "family": [...],
        "in_scope": [{type,name}], "out_of_scope": [{type,name}],
        "path_in_scope": bool, "module_paths": [...],
        "ok": bool   # True iff nothing out of scope and path is allowed
      }
    """
    p = registry.get(product)
    if not p:
        return {"product": product, "known": False, "ok": False,
                "reason": "unknown_product"}

    family = {r.lower() for r in p.family}
    in_scope: list[dict[str, str]] = []
    out_of_scope: list[dict[str, str]] = []
    for t, n, _, _ in _iter_resource_blocks(hcl):
        (in_scope if t.lower() in family else out_of_scope).append({"type": t, "name": n})

    module_paths = list(p.module_paths)
    path_in_scope = True
    if file_path and module_paths:
        path_in_scope = any(_path_under(file_path, mp) for mp in module_paths)

    return {
        "product": p.name,
        "known": True,
        "family": list(p.family),
        "in_scope": in_scope,
        "out_of_scope": out_of_scope,
        "path_in_scope": path_in_scope,
        "module_paths": module_paths,
        "ok": (not out_of_scope) and path_in_scope,
    }


def strip_out_of_scope(product: str, hcl: str) -> dict[str, Any]:
    """Remove resource blocks that are not in the product's family.

    Returns {content, stripped:[{type,name}], kept:[{type,name}]}. In-family
    blocks (and any non-resource content like variables/locals/outputs) are left
    untouched; out-of-family resource blocks are removed so they are never part
    of the change set.
    """
    p = registry.get(product)
    if not p:
        return {"content": hcl, "stripped": [], "kept": [], "known": False}

    family = {r.lower() for r in p.family}
    # Collect spans to remove (out-of-family resource blocks), then splice.
    removals: list[tuple[int, int, str, str]] = []
    kept: list[dict[str, str]] = []
    for t, n, start, end in _iter_resource_blocks(hcl):
        if t.lower() in family:
            kept.append({"type": t, "name": n})
        else:
            removals.append((start, end, t, n))

    if not removals:
        return {"content": hcl, "stripped": [], "kept": kept, "known": True}

    # Remove from the back so indices stay valid; also trim a trailing blank line.
    out = hcl
    stripped: list[dict[str, str]] = []
    for start, end, t, n in sorted(removals, key=lambda x: x[0], reverse=True):
        seg_end = end
        # swallow a single trailing newline left by the removed block
        if seg_end < len(out) and out[seg_end] == "\n":
            seg_end += 1
        out = out[:start] + out[seg_end:]
        stripped.append({"type": t, "name": n})

    # Collapse 3+ blank lines created by removal down to one.
    out = re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"
    logger.info("scope guard stripped %d out-of-family block(s) for %s",
                len(stripped), p.name)
    return {"content": out, "stripped": list(reversed(stripped)), "kept": kept,
            "known": True}


def _path_under(file_path: str, module_path: str) -> bool:
    fp = file_path.strip("/").replace("\\", "/")
    mp = module_path.strip("/").replace("\\", "/")
    return fp == mp or fp.startswith(mp + "/") or ("/" + mp + "/") in ("/" + fp)
