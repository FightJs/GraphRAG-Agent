# User API Key Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require every authenticated user to configure and verify encrypted DeepSeek, MinerU, and OpenRouter embedding credentials before protected GraphRAG workflows are available.

**Architecture:** A user-scoped credential vault stores Fernet-authenticated ciphertext in a unique `(user_id, provider)` row. A settings router validates a submitted secret before writing it, and a readiness dependency guards all business routers. React Query drives a guided provider wizard and an application route guard while provider callers receive a short-lived user-scoped secret instead of reading a shared API key.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Pydantic v2, `cryptography` Fernet, `httpx`, React 18, TypeScript, TanStack Query, Zustand, Vite, Tailwind CSS, Lucide React, pytest.

---

## File Structure

- Create: `backend/app/schemas/api_keys.py` - request and response contracts for the credential settings API.
- Create: `backend/app/services/key_vault_service.py` - encryption, credential storage, provider verification, and readiness logic.
- Create: `backend/app/routers/api_keys.py` - authenticated status, update, delete, and readiness endpoints.
- Create: `backend/tests/test_api_keys.py` - vault, router, ownership, validation, and readiness tests.
- Modify: `backend/app/config.py` - add deployment-owned encryption and provider endpoint settings.
- Modify: `backend/app/models/db_models.py` - add the `UserApiKey` entity and `User.api_keys` relationship.
- Modify: `backend/app/dependencies.py` - add the all-provider readiness dependency.
- Modify: `backend/app/main.py` - register the API-key router and attach readiness to business routers only.
- Modify: `backend/app/services/llm_client.py` - accept a supplied user-scoped DeepSeek key rather than read a global key.
- Modify: `backend/app/services/index_service.py` and `backend/app/services/qa_service.py` - resolve the owner credential at request/task time.
- Modify: `backend/pyproject.toml`, `backend/.env.example`, `backend/tests/conftest.py`, and `backend/tests/test_api.py` - declare encryption dependency/configuration and keep the existing suite intentionally ready.
- Modify: `frontend/src/types/index.ts` and `frontend/src/services/api.ts` - add settings API types and methods.
- Modify: `frontend/src/App.tsx` - add a readiness-aware route guard that permits `/settings` during onboarding.
- Modify: `frontend/src/pages/SettingsPage.tsx` - replace static key display with the approved guided provider connection UI.
- Create: `README.md` - product overview, accurate architecture, setup, deployment, security, and verification documentation.

### Task 1: Establish encrypted credential storage

**Files:**
- Create: `backend/tests/test_api_keys.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/config.py`
- Modify: `backend/app/models/db_models.py`
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Write failing encryption and persistence tests**

```python
from app.models.db_models import UserApiKey
from app.services import key_vault_service

async def _accept(provider: str, api_key: str) -> None:
    return None

@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session

@pytest.fixture
async def test_user(db_session):
    user = User(username="vaultuser", email="vault@example.test", password_hash="not-used")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user

async def test_store_key_encrypts_secret_and_returns_safe_status(db_session, test_user):
    status = await key_vault_service.store_verified_key(
        db_session, test_user.user_id, "deepseek", "deepseek-secret-1234"
    )
    row = await db_session.get(UserApiKey, status.key_id)
    assert row.encrypted_secret != "deepseek-secret-1234"
    assert status.key_hint == "1234"
    assert status.is_verified is True

def test_decrypt_requires_a_valid_deployment_key(monkeypatch):
    monkeypatch.setattr(key_vault_service.settings, "API_KEY_ENCRYPTION_KEY", "")
    with pytest.raises(RuntimeError, match="API_KEY_ENCRYPTION_KEY"):
        key_vault_service.encrypt_secret("value")
```

- [ ] **Step 2: Run the focused tests to verify the missing vault fails**

Run: `UV_CACHE_DIR=/tmp/graphrag-agent-uv-cache uv run python -m pytest tests/test_api_keys.py -k 'encrypts_secret or deployment_key' -v`

Expected: import failure for `UserApiKey` or `key_vault_service` because neither exists.

- [ ] **Step 3: Add direct cryptography dependency and configuration**

```toml
# backend/pyproject.toml
dependencies = [
    # existing dependencies
    "cryptography>=43.0.0",
    "greenlet>=3.0.0",
]
```

```python
# backend/app/config.py
API_KEY_ENCRYPTION_KEY: str = ""
DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
MINERU_BASE_URL: str = "https://mineru.net/api/v4"
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
OPENROUTER_EMBEDDING_MODEL: str = "qwen/qwen3-embedding-8b"
```

