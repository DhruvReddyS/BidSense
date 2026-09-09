"""Run guard mutations in disposable copies; never edit the working checkout."""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
from app.config import settings
root=Path.cwd()
cases=[('evaluation_exit', 'scripts/evaluate.py', 'return 0 if summary["passed"] else 1', 'return 0', 'tests/test_evaluation_gate.py::test_cli_returns_nonzero_for_bad_evaluation'), ('narrative_honesty', 'app/compliance/gap.py', 'if narrative and not formal_document and not explicitly_absent:', 'if False:', 'tests/test_narrative_requirements.py::test_narrative_absence_is_not_inferred_from_enclosures[Method statement]'), ('explicit_absence', 'app/compliance/gap.py', 'if narrative and not formal_document and not explicitly_absent:', 'if narrative and not formal_document:', 'tests/test_narrative_requirements.py::test_explicitly_missing_narrative_still_fails'), ('certificate_guard', 'app/compliance/gap.py', 'if narrative and not formal_document and not explicitly_absent:', 'if narrative and not explicitly_absent:', 'tests/test_narrative_requirements.py::test_required_certificates_still_fail_when_absent[Technical manpower certification]'), ('quality_error_propagation', 'app/api/quality.py', "for field in ('extraction_errors', 'parse_warnings'):", 'for field in ():', 'tests/test_extraction_audit.py::test_export_receives_the_same_audit_warning_and_provider'), ('singleflight', 'app/extraction/pipeline.py', 'with extraction_cache.extraction_lock(digest, DocumentKind.NOTIFICATION) if use_cache else nullcontext():', 'with nullcontext():', 'tests/test_singleflight.py::test_simultaneous_uploads_call_the_graph_once')]
results=[]
with tempfile.TemporaryDirectory(prefix='bidsense-mutation-') as tmp:
 target=Path(tmp)/'backend';target.mkdir()
 for folder in ('app','tests','scripts'): shutil.copytree(root/folder,target/folder,ignore=shutil.ignore_patterns('__pycache__'))
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
