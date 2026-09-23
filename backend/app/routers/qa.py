from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.qa import QARequest, KBQARequest, FeedbackRequest
from app.schemas.common import Resp
from app.services import qa_service
from app.dependencies import get_current_user
from app.models.db_models import User

router = APIRouter(tags=["qa"])

@router.post("/api/v1/qa/query")
async def query(body: QARequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    mode = body.options.retrieval_mode
    if body.stream:
        return StreamingResponse(
            qa_service.qa_stream(db, body.doc_id, body.question, user.user_id, mode),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    try:
        result = await qa_service.qa_sync(db, body.doc_id, body.question, user.user_id, mode)
    except ValueError as e:
        code, msg = str(e).split(":", 1)
        raise HTTPException(400, {"code": int(code), "msg": msg})
    return Resp.ok(result)

@router.post("/api/v2/qa/kb-query")
async def kb_query(body: KBQARequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if len(body.doc_ids) > 10:
        raise HTTPException(400, {"code": 4007, "msg": "最多同时选10份文档参与联合检索"})
    mode = body.options.retrieval_mode
    if body.stream:
        return StreamingResponse(
            qa_service.kb_qa_stream(db, body.kb_id, body.doc_ids, body.question, user.user_id, mode),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    # non-stream: collect SSE and return plain JSON
    full = ""
    async for chunk in qa_service.kb_qa_stream(db, body.kb_id, body.doc_ids, body.question, user.user_id, mode):
        if chunk.startswith("event: done"):
            import json
            data_line = [l for l in chunk.split("\n") if l.startswith("data:")]
            if data_line:
                full = json.loads(data_line[0][5:])
    return Resp.ok(full or {"msg": "no result"})

@router.get("/api/v1/qa/history")
async def history(
    kb_id: str | None = None, doc_id: str | None = None,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    records = await qa_service.get_history(db, user.user_id, kb_id, doc_id)
    return Resp.ok([{
        "query_id": r.query_id, "doc_id": r.doc_id, "kb_id": r.kb_id,
        "question": r.question, "answer": r.answer,
        "retrieval_mode": r.retrieval_mode, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
        "created_at": r.created_at.isoformat() + "Z",
    } for r in records])

@router.post("/api/v2/qa/{query_id}/feedback", status_code=201)
async def feedback(
    query_id: str, body: FeedbackRequest,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    if body.rating not in ("positive", "negative"):
        raise HTTPException(400, {"code": 4001, "msg": "rating 需为 positive 或 negative"})
    try:
        result = await qa_service.submit_feedback(db, query_id, user.user_id, body.rating, body.comment)
    except ValueError as e:
        code, msg = str(e).split(":", 1)
        raise HTTPException(409, {"code": int(code), "msg": msg})
    return Resp.ok(result)
