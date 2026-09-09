# PDF export hardening

The PDF changes passed the complete backend suite: **751 passed, no skips or failures, 436.81 seconds**. This run precedes the separate fallback-capacity changes in `../fallback-hardening-2026-09-07` and must not certify those later changes.

- Replaced Latin-1 substitution with embedded licensed Noto fonts and WeasyPrint 69.0. Hindi, Telugu, rupee signs, Greek and Cyrillic retain their source characters. Bundled coverage is explicit; it is not universal Unicode coverage.
- PDF ActualText preserves logical Indic text in supporting readers, independently of visual shaping. Poppler copy-text tests pass. Readers that ignore ActualText, including the current pypdf text extractor for these Indic runs, can still reorder combining marks. DOCX retains the original Unicode.
- Four simultaneous distinct Unicode exports retain each vendor's text without cross-request leakage. The renderer serializes PDF generation while its version-pinned text hook is installed and restores the hook afterward.
- An unseen 96-row report produced a 10-page PDF and DOCX concurrently. Every unique requirement/value marker survives in both formats, including literal markup. All ten dense PDF pages and both short Unicode pages were rendered and visually inspected for wrapping, repeated headers, clipping, footer placement and readable glyphs. These are synthetic layout probes, not fabricated GHMC rows.
- Four actual concurrent HTTP exports for the stored SBI Version 3 and GHMC reports returned 200, valid PDF/DOCX files and their data-quality warning. PDF lengths: 4 and 8 pages. Completion times: 13.05–13.92 seconds including report construction/model loading.
- Unsupported Chinese text produces a tested HTTP 422 with a DOCX alternative; the same request as DOCX returns 200. Renderer resource fetching is restricted to six bundled fonts.
- Removing ActualText in a disposable copy causes the Indic regression to fail: mutation killed. The full suite also includes the nine individual defect-registry deletion checks.
- Pango/Poppler requirements, supported scripts and the reader limitation are documented in RUNNING.md. Font sources, hashes and the OFL license are bundled.

Evidence: `full-tests.log`, `mutation.json`, `dense-parity.json`, `api-unsupported.json`, `live-export.json`. Probe scripts are retained here. QA artifacts are in `../pdf/`; they are not a new UI preview.

Track A remains open. User confirmed on 7 September that key rotation is **not completed**. The strict baseline still has 17/19 outcome matches (original subset 13/15), as documented by the source-based identity audit. No Track B or Part 2 completion is claimed.
