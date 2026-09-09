"""Run guard mutations in disposable copies; never edit the working checkout."""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
from app.config import settings
root=Path.cwd()
cases=[('dedup_form_identity', 'app/compliance/requirements.py', 'identifiers = document_identifiers(doc_name)', 'identifiers = frozenset()', 'tests/test_document_identifiers.py::test_identifiers_survive_deduplication[Process Compliance Statement (Annexure-B)-Process Compliance Statement (Annexure-II)]'), ('conflicting_form_guard', 'app/compliance/matching.py', 'submitted = [name for name in submitted if not _conflicting_identifiers(required, name)]', 'submitted = list(submitted)', 'tests/test_document_identifiers.py::test_conflicting_annexures_cannot_match_even_with_high_similarity[True]'), ('explicit_absence_priority', 'app/compliance/gap.py', 'if explicitly_absent:\n        # A different', 'if False:\n        # A different', 'tests/test_document_identifiers.py::test_declared_absence_beats_a_positive_lexical_candidate'), ('all_expected_clauses', 'scripts/evaluate.py', 'return all(_clause_matches(ref, actual) is True for ref in references)', 'return any(_clause_matches(ref, actual) is True for ref in references)', 'tests/test_evaluation_gate.py::test_clause_check_uses_full_references')]
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
   killed=run.returncode==1 and ' failed' in run.stdout and 'ERROR collecting' not in run.stdout
   results.append({'mutation':name,'test':test,'killed':killed,'summary':run.stdout.strip().splitlines()[-1]})
  finally: file.write_text(source)
print(json.dumps(results,indent=2))
assert all(r['killed'] for r in results), results
