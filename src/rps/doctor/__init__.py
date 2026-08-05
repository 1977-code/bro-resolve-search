"""Resolve Doctor — collects the facts this project cannot get any other way.

The searcher was written on a machine with no DaVinci Resolve and no ``.drp``
files. Everything past version 1.0 — the structural parser, search by Reel Name,
importing a found project straight into Resolve — needs facts about a real
installation. This package gathers them.

Design rules, same as the rest of the project:

* **Read-only.** Nothing here writes, renames, deletes or launches anything. The
  live API probe calls getters only.
* **Candidates, not claims.** Paths that "should" hold a Resolve database are
  listed as candidates and reported by whether they exist, never asserted.
* **Absent is not broken.** A missing module and a module that failed to import
  are different findings with different fixes, and they are reported separately.
"""

from __future__ import annotations

__all__ = ["collect", "render_markdown", "render_json"]

from rps.doctor.probe import collect
from rps.doctor.report import render_json, render_markdown
