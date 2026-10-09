"""Run every evaluator, record what it took to reproduce, write one result set.

A reviewer has to be able to re-run the numbers and get the numbers. That needs
three things this project had scattered across seven scripts: one entry point,
a manifest of the exact inputs (code revision, dependency versions, seeds,
corpus checksums), and a consolidated result file with the n behind every
figure.

The important design choice is that a missing prerequisite is reported as
BLOCKED, not as a failure and never as a zero. The corpus PDFs are gitignored,
the vector store and database may not be running, and the LLM providers have
quotas -- so on a fresh checkout most stages cannot run, and a harness that
exits 1 or silently writes 0.0 for those would be worse than useless. A stage
is FAILED only when its prerequisites were present and it still broke, which is
the signal worth acting on.

  python -m scripts.evaluate_all                     # everything that can run
  python -m scripts.evaluate_all --out ../output/run-2026-10-09
  python -m scripts.evaluate_all --only retrieval,chunking
  python -m scripts.evaluate_all --list              # stages and prerequisites

Exit status: 0 if nothing FAILED (BLOCKED stages do not fail the run),
1 if any stage FAILED, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
DATA = ROOT / "data"

#: The bootstrap seed. Every sampling or resampling step in the suite derives
#: from this, and it is recorded in the manifest so an interval is reproducible.
SEED = 20260907
BOOTSTRAP_ITERATIONS = 10000


@dataclass
class Stage:
    """One evaluator, its prerequisites, and how to invoke it."""

    name: str
    module: str
    what: str
    #: Paths that must exist for the stage to be meaningful.
    needs_paths: list[Path] = field(default_factory=list)
    #: Services that must answer before the stage can run. "schema" means
    #: Postgres is reachable AND scripts.bootstrap has been run against it;
    #: "ingested" additionally means at least one notification is in it.
    needs_services: list[str] = field(default_factory=list)
    #: True if the stage calls an LLM provider and so depends on quota.
    needs_llm: bool = False
    args: list[str] = field(default_factory=list)
    #: Writes its own JSON when given --json.
    takes_json: bool = True


def notification_pdfs() -> list[Path]:
    return sorted((DATA / "notifications").glob("*.pdf"))


STAGES = [
    Stage("extraction", "scripts.evaluate_extraction",
          "header-field extraction against data/extraction_truth.json",
          needs_paths=[DATA / "extraction_truth.json"],
          needs_services=["postgres", "schema", "ingested"]),
    Stage("retrieval", "scripts.evaluate_retrieval",
          "dense retrieval hit@k and MRR over the labelled queries",
          needs_paths=[DATA / "rag_queries.json"],
          needs_services=["qdrant"]),
    Stage("baseline", "scripts.baseline_retrieval",
          "BM25 floor, paired against the dense arm",
          needs_paths=[DATA / "rag_queries.json"],
          args=["--dense"]),
    Stage("chunking", "scripts.ablate_chunking",
          "table-row vs size-only chunking, same labels, in memory",
          needs_paths=[DATA / "rag_queries.json"]),
    Stage("citations", "scripts.evaluate_citations",
          "whether a cited page actually supports the claim",
          needs_paths=[DATA / "rag_queries.json"],
          needs_services=["qdrant"], needs_llm=True),
    Stage("router", "scripts.evaluate_router",
          "query routing accuracy",
          needs_paths=[DATA / "router_queries.json"], takes_json=False),
    Stage("elimination", "scripts.evaluate",
          "elimination status and reason against the answer key",
          needs_paths=[DATA / "tracking_vendors.csv"],
          needs_services=["postgres", "schema", "ingested"]),
]


def service_up(name: str) -> bool:
    """Cheap liveness probe. Never raises -- an unreachable service is a
    blocked stage, not a crash of the harness."""
    try:
        if name == "qdrant":
            import urllib.request
            host = os.environ.get("QDRANT_HOST", "localhost")
            port = os.environ.get("QDRANT_PORT", "6343")
            with urllib.request.urlopen(
                f"http://{host}:{port}/readyz", timeout=3
            ) as response:
                return response.status == 200
        if name == "postgres":
            import socket
            host = os.environ.get("POSTGRES_HOST", "localhost")
            port = int(os.environ.get("POSTGRES_PORT", "5432"))
            with socket.create_connection((host, port), timeout=3):
                return True
        if name == "ingested":
            # An empty-but-valid schema is still a prerequisite that has not
            # been met. Without this the elimination evaluator runs, reports
            # "notification not ingested" for every bid and exits 1 -- which
            # the harness then calls FAILED, when the only thing missing is
            # the corpus the other six stages are already blocked on.
            from sqlalchemy import create_engine, text
            from app.config import settings
            engine = create_engine(settings.database_url, pool_pre_ping=False)
            try:
                with engine.connect() as connection:
                    return bool(connection.execute(text(
                        "select 1 from tender_notifications limit 1"
                    )).first())
            finally:
                engine.dispose()
        if name == "schema":
            # A reachable Postgres with no tables is a prerequisite that has
            # not been met, not a broken evaluator: without this probe the
            # stage fails deep inside SQLAlchemy with an UndefinedTable and
            # reads as a bug in the code under test.
            from sqlalchemy import create_engine, text
            from app.config import settings
            engine = create_engine(settings.database_url, pool_pre_ping=False)
            try:
                with engine.connect() as connection:
                    return bool(connection.execute(text(
                        "select 1 from information_schema.tables "
                        "where table_name = 'tender_notifications'"
                    )).first())
            finally:
                engine.dispose()
    except Exception:
        return False
    return False


def blockers(stage: Stage, services: dict[str, bool]) -> list[str]:
    reasons = []
    missing = [p for p in stage.needs_paths if not p.exists()]
    reasons += [f"missing {p.relative_to(ROOT)}" for p in missing]
    if not notification_pdfs() and stage.name != "elimination":
        reasons.append("no notification PDFs in data/notifications "
                       "(gitignored; restore the corpus)")
    for required in stage.needs_services:
        if not services.get(required):
            reasons.append({
                "schema": "schema not created (run: python -m scripts.bootstrap)",
                "ingested": "no notifications ingested (run: python -m "
                            "scripts.ingest over data/notifications)",
            }.get(required, f"{required} unreachable"))
    if stage.needs_llm and not any(
        os.environ.get(k) for k in
        ("GEMINI_API_KEY", "GROQ_API_KEY", "XAI_API_KEY", "OLLAMA_BASE_URL")
    ):
        reasons.append("no LLM provider configured")
    return reasons


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except Exception:
        return ""


def dependency_versions() -> dict[str, str]:
    """The packages whose version can move a number."""
    from importlib.metadata import PackageNotFoundError, version
    wanted = [
        "sentence-transformers", "torch", "qdrant-client", "pdfplumber",
        "pypdf", "numpy", "SQLAlchemy", "pydantic", "google-genai", "langgraph",
    ]
    out = {}
    for name in wanted:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = "absent"
    return out


def corpus_manifest() -> dict:
    """Checksums, so a number can be tied to the bytes that produced it."""
    labels = {}
    for relative in ("rag_queries.json", "router_queries.json",
                     "extraction_truth.json", "tracking_vendors.csv"):
        path = DATA / relative
        if path.exists():
            labels[relative] = {"sha256": sha256(path), "bytes": path.stat().st_size}

    notifications = {
        p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
        for p in notification_pdfs()
    }

    counts = {}
    queries = DATA / "rag_queries.json"
    if queries.exists():
        spec = json.loads(queries.read_text())
        counts["labelled_queries"] = len(spec.get("queries", []))
    key = DATA / "tracking_vendors.csv"
    if key.exists():
        import csv
        with key.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        counts["labelled_bids"] = len(rows)
        counts["bids_eliminated"] = sum(
            1 for r in rows if r.get("intended_status") == "eliminate"
        )

    return {
        "labels": labels,
        "notifications": notifications,
        "notification_count": len(notifications),
        "n": counts,
    }


def manifest() -> dict:
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git": {
            "revision": git("rev-parse", "HEAD"),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            # A dirty tree means the recorded revision does not describe the
            # code that produced these numbers. Say so rather than imply it.
            "dirty": bool(git("status", "--porcelain")),
        },
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "seed": SEED,
        "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
        "dependencies": dependency_versions(),
        "corpus": corpus_manifest(),
    }


def run_stage(stage: Stage, out_dir: Path, services: dict[str, bool]) -> dict:
    reasons = blockers(stage, services)
    if reasons:
        print(f"  BLOCKED  {stage.name:12} {'; '.join(reasons)}")
        return {"status": "blocked", "reasons": reasons, "what": stage.what}

    target = out_dir / f"{stage.name}.json"
    command = [sys.executable, "-m", stage.module, *stage.args]
    if stage.takes_json:
        command += ["--json", str(target)]

    started = time.perf_counter()
    completed = subprocess.run(
        command, cwd=BACKEND, capture_output=True, text=True
    )
    elapsed = time.perf_counter() - started

    (out_dir / f"{stage.name}.log").write_text(
        completed.stdout + ("\n--- stderr ---\n" + completed.stderr
                            if completed.stderr else "")
    )

    status = "ok" if completed.returncode == 0 else "failed"
    print(f"  {status.upper():8} {stage.name:12} {elapsed:6.1f}s"
          f"{'' if status == 'ok' else f'  exit={completed.returncode}'}")
    if status == "failed":
        tail = (completed.stderr or completed.stdout).strip().splitlines()[-3:]
        for line in tail:
            print(f"           | {line[:100]}")

    result = {
        "status": status,
        "what": stage.what,
        "seconds": round(elapsed, 2),
        "exit_code": completed.returncode,
        "command": " ".join(command[1:]),
        "log": f"{stage.name}.log",
    }
    if stage.takes_json and target.exists():
        try:
            result["results"] = json.loads(target.read_text())
        except json.JSONDecodeError:
            result["results_unparseable"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "output" / f"evaluate-all-{time.strftime('%Y-%m-%d')}")
    parser.add_argument("--only", help="comma-separated stage names")
    parser.add_argument("--list", action="store_true",
                        help="print the stages and their prerequisites")
    args = parser.parse_args()

    if args.list:
        print(f"{'stage':12} {'needs':38} what")
        for stage in STAGES:
            needs = ", ".join(
                [p.name for p in stage.needs_paths]
                + stage.needs_services
                + (["an LLM provider"] if stage.needs_llm else [])
            )
            print(f"{stage.name:12} {needs[:37]:38} {stage.what}")
        return 0

    selected = STAGES
    if args.only:
        wanted = {n.strip() for n in args.only.split(",")}
        unknown = wanted - {s.name for s in STAGES}
        if unknown:
            parser.error(f"unknown stage(s): {sorted(unknown)}")
        selected = [s for s in STAGES if s.name in wanted]

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    services = {name: service_up(name) for name in ("qdrant", "postgres")}
    # Only worth probing when the server itself answered.
    services["schema"] = services["postgres"] and service_up("schema")
    services["ingested"] = services["schema"] and service_up("ingested")
    info = manifest()

    print(f"BidSense evaluation suite")
    print(f"  revision  {info['git']['revision'][:12] or '(unknown)'}"
          f"{'  (DIRTY TREE)' if info['git']['dirty'] else ''}")
    print(f"  corpus    {info['corpus']['notification_count']} notification(s), "
          f"{info['corpus']['n'].get('labelled_queries', 0)} labelled quer(ies), "
          f"{info['corpus']['n'].get('labelled_bids', 0)} labelled bid(s)")
    print(f"  services  " + ", ".join(
        f"{k}={'up' if v else 'down'}" for k, v in services.items()))
    print(f"  seed      {SEED}")
    print(f"  output    {out_dir}\n")

    results = {stage.name: run_stage(stage, out_dir, services)
               for stage in selected}

    tally = {}
    for value in results.values():
        tally[value["status"]] = tally.get(value["status"], 0) + 1

    consolidated = {"manifest": info, "stages": results, "tally": tally}
    (out_dir / "results.json").write_text(json.dumps(consolidated, indent=2))

    print(f"\n{'-' * 70}")
    print("  ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    if tally.get("blocked"):
        print(f"\n{tally['blocked']} stage(s) BLOCKED on a missing prerequisite."
              "\nThat is not a failure and no number was invented for them --"
              "\nsee results.json for exactly what each one needs.")
    print(f"\nWrote {out_dir / 'results.json'}")
    return 1 if tally.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
