from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time, json
from fastapi.testclient import TestClient
from app.api.main import app
from app.config import settings
from app.documents import store_document
from app.documents.render import _page_words
path=Path('../data/notifications/NOTIF_civilworks_02.pdf')
digest=store_document(path)
pages=[1,100,200,382]
queries={page:' '.join(w[0] for w in _page_words(str(path),page)[10:20]) for page in pages}
def run(i):
 page=pages[i%4]
 client=TestClient(app)
 started=time.perf_counter()
 try:
  response=client.get(f'/api/documents/{digest}/page/{page}',params={'highlight':queries[page]})
  assert response.status_code==200,response.text[:100]
  assert response.headers['x-page']==str(page)
  assert response.headers['x-page-count']=='382'
  assert int(response.headers['x-highlights'])>0
  assert response.content.startswith(b'\x89PNG')
  return {'page':page,'seconds':round(time.perf_counter()-started,3),'bytes':len(response.content),'highlights':int(response.headers['x-highlights'])}
 finally: client.close()
started=time.perf_counter()
with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(run,range(12)))
print(json.dumps({'mode':'FastAPI TestClient concurrent real PDF rendering; no external HTTP server','requests':12,'workers':4,'dpi':settings.page_render_dpi,'pages':382,'wall_seconds':round(time.perf_counter()-started,3),'results':results},indent=2))
