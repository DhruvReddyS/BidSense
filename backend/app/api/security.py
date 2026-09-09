"""Small-process security perimeter: headers and brute-force throttling."""
from __future__ import annotations
import time
from collections import defaultdict,deque
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

class SecurityMiddleware(BaseHTTPMiddleware):
    attempts: dict[str,deque[float]]=defaultdict(deque)
    async def dispatch(self,request,call_next):
        bucket=None
        if request.url.path in {"/api/auth/login","/api/auth/register"}:
            key=request.client.host if request.client else "unknown";now=time.monotonic();bucket=self.attempts[key]
            while bucket and bucket[0]<now-60: bucket.popleft()
            if len(bucket)>=10:return JSONResponse({"detail":"Too many authentication attempts; retry in one minute"},status_code=429)
        response=await call_next(request)
        if bucket is not None and response.status_code in {401,403}: bucket.append(time.monotonic())
        response.headers["X-Content-Type-Options"]="nosniff";response.headers["X-Frame-Options"]="DENY";response.headers["Referrer-Policy"]="same-origin";response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"
        return response
