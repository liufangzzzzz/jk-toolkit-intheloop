"""Text cleanup owned by the InTheLoop flow.

This is intentionally copied instead of importing from other product tabs.
Keep this module small so the InTheLoop tab can be pasted into a newer
workbench source tree without inheriting another tab's parsing changes.
"""
from __future__ import annotations

import re

_OUTER_MD_EM_RE = re.compile(r"^\s*(\*\*\*|\*\*|\*)\s*([\s\S]*?)\s*\1\s*$", re.I)
_ORPHAN_EDGE_MARKER_RE = re.compile(r"^\s*(\*{1,3})\s*")


def strip_outer_markdown_emphasis(raw: str) -> str:
    """Remove whole-line markdown emphasis and common orphan markers."""
    s = str(raw or "").strip()
    if not s:
        return ""
    while True:
        m = _OUTER_MD_EM_RE.match(s)
        if not m:
            break
        inner = (m.group(2) or "").strip()
        if inner == s:
            break
        s = inner
    while True:
        m = _ORPHAN_EDGE_MARKER_RE.match(s)
        if not m:
            break
        marker = m.group(1)
        if _OUTER_MD_EM_RE.match(s):
            break
        s = (s[m.end() :] or "").strip()
        if s.endswith(marker):
            s = s[: -len(marker)].rstrip()
    return re.sub(r"\s*(\*{1,3})\s*$", "", s).strip()


def normalize_line_for_intheloop_rule_match(raw: str) -> str:
    """Normalize one Feishu/Word line before InTheLoop regex matching."""
    s = str(raw or "").replace("\u200b", "").replace("\ufeff", "")
    s = s.replace("\u00a0", " ")
    return strip_outer_markdown_emphasis(s)
