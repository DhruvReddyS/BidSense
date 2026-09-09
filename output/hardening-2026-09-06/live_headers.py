"""Bounded live provider checks against an existing real-document answer key.
Run from backend with PYTHONPATH=. and the repository virtual environment.
Two concurrent requests per tier; normal configured pacing/timeouts apply.
No database writes, no credential values in output.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json, time
from app.llm import build_provider
from app.ingest import parse_document
from app.schemas.common import DocumentKind
from app.extraction.selection import select_pages
from app.extraction import prompts, llm_schemas
from scripts.benchmark_extraction import TRUTH, _matches

out=Path('../output/hardening-2026-09-06/live-headers.json')
expected=TRUTH[0]
document=parse_document(expected.path,DocumentKind.NOTIFICATION)
results=[]
for name in ('gemini','groq','ollama'):
    provider=build_provider(name)
    budget=provider.input_char_budget
    body,pages=select_pages(document,'header',**({'char_budget':budget} if budget else {}))
    def run(index):
        started=time.perf_counter()
        try:
            header=provider.generate_structured(prompts.HEADER_PROMPT.format(text=body),llm_schemas.RawHeader,system=prompts.SYSTEM_PROMPT)
            checks={field:_matches(value,getattr(header,field,None)) for field,(value,_) in expected.header.items()}
            return dict(provider=name,model=provider.last_model_used,request=index,seconds=round(time.perf_counter()-started,3),checks=checks,pages=pages,error=None)
        except Exception as exc:
            # Exception payloads from remote services can include request details.
            # Retain only the class here; provider logs remain local to the run.
            return dict(provider=name,request=index,seconds=round(time.perf_counter()-started,3),checks={},pages=pages,error=type(exc).__name__)
    with ThreadPoolExecutor(max_workers=2) as pool:
        batch=list(pool.map(run,range(2)))
    results.extend(batch)
    out.write_text(json.dumps({'scope':'two concurrent live header extractions per tier; not full extraction or forced quota exhaustion','document':expected.label,'results':results},indent=2))
    print(name,[(sum(r['checks'].values()),len(r['checks']),r['error']) for r in batch],flush=True)
