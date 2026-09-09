"""Remove the Indic copy-text protection in an isolated copy and prove the test fails."""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
root=Path.cwd()
with tempfile.TemporaryDirectory(prefix='bidsense-pdf-mutation-') as tmp:
 target=Path(tmp)/'backend';target.mkdir()
 for folder in ('app','tests'):
  shutil.copytree(root/folder,target/folder,ignore=shutil.ignore_patterns('__pycache__'))
 shutil.copy(root/'pytest.ini',target/'pytest.ini')
 file=target/'app/compliance/pdf_document.py'
 source=file.read_text();before='draw.draw_text = with_actual_text'
 assert source.count(before)==1
 file.write_text(source.replace(before,'draw.draw_text = original'))
 env=os.environ.copy();env['PYTHONPATH']=str(target)
 run=subprocess.run([sys.executable,'-m','pytest','tests/test_unicode_export.py::test_indic_and_currency_text_survive_copy_and_both_formats','-q'],cwd=target,env=env,capture_output=True,text=True,timeout=90)
 killed=run.returncode==1 and ' failed' in run.stdout and 'ERROR collecting' not in run.stdout
 print(json.dumps({'mutation':'remove_actual_text','killed':killed,'summary':run.stdout.strip().splitlines()[-1]},indent=2))
 assert killed,run.stdout+run.stderr
