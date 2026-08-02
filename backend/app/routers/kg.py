from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.kg import KGEditRequest
from app.schemas.common import Resp
from app.services import kg_service
from app.dependencies import get_current_user
from app.models.db_models import User

router = APIRouter(tags=["kg"])

@router.get("/api/v1/kg/{doc_id}")
async def get_kg(doc_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        kg = await kg_service.get_kg(db, doc_id, user.user_id)
    except ValueError as e:
        code, msg = str(e).split(":", 1)
        raise HTTPException(404, {"code": int(code), "msg": msg})
    return Resp.ok(kg)

@router.patch("/api/v2/kg/{doc_id}")
async def edit_kg(doc_id: str, body: KGEditRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        result = await kg_service.apply_kg_operations(db, doc_id, user.user_id, [op.model_dump() for op in body.operations])
    except ValueError as e:
        code, msg = str(e).split(":", 1)
        status = 403 if code == "4031" else 422 if code == "4222" else 404
        raise HTTPException(status, {"code": int(code), "msg": msg})
    return Resp.ok(result)
