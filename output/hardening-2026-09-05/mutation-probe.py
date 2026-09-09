"""Run guard mutations in disposable copies; never edit the working checkout."""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
from app.config import settings
root=Path.cwd()
cases=[
 ('cache_hit_increment','app/extraction/cache.py','hits=ExtractionCacheRow.hits + 1','hits=ExtractionCacheRow.hits','tests/test_concurrent_storage.py::test_concurrent_cache_lookups_count_every_hit'),
 ('citation_atomic_publish','app/documents/store.py','staging.replace(target)','pass  # mutation: never publish','tests/test_concurrent_storage.py::test_same_document_concurrent_writers_publish_complete_bytes'),
 ('routing_attribution','app/llm/chain.py','return self._last_used.get()','return None','tests/test_provider_attribution.py::test_concurrent_tier_recovery_keeps_attribution_with_the_call'),
 ('graph_attribution','app/extraction/graph.py','"providers": final.get("providers", []),','"providers": [],','tests/test_provider_attribution.py::test_graph_keeps_every_nodes_serving_tier'),
 ('token_reservation','app/llm/ratelimit.py','self._tokens -= cost\n        return deficit / rate','self._tokens = 0.0\n        return deficit / rate','tests/test_hardening_probes.py::test_token_budget_does_not_spend_the_same_refill_twice'),
 ('literal_export_text','app/compliance/export.py','return escape(text.encode("latin-1", "replace").decode("latin-1"))','return text.encode("latin-1", "replace").decode("latin-1")','tests/test_hardening_probes.py::test_pdf_preserves_literal_markup_in_source_values'),
]
results=[]
with tempfile.TemporaryDirectory(prefix='bidsense-mutation-') as tmp:
 target=Path(tmp)/'backend';target.mkdir()
 for folder in ('app','tests'): shutil.copytree(root/folder,target/folder,ignore=shutil.ignore_patterns('__pycache__'))
 shutil.copy(root/'pytest.ini',target/'pytest.ini')
 env=os.environ.copy();env['PYTHONPATH']=str(target)
 for field in ('postgres_user','postgres_password','postgres_db','postgres_host','postgres_port'):
  env[field.upper()]=str(getattr(settings,field))
 for name,path,before,after,test in cases:
  file=target/path;source=file.read_text();assert before in source
  file.write_text(source.replace(before,after))
  try:
   run=subprocess.run([sys.executable,'-m','pytest',test,'-q'],cwd=target,env=env,capture_output=True,text=True,timeout=60)
   killed=run.returncode==1 and '1 failed' in run.stdout and 'ERROR collecting' not in run.stdout
   results.append({'mutation':name,'test':test,'killed':killed,'summary':run.stdout.strip().splitlines()[-1]})
  finally: file.write_text(source)
print(json.dumps(results,indent=2))
assert all(r['killed'] for r in results), results
