# User API Key Onboarding Design

## Purpose

Replace the administrator-managed API Key display with a user-owned setup flow.
Each authenticated user must configure and validate all three required providers before the application allows access to knowledge-base, document indexing, graph, or Q&A operations:

- DeepSeek: chat completion and knowledge-graph extraction
- MinerU: cloud document parsing
- OpenRouter Embedding: `qwen/qwen3-embedding-8b`

The system stores only encrypted provider credentials. It never returns a plaintext key to the browser after submission.

## Constraints

- The existing FastAPI service, SQLite development database, React SPA, JWT access token, and React Query patterns remain the integration points.
- Production deployments must set the encryption key through a cloud secret manager, KMS-backed secret, or equivalent environment-secret mechanism. It must never be committed, stored in the database, or derived from a user password.
- The user-provided OpenRouter key is not seeded into source, tests, documentation, or local configuration. It is entered only through the authenticated application UI.
- The current backend uses a mock fallback when its global DeepSeek key is absent. The new feature removes that fallback for user-facing protected workflows: incomplete provider setup is a prerequisite error, not an implicit mock-mode success.

## Chosen Approach

Use application-level authenticated encryption with a deployment-provided `API_KEY_ENCRYPTION_KEY` as the first release design.

This approach keeps keys isolated by user, works with the project's current SQLite/PostgreSQL-compatible SQLAlchemy model, and has a clear production upgrade path to envelope encryption with AWS KMS, GCP KMS, Azure Key Vault, or HashiCorp Vault. The database contains ciphertext only; the service decrypts a key in memory only for a provider request.

Cloud KMS envelope encryption is intentionally deferred because it adds cloud-vendor provisioning and operational complexity. A shared `.env` credential is rejected because it cannot represent per-user ownership or revocation.

## Data Model

Add a `UserApiKey` model with one record per `(user_id, provider)` pair.

| Field | Purpose |
| --- | --- |
| `key_id` | UUID primary key |
| `user_id` | Foreign key to the owning user |
| `provider` | `deepseek`, `mineru`, or `embedding` |
| `encrypted_secret` | Fernet/AES authenticated ciphertext |
| `key_hint` | Last four safe-to-display characters only |
| `is_verified` | Whether the latest validation succeeded |
| `verified_at` | UTC validation timestamp |
| `created_at`, `updated_at` | Audit timestamps |

The unique database constraint on `(user_id, provider)` makes repeated setup an update rather than a duplicate. Validation errors are returned for the current request but are not persisted with the secret.

## Provider Verification

The setup wizard validates the key before writing it to the database.

| Provider | Verification request | Success condition |
| --- | --- | --- |
| DeepSeek | Minimal `chat/completions` request against `https://api.deepseek.com/v1` using `deepseek-chat` | HTTP success with a response payload |
| MinerU | Minimal authenticated parsing task against `https://mineru.net/api/v4/extract/task` using a generated one-page test PDF | Task accepted by MinerU |
| OpenRouter Embedding | OpenAI-compatible embedding request to `https://openrouter.ai/api/v1/embeddings` using `qwen/qwen3-embedding-8b` and a short health-check input | HTTP success with an embedding vector |

MinerU verification creates a minimal external task and can consume provider quota. The UI must state this before the request. The OpenRouter integration follows the official Quickstart's bearer-token and `/api/v1` conventions; optional attribution headers may be added from deployment configuration, never from user input.

## API Contract

Add an authenticated router at `/api/v2/settings/api-keys`.

| Method | Endpoint | Behaviour |
| --- | --- | --- |
| `GET` | `/api/v2/settings/api-keys` | Returns the three providers' configuration and verification states, safe hint, and verification timestamp; never ciphertext or plaintext |
| `PUT` | `/api/v2/settings/api-keys/{provider}` | Accepts a plaintext key once, validates it externally, encrypts it, and upserts the owner's record only on success |
| `DELETE` | `/api/v2/settings/api-keys/{provider}` | Removes only the current user's provider key |
| `GET` | `/api/v2/settings/api-keys/readiness` | Returns whether all three providers have valid, verified credentials |

Invalid provider names, empty keys, unauthenticated requests, and cross-user access are rejected. Provider keys are never included in logs, validation error bodies, analytics events, or exception messages.

## Backend Flow

1. `key_vault_service` owns encryption, decryption, provider adapters, status lookup, and readiness calculation.
2. A `require_provider_readiness` dependency guards business routers. Auth, health, and API-key setup endpoints remain reachable so a new user can finish onboarding.
3. The dependency returns a structured prerequisite error containing only missing provider names. It does not disclose whether another user's key exists.
4. DeepSeek callers receive the current user ID and resolve a decrypted key just before the outgoing request. Background indexing propagates the document owner ID into its task runner.
5. MinerU and OpenRouter provider clients use the same user-scoped resolution boundary. No provider client reads a user API key from global application settings.
6. Decryption stays in local variables for the duration of the request and is not cached across users.

## Frontend Flow

The API Key tab becomes a three-step provider onboarding flow selected during design:

1. Select the next provider and read its role.
2. Enter the key in a password field; the value remains only in component state while submitting.
3. Run verification, show the result, then advance to the next provider.

The summary lists DeepSeek, MinerU, and Embedding with `Not configured`, `Verifying`, or `Verified` states. Verified keys show a safe suffix only. Users can replace or remove a provider key. A readiness guard directs users to this page until all three cards are verified.

The UI uses the existing setting sidebar, React Query mutation and invalidation patterns, toast feedback, Lucide icons, keyboard-accessible form controls, and error states. It does not put a secret in browser storage or render a submitted value after save.

## README Scope

Add a root `README.md` that documents the system accurately:

- Product purpose and GraphRAG workflow
- Architecture diagram covering React/Vite, FastAPI, SQLAlchemy, document indexing, knowledge graph, and provider boundary
- Technology stack and why each component is used
- Local startup, environment configuration, test, and build commands based on the repository's existing `CLAUDE.md` guidance
- User API Key onboarding and cloud deployment security requirements
- API overview, project structure, and known implementation boundaries

The README may describe the design as a production-oriented architecture, but must not claim that an unimplemented vector database, external parsing path, or provider capability is already in production.

## Test Plan

Test-first implementation covers:

- Encryption round-trip and failure when the application encryption key is absent or invalid
- User ownership isolation and no plaintext/ciphertext leakage in list responses
- Provider validation success and failure with mocked HTTP transports
- Failed validation never persisting a key
- Readiness transitions from missing to complete only after all three verified providers exist
- Business endpoint rejection when setup is incomplete and access after complete setup
- API Key router authentication and delete/update behaviour
- Frontend service typing, component states, TypeScript compilation, and production build

Outbound provider calls are mocked in automated tests. Manual verification uses user-entered credentials from the live application rather than test fixtures.

## Acceptance Criteria

- A new authenticated user cannot use protected product functions until all three providers are verified.
- The user can complete setup in the selected guided flow and sees no full key after submission.
- Database rows contain only encrypted API key material and a safe hint.
- The backend resolves credentials by the authenticated user, not a shared environment credential.
- The OpenRouter embedding validator targets `qwen/qwen3-embedding-8b` through the OpenRouter API.
- The root README documents setup, architecture, technologies, security, and deployment without including secrets.