Use a deterministic, generated test-only Fernet key in `backend/tests/conftest.py` before importing `app.main`; do not set a production default.

- [ ] **Step 4: Add the model and vault primitives**

```python
# backend/app/models/db_models.py
class UserApiKey(Base):
    __tablename__ = "user_api_keys"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_api_key_provider"),)

    key_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.user_id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    key_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
```

```python
# backend/app/services/key_vault_service.py
def _fernet() -> Fernet:
    if not settings.API_KEY_ENCRYPTION_KEY:
        raise RuntimeError("API_KEY_ENCRYPTION_KEY must be configured")
    return Fernet(settings.API_KEY_ENCRYPTION_KEY.encode())

def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()

def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
```

Add `User.api_keys` with `cascade="all, delete-orphan"` and a `back_populates="owner"` relationship. Implement an upsert that replaces a provider row for its owner and returns only `provider`, `key_hint`, `is_verified`, and `verified_at`.

- [ ] **Step 5: Run the focused tests to verify encryption passes**

Run: `UV_CACHE_DIR=/tmp/graphrag-agent-uv-cache uv run python -m pytest tests/test_api_keys.py -k 'encrypts_secret or deployment_key' -v`

Expected: both tests pass; the database row does not equal the submitted secret.

- [ ] **Step 6: Commit the storage foundation**

```bash
git add backend/pyproject.toml backend/app/config.py backend/app/models/db_models.py backend/app/services/key_vault_service.py backend/tests/conftest.py backend/tests/test_api_keys.py
git commit -m "feat: add encrypted user API key storage"
```

### Task 2: Add provider verification and the credential settings API

**Files:**
- Modify: `backend/app/services/key_vault_service.py`
- Create: `backend/app/schemas/api_keys.py`
- Create: `backend/app/routers/api_keys.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_api_keys.py`

- [ ] **Step 1: Write failing provider and router tests**

```python
async def test_put_key_does_not_persist_when_validation_fails(client, auth_headers, monkeypatch):
    async def reject(*args, **kwargs):
        raise ValueError("验证失败：凭据无效")
    monkeypatch.setattr(key_vault_service, "verify_provider", reject)

    response = await client.put(
        "/api/v2/settings/api-keys/deepseek",
        json={"api_key": "invalid-value"}, headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["msg"] == "验证失败：凭据无效"

async def test_list_keys_returns_status_without_plaintext(client, auth_headers, monkeypatch):
    monkeypatch.setattr(key_vault_service, "verify_provider", _accept)
    await client.put("/api/v2/settings/api-keys/deepseek", json={"api_key": "secret-9876"}, headers=auth_headers)
    response = await client.get("/api/v2/settings/api-keys", headers=auth_headers)
    assert response.status_code == 200
    assert "secret-9876" not in response.text
    status = next(item for item in response.json()["data"]["providers"] if item["provider"] == "deepseek")
    assert status["key_hint"] == "9876"
```

- [ ] **Step 2: Run router tests to verify they fail before endpoints exist**

Run: `UV_CACHE_DIR=/tmp/graphrag-agent-uv-cache uv run python -m pytest tests/test_api_keys.py -k 'persist or list_keys' -v`

Expected: `404 Not Found` or missing service symbol.

- [ ] **Step 3: Define exact Pydantic contracts**

```python
# backend/app/schemas/api_keys.py
ProviderName = Literal["deepseek", "mineru", "embedding"]

class ApiKeyUpsert(BaseModel):
    api_key: str = Field(min_length=8, max_length=4096)

class ProviderStatus(BaseModel):
    provider: ProviderName
    configured: bool
    is_verified: bool
    key_hint: str | None = None
    verified_at: datetime | None = None

class ApiKeyStatusResponse(BaseModel):
    providers: list[ProviderStatus]
    ready: bool
```

- [ ] **Step 4: Implement provider adapters with no secret logging**

```python
# backend/app/services/key_vault_service.py
async def verify_provider(provider: ProviderName, api_key: str) -> None:
    if provider == "deepseek":
        await _verify_deepseek(api_key)
    elif provider == "mineru":
        await _verify_mineru(api_key)
    else:
        await _verify_openrouter_embedding(api_key)

async def _verify_openrouter_embedding(api_key: str) -> None:
    payload = {"model": settings.OPENROUTER_EMBEDDING_MODEL, "input": "GraphRAG health check"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{settings.OPENROUTER_BASE_URL}/embeddings",
            headers={"Authorization": f"Bearer {api_key}"}, json=payload,
        )
    response.raise_for_status()
    if not response.json().get("data"):
        raise ValueError("验证失败：Embedding 服务未返回向量")
```

