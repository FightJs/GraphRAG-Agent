import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.common import Resp
from app.services import index_service
from app.dependencies import get_current_user
from app.models.db_models import User

router = APIRouter(tags=["index"])

@router.post("/api/v1/documents/{doc_id}/index", status_code=202)
async def start_index(doc_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        task = await index_service.start_index_task(db, doc_id, user.user_id)
    except ValueError as e:
        code, msg = str(e).split(":", 1)
        raise HTTPException(400, {"code": int(code), "msg": msg})
    return Resp.ok(_task_dict(task))

@router.post("/api/v2/index/batch", status_code=202)
async def batch_index(body: dict, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    doc_ids = body.get("doc_ids", [])
    if not doc_ids or len(doc_ids) > 10:
        raise HTTPException(400, {"code": 4007, "msg": "doc_ids 需1-10个"})
    tasks, skipped = [], []
    for doc_id in doc_ids:
        try:
            task = await index_service.start_index_task(db, doc_id, user.user_id)
            tasks.append({"task_id": task.task_id, "doc_id": doc_id, "status": "pending"})
        except ValueError:
            skipped.append(doc_id)
    return Resp.ok({"tasks": tasks, "skipped": skipped})

@router.get("/api/v1/index/tasks/{task_id}")
async def get_task(task_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        task = await index_service.get_task(db, task_id)
    except ValueError as e:
        raise HTTPException(404, {"code": 4042, "msg": str(e).split(":", 1)[-1]})
    return Resp.ok(_task_dict(task))

@router.post("/api/v1/index/tasks/{task_id}/cancel")
async def cancel_index_task(task_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        result = await index_service.cancel_task(db, task_id, user.user_id)
    except ValueError as e:
        code, msg = str(e).split(":", 1)
        raise HTTPException(400 if code != "4041" else 404, {"code": int(code), "msg": msg})
    return Resp.ok(result)

def _task_dict(task) -> dict:
    return {
        "task_id": task.task_id, "doc_id": task.doc_id, "status": task.status,
        "progress": task.progress, "stages": json.loads(task.stages_json),
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() + "Z",
        "updated_at": task.updated_at.isoformat() + "Z",
    }
