"""Corrigendum handling (Section 5.6, Part 1 slice).

A corrigendum amends a notification that has already been extracted, and bidders
have already been told what the tender requires. Two things must happen and a
third must not:

  * the amendment is extracted and diffed against the parent, so the change is
    recorded rather than lost;
  * every vendor whose gap report predates the amendment is flagged STALE, with
    a one-click re-check;
  * nothing is silently re-decided on their behalf. Auto-propagating a changed
    threshold across a pool of vendors is Part 2 (5.6) and is a different
    problem, because it changes a compliance verdict a vendor has already read
    without them asking for it.
"""

from app.corrigendum.diff import diff_corrigendum
from app.corrigendum.staleness import Staleness, staleness_for

__all__ = ["diff_corrigendum", "Staleness", "staleness_for"]