The MinerU adapter generates a tiny valid PDF in memory, posts it to `/extract/task` as multipart form data, and treats only a successful accepted task response as valid. It must raise a generic Chinese validation error from status codes without embedding the key or provider response body.

- [ ] **Step 5: Implement authenticated settings endpoints**

```python
# backend/app/routers/api_keys.py
router = APIRouter(prefix="/api/v2/settings/api-keys", tags=["api-keys"])

@router.get("")
async def list_api_keys(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return Resp.ok(await key_vault_service.get_statuses(db, user.user_id))

@router.put("/{provider}")
async def save_api_key(provider: ProviderName, body: ApiKeyUpsert, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await key_vault_service.verify_provider(provider, body.api_key)
    return Resp.ok(await key_vault_service.store_verified_key(db, user.user_id, provider, body.api_key))

@router.delete("/{provider}")
async def delete_api_key(provider: ProviderName, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await key_vault_service.delete_key(db, user.user_id, provider)
    return Resp.ok(msg="API Key 已删除")
```

Register `api_keys.router` in `backend/app/main.py` without the readiness dependency.

- [ ] **Step 6: Run the API-key test file and verify green**

Run: `UV_CACHE_DIR=/tmp/graphrag-agent-uv-cache uv run python -m pytest tests/test_api_keys.py -v`

Expected: encrypted persistence, failed validation, safe status response, update, deletion, and ownership tests pass with mocked outbound HTTP.

- [ ] **Step 7: Commit the API and verification flow**

```bash
git add backend/app/services/key_vault_service.py backend/app/schemas/api_keys.py backend/app/routers/api_keys.py backend/app/main.py backend/tests/test_api_keys.py
git commit -m "feat: add API key verification endpoints"
```

### Task 3: Enforce full-provider readiness and pass user-scoped credentials

**Files:**
- Modify: `backend/app/dependencies.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/llm_client.py`
- Modify: `backend/app/services/index_service.py`
- Modify: `backend/app/services/qa_service.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_api.py`
- Modify: `backend/tests/test_api_keys.py`

- [ ] **Step 1: Write failing readiness tests**

```python
async def test_business_api_rejects_user_until_all_three_keys_are_verified(client, auth_headers):
    response = await client.get("/api/v2/kbs", headers=auth_headers)
    assert response.status_code == 428
    assert response.json()["detail"]["code"] == 4281
    assert set(response.json()["detail"]["missing_providers"]) == {"deepseek", "mineru", "embedding"}

async def test_business_api_allows_user_after_all_provider_rows_exist(client, ready_auth_headers):
    response = await client.get("/api/v2/kbs", headers=ready_auth_headers)
    assert response.status_code == 200
```

- [ ] **Step 2: Run readiness tests and confirm the gate is absent**

Run: `UV_CACHE_DIR=/tmp/graphrag-agent-uv-cache uv run python -m pytest tests/test_api_keys.py -k 'business_api' -v`

Expected: first test receives `200` before the readiness dependency exists.

- [ ] **Step 3: Implement the readiness dependency and attach it narrowly**

```python
# backend/app/dependencies.py
async def require_provider_readiness(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    missing = await key_vault_service.missing_providers(db, user.user_id)
    if missing:
        raise HTTPException(
            status_code=428,
            detail={"code": 4281, "msg": "请先完成全部 API Key 配置", "missing_providers": missing},
        )
    return user
```

Register the dependency only while including `kbs`, `documents`, `index`, `kg`, `qa`, and `webhooks` routers. Keep `health`, `auth`, and `api_keys` excluded so first-time setup remains possible.

- [ ] **Step 4: Replace global DeepSeek credential reads**

```python
# backend/app/services/llm_client.py
async def chat_complete(api_key: str, messages: list[dict], temperature: float = 0.2, max_tokens: int = 2048) -> tuple[str, dict]:
    response = await client.post(
        f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"}, json=payload,
    )
```

Update Q&A functions to resolve `deepseek` for `user_id` immediately before calling `chat_complete` or `chat_stream`. Update `start_index_task` to pass `owner_id` into `_run_pipeline`, resolve the same provider there, and call the revised graph extraction client. Remove user-facing mock-mode branching caused by a missing global `DEEPSEEK_API_KEY`.

- [ ] **Step 5: Seed verified key rows only in existing business-test fixtures**

