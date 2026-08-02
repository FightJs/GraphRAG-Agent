from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.db_models import User
from app.schemas.api_keys import ApiKeyUpsert, ProviderName
from app.schemas.common import Resp
from app.services import key_vault_service

router = APIRouter(prefix="/api/v2/settings/api-keys", tags=["api-keys"])


@router.get("")
async def list_api_keys(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return Resp.ok(await key_vault_service.get_statuses(db, user.user_id))


@router.put("/{provider}")
async def save_api_key(
    provider: ProviderName,
    body: ApiKeyUpsert,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await key_vault_service.verify_provider(provider, body.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"msg": str(exc)}) from exc
    status = await key_vault_service.store_verified_key(db, user.user_id, provider, body.api_key)
    return Resp.ok(key_vault_service.status_to_dict(status))


@router.delete("/{provider}")
async def delete_api_key(
    provider: ProviderName,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await key_vault_service.delete_key(db, user.user_id, provider)
    return Resp.ok(msg="API Key 已删除")
