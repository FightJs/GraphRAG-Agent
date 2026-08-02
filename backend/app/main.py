from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.database import init_db
from app.dependencies import require_provider_readiness
from app.routers import api_keys, health, auth, kbs, documents, index, kg, qa, webhooks

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(
    title="GraphRAG Agent API",
    version="2.0.0",
    description="多模态知识图谱问答系统后端服务",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"code": 5000, "msg": str(exc)})

for r in [health.router, auth.router, api_keys.router]:
    app.include_router(r)

for r in [kbs.router, documents.router, index.router, kg.router, qa.router, webhooks.router]:
    app.include_router(r, dependencies=[Depends(require_provider_readiness)])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.PORT, reload=True)