```python
@pytest.fixture(scope="session")
async def ready_auth_headers(client, auth_headers):
    me = await client.get("/api/v2/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["user_id"]
    async with AsyncSessionLocal() as db_session:
        for provider in ("deepseek", "mineru", "embedding"):
            await key_vault_service.store_verified_key(db_session, user_id, provider, f"test-{provider}-secret")
    return auth_headers
```

Use `ready_auth_headers` for existing knowledge-base, document, index, graph, Q&A, and webhook fixtures. Keep auth and new readiness tests on unseeded users so the gate remains genuinely tested.

- [ ] **Step 6: Run gate and full backend suite**

Run: `UV_CACHE_DIR=/tmp/graphrag-agent-uv-cache uv run python -m pytest -v`

Expected: the gate tests pass, existing API tests receive ready credentials from fixtures, and no test makes a live provider request.

- [ ] **Step 7: Commit the readiness enforcement**

```bash
git add backend/app/dependencies.py backend/app/main.py backend/app/services/llm_client.py backend/app/services/index_service.py backend/app/services/qa_service.py backend/tests/conftest.py backend/tests/test_api.py backend/tests/test_api_keys.py
git commit -m "feat: require verified provider setup"
```

### Task 4: Add frontend API types and onboarding route guard

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write a focused type-level and route-guard test or compile assertion**

```ts
export type ApiKeyProvider = 'deepseek' | 'mineru' | 'embedding'

export interface ApiKeyReadiness {
  ready: boolean
  providers: ApiKeyProviderStatus[]
}
```

Add a small React route test if a test runner is introduced; otherwise use TypeScript compilation as the red/green check for the typed API contract before rendering the wizard.

- [ ] **Step 2: Run TypeScript compilation before implementation**

Run: `npx tsc --noEmit`

Expected: failure after importing the not-yet-defined `apiKeyApi` contract into the guard.

- [ ] **Step 3: Implement the settings API client**

```ts
export const apiKeyApi = {
  status: () => http.get<{ data: ApiKeyReadiness }>('/v2/settings/api-keys').then(d<ApiKeyReadiness>),
  readiness: () => http.get<{ data: ApiKeyReadiness }>('/v2/settings/api-keys/readiness').then(d<ApiKeyReadiness>),
  save: (provider: ApiKeyProvider, api_key: string) =>
    http.put<{ data: ApiKeyProviderStatus }>(`/v2/settings/api-keys/${provider}`, { api_key }).then(d<ApiKeyProviderStatus>),
  remove: (provider: ApiKeyProvider) => http.delete(`/v2/settings/api-keys/${provider}`),
}
```

- [ ] **Step 4: Implement a settings-safe route guard**

```tsx
function RequireReady({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const { data, isLoading } = useQuery({ queryKey: ['api-key-readiness'], queryFn: apiKeyApi.readiness })
  if (isLoading) return <div className="h-full skeleton" aria-label="Loading account setup" />
  if (!data?.ready && location.pathname !== '/settings') return <Navigate to="/settings" replace />
  return <>{children}</>
}
```

Wrap the non-settings child routes in `RequireReady`; leave the authenticated `/settings` route reachable. Treat a `428` interceptor error as a settings redirect rather than logging a false generic failure.

- [ ] **Step 5: Verify frontend typing after the API contract exists**

Run: `npx tsc --noEmit`

Expected: exit code `0`.

- [ ] **Step 6: Commit the API contract and guard**

```bash
git add frontend/src/types/index.ts frontend/src/services/api.ts frontend/src/App.tsx
git commit -m "feat: gate frontend on API key readiness"
```

### Task 5: Build the guided API Key settings experience

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: Write the failing UI state contract**

```ts
const PROVIDERS: ProviderDescriptor[] = [
  { id: 'deepseek', label: 'DeepSeek', detail: 'Chat and knowledge graph extraction' },
  { id: 'mineru', label: 'MinerU', detail: 'Cloud document parsing' },
  { id: 'embedding', label: 'OpenRouter Embedding', detail: 'qwen/qwen3-embedding-8b' },
]
```

Define the expected states as `not_configured`, `verifying`, and `verified`; add component tests if a frontend test harness is present, or use an explicit manual checklist alongside the build command for this existing Vite-only project.

- [ ] **Step 2: Run the frontend build before replacing the static screen**

Run: `npm run build`

Expected: current static page builds successfully; no wizard controls exist yet.

- [ ] **Step 3: Replace the API Key tab with the selected wizard**

