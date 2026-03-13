import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.auth_routes import router as auth_router
from app.core.auth import SESSION_COOKIE, load_session
from app.core.user_context import set_current_user

app = FastAPI(title="Roleplay Web API", version="0.1.0")
logger = logging.getLogger("roleplay.api")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(router)


@app.middleware("http")
async def user_context_middleware(request: Request, call_next):
    # Parse signed session cookie and store current user in a contextvar.
    token = request.cookies.get(SESSION_COOKIE, "")
    sess = load_session(token)
    set_current_user(sess.username if sess else None)
    try:
        return await call_next(request)
    finally:
        set_current_user(None)


@app.middleware("http")
async def api_log_middleware(request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if request.url.path.startswith("/api/") and response.status_code < 400:
        logger.info("%s %s -> %s (%sms)", request.method, request.url.path, response.status_code, elapsed_ms)
    return response
