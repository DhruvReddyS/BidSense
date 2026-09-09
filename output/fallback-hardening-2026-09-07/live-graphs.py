"""Full real-document graphs at both lower tiers, with injected upstream retirement.
No production rows/cache writes. This does not spend quota to force exhaustion.
"""
import json,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.llm import build_provider
from app.llm.base import LLMProvider,LLMError
from app.llm.chain import ChainProvider
from app.ingest import parse_document
from app.schemas.common import DocumentKind
from app.extraction.graph import extract_notification
from app.extraction.validate import validate_notification
from scripts.benchmark_extraction import TRUTH

class Exhausted(LLMProvider):
 name='injected-exhaustion'
 def generate_text(self,*a,**k):raise LLMError('exhausted its daily free-tier quota [injected probe]')
 def generate_structured(self,*a,**k):raise LLMError('exhausted its daily free-tier quota [injected probe]')

root=Path('../output/fallback-hardening-2026-09-07')
document=parse_document(TRUTH[0].path,DocumentKind.NOTIFICATION)
def run(destination):
 names=['gemini','groq'] if destination=='groq' else ['gemini','groq','ollama']
 chain=ChainProvider(names)
 chain._built={name:build_provider(name) if name==destination else Exhausted() for name in names}
 started=time.monotonic()
 notification,meta=extract_notification(document,llm=chain)
 pages=next((pages for node,pages in meta['selections'] if node=='header'),None)
 findings=validate_notification(notification,document,selected_pages=pages)
 missing=notification.model_copy(update={'submission_deadline':None})
 forced=validate_notification(missing,document,selected_pages=pages)
 backstop=any(f.field=='submission_deadline' and 'appears to state it' in f.message for f in forced)
 output={'destination':destination,'seconds':round(time.monotonic()-started,3),'nodes':len(meta['timings']),'error_count':len(meta['errors']),'providers':meta['providers'],'selections':meta['selections'],'retired_tiers':list(chain.retired),'notification':notification.model_dump(mode='json'),'findings':[{'field':f.field,'severity':f.severity.value,'message':f.message} for f in findings],'deliberately_removed_deadline_detected_by_regex':backstop,'scope':'Live lower-tier full graph; upstream retirement and missing deadline are injected faults, not observed quota exhaustion/model omission.'}
 (root/f'live-{destination}.json').write_text(json.dumps(output,indent=2))
 return {k:output[k] for k in ['destination','seconds','nodes','error_count','providers','deliberately_removed_deadline_detected_by_regex']}
with ThreadPoolExecutor(max_workers=2) as pool:
 for future in as_completed([pool.submit(run,name) for name in ['groq','ollama']]):print(json.dumps(future.result()),flush=True)
