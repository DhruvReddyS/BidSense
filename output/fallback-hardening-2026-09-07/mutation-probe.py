"""Break the new fallback protections only in a disposable checkout."""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
root=Path.cwd()
cases=[
 ('tier_context','app/llm/chain.py','_prompt_factory(provider.input_char_budget)','_prompt_factory(None)','test_fallback_rebuilds_prompt_for_actual_tier'),
 ('tier_concurrency','app/llm/chain.py','with provider:','with __import__("contextlib").nullcontext():','test_bursty_fallback_uses_local_concurrency_limit'),
 ('validation_coverage','app/extraction/pipeline.py','selected_pages=header_pages','selected_pages=None','test_validation_uses_actual_header_pages'),
]
results=[]
with tempfile.TemporaryDirectory(prefix='bidsense-fallback-mutation-') as tmp:
 target=Path(tmp)/'backend';target.mkdir()
 for folder in ('app','tests'):shutil.copytree(root/folder,target/folder,ignore=shutil.ignore_patterns('__pycache__'))
 shutil.copy(root/'pytest.ini',target/'pytest.ini')
 env=os.environ.copy();env['PYTHONPATH']=str(target)
 for name,path,before,after,test in cases:
  file=target/path;source=file.read_text();assert before in source
  file.write_text(source.replace(before,after))
  try:
   run=subprocess.run([sys.executable,'-m','pytest','tests/test_fallback_capacity.py::'+test,'-q'],cwd=target,env=env,capture_output=True,text=True,timeout=60)
   killed=run.returncode==1 and ' failed' in run.stdout and 'ERROR collecting' not in run.stdout
   results.append({'mutation':name,'killed':killed,'summary':run.stdout.strip().splitlines()[-1]})
  finally:file.write_text(source)
print(json.dumps(results,indent=2))
assert all(r['killed'] for r in results),results