```tsx
const [selectedProvider, setSelectedProvider] = useState<ApiKeyProvider | null>(null)
const [apiKey, setApiKey] = useState('')

const saveKey = useMutation({
  mutationFn: ({ provider, apiKey }: { provider: ApiKeyProvider; apiKey: string }) => apiKeyApi.save(provider, apiKey),
  onSuccess: () => {
    setApiKey('')
    queryClient.invalidateQueries({ queryKey: ['api-key-status'] })
    queryClient.invalidateQueries({ queryKey: ['api-key-readiness'] })
    toast.success('连接已验证并安全保存')
  },
})
```

Render one provider-selection step, a password input step, and a verification/result step. Make the MinerU confirmation state disclose that it creates a minimal verification task. Disable duplicate submission while verifying; allow replace and delete actions only for the selected provider. Use `KeyRound`, `ShieldCheck`, `ArrowRight`, `Trash2`, and `RotateCcw` from Lucide with accessible `aria-label` values and compact tooltips.

- [ ] **Step 4: Verify the wizard build and manual safety checklist**

Run: `npm run build`

Expected: exit code `0`.

Manual checklist: submit each provider through the password input, verify that no full key appears after save, verify the key clears on success/error, verify a missing provider redirects a user back to Settings, and verify a confirmed three-provider state unlocks navigation.

- [ ] **Step 5: Commit the settings UI**

```bash
git add frontend/src/pages/SettingsPage.tsx frontend/src/services/api.ts frontend/src/types/index.ts
git commit -m "feat: add guided API key onboarding"
```

### Task 6: Document the project and safe deployment

**Files:**
- Create: `README.md`
- Modify: `backend/.env.example`

- [ ] **Step 1: Write the README content**

```markdown
# GraphRAG Agent

GraphRAG Agent is a full-stack knowledge-workbench that turns uploaded documents into an inspectable knowledge graph and supports graph-grounded Q&A.

## Architecture

React/Vite -> FastAPI -> SQLAlchemy -> document/index/KG services
                              |-> DeepSeek
                              |-> MinerU
                              |-> OpenRouter embeddings
```

Document the actual React/Vite, FastAPI, SQLAlchemy, SQLite/PostgreSQL-compatible, TanStack Query, Zustand, document parsing, graph extraction, and OpenRouter/MinerU/DeepSeek boundaries. Include local commands from root and each component's existing `CLAUDE.md`, provider onboarding steps, `API_KEY_ENCRYPTION_KEY` generation/secret-manager requirements, testing/build commands, and a clear statement that the current retrieval implementation remains keyword-based until vector persistence is explicitly added.

- [ ] **Step 2: Add environment template entries**

```dotenv
# Required in deployed environments; generate once and store in your secret manager.
API_KEY_ENCRYPTION_KEY=

# Provider keys are user-managed in Settings and must remain empty here.
DEEPSEEK_API_KEY=
MINERU_API_KEY=
```

Do not add real keys, test keys, or copied chat credentials to the README or `.env.example`.

- [ ] **Step 3: Verify documentation safety**

Run: `rg -n 'sk-or-|sk-[A-Za-z0-9_-]{20,}|API_KEY_ENCRYPTION_KEY=.+' README.md backend/.env.example`

Expected: no API key values; the encryption variable appears only with an empty assignment or a descriptive explanation.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md backend/.env.example
git commit -m "docs: document secure GraphRAG deployment"
```

### Task 7: Run final verification and publish the completed feature

**Files:**
- Verify: all files above

- [ ] **Step 1: Run backend tests**

Run: `UV_CACHE_DIR=/tmp/graphrag-agent-uv-cache uv run python -m pytest -v`

Expected: all existing API tests and API-key tests pass without live provider calls.

- [ ] **Step 2: Run frontend type and build checks**

Run: `npx tsc --noEmit && npm run build`

Expected: both commands exit `0`.

- [ ] **Step 3: Run staged secret and generated-data checks**

Run: `git grep -n -E 'sk-or-|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]+' HEAD`

Expected: no output and exit code `1`; no `.env`, PDFs, output directories, local IDE settings, or plaintext API credentials appear in `git ls-tree -r --name-only HEAD`.

- [ ] **Step 4: Verify the live flow**

Run: start the backend and frontend, register a fresh user, confirm protected pages redirect to Settings, configure all three providers with fresh keys, observe three verified states, then confirm the knowledge-base route is available. Do not use the previously pasted OpenRouter key; use a newly rotated key entered only through the UI.

- [ ] **Step 5: Commit and push the finished feature**

```bash
git status -sb
git push origin main
```

Expected: `main` tracks `origin/main` with no unintended files.
