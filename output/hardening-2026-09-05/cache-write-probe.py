from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import uuid, json, logging
from sqlalchemy import delete, select
from app.extraction import cache
from app.db.session import session_scope
from app.db.models.cache import ExtractionCacheRow
from app.schemas.common import DocumentKind
key=uuid.uuid4().hex*2
barrier=Barrier(8)
warnings=[]
class Capture(logging.Handler):
 def emit(self,record): warnings.append(record.getMessage())
handler=Capture(level=logging.WARNING); cache.logger.addHandler(handler)
def write(i):
 barrier.wait(timeout=10)
 cache.store(key,DocumentKind.NOTIFICATION,{'writer':i},model=f'probe-{i}')
try:
 with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(write,range(8)))
 with session_scope() as s:
  rows=s.scalars(select(ExtractionCacheRow).where(ExtractionCacheRow.content_hash==key)).all()
  assert len(rows)==1
  assert rows[0].model==f"probe-{rows[0].payload['writer']}"
  assert not warnings, warnings
  print(json.dumps({'writers':8,'rows':1,'payload_and_provider_match':True,'warnings':warnings}))
finally:
 cache.logger.removeHandler(handler)
 with session_scope() as s: s.execute(delete(ExtractionCacheRow).where(ExtractionCacheRow.content_hash==key))
