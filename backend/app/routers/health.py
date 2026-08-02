from fastapi import APIRouter
from datetime import datetime

router = APIRouter(prefix="/api/v1", tags=["health"])

@router.get("/health")
async def health():
    return {"code": 0, "data": {"status": "ok", "version": "2.0.0", "timestamp": datetime.utcnow().isoformat() + "Z"}}
