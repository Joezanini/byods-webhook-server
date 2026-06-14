# Implementation Plan: AWS CI/CD Pipeline for BYODS Webhook Server

**Branch**: `004-aws-cicd-pipeline` | **Date**: 2026-06-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-aws-cicd-pipeline/spec.md`  
**User addition**: Design the CodePipeline/CodeBuild/ECS pipeline against existing `infra/` assets (`buildspec.yml`, `deploy.sh`, CDK stack).

## Summary

Add AWS-native continuous delivery using **CodePipeline V2** + **CodeBuild** orchestrating the same steps operators run today via `infra/scripts/deploy.sh`. A new CDK stack **`ByodsPipelineStack`** provisions two pipelines: **`byods-webhook-release`** (push to `main` → optional infra → build/push ECR → ECS force-new-deployment → HTTP smoke tests) and **`byods-webhook-pr-validation`** (PR → pytest + docker build, no deploy). Reuse existing [`infra/buildspec.yml`](../../infra/buildspec.yml) for image build; add four new buildspecs for infra, deploy, verify, and PR test. No application code or Webex integration changes.

## Technical Context

**Language/Version**: Python 3.11+ (CDK infra), Bash (buildspec commands), YAML (buildspecs)

**Primary Dependencies**: AWS CDK (`aws-cdk-lib`), CodePipeline V2, CodeBuild, CodeStar Connections (GitHub), ECR, ECS Fargate, CloudFormation, existing `ByodsWebhookStack`

**Storage**: S3 artifact bucket (pipeline artifacts); ECR `byods-webhook-server`; Secrets Manager unchanged (`byods-webhook-server/webex`)

**Testing**: PR pipeline runs `pytest`; release Verify stage runs curl smoke tests; manual validation per [quickstart.md](./quickstart.md)

**Target Platform**: AWS `us-east-1` — same account/region as production ECS deployment

**Project Type**: Infrastructure/delivery automation layered on existing containerized FastAPI + gRPC service

**Performance Goals**: Application-only release median < 20 minutes (SC-002); PR validation < 10 minutes

**Constraints**: Task definition uses ECR `:latest`; no `.env` in CI; Webhook OAuth registration stays manual; gRPC verify non-blocking v1; bootstrap via `deploy.sh all` remains one-time manual path

**Scale/Scope**: Single production environment; GitHub repo `Joezanini/byods-webhook-server`; ~$1–5/month pipeline cost atop existing ~$30–35/month ECS footprint

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Verify against `.specify/memory/constitution.md`:

- [x] **SDK-First**: No application or Webex protocol changes; pipeline deploys existing SDK-backed service unchanged.
- [x] **Webhook Integrity**: `POST /webhooks/webex` untouched; verify stage only probes reachability.
- [x] **Modular Architecture**: All changes confined to `infra/` (CDK + buildspecs); `src/` modules unaffected.
- [x] **Production Reliability**: Verify stage checks `/health`; deploy waits for `services-stable`; structured JSON in verify output; CloudWatch logs per CodeBuild project.
- [x] **Security by Default**: No secrets in git/logs; pipeline IAM scoped without Secrets Manager read on Webex secret; GitHub via CodeStar connection.
- [x] **Incremental Delivery**: Pipeline stack deployable after app stack; PR validation before release pipeline; bootstrap documented separately.

**Post-Phase 1 re-check**: All gates pass. Delivery ordering for this feature: pipeline IaC → buildspecs → CDK stack → GitHub connection → quickstart validation.

## Project Structure

### Documentation (this feature)

```text
specs/004-aws-cicd-pipeline/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── cicd-pipeline.md
└── tasks.md                    # Phase 2 (/speckit-tasks)
```

### Source Code (repository root — additions/changes)

```text
infra/
├── app.py                          # MODIFY: add ByodsPipelineStack synth
├── stack.py                        # unchanged (ByodsWebhookStack)
├── pipeline_stack.py               # NEW: CodePipeline + CodeBuild + IAM + S3
├── buildspec.yml                   # existing — image build (Build stage)
├── buildspec-infra.yml             # NEW: conditional CDK deploy
├── buildspec-deploy.yml            # NEW: ECS force-new-deployment
├── buildspec-verify.yml            # NEW: HTTP smoke tests
├── buildspec-test.yml              # NEW: PR pytest + docker build
├── cdk.json                        # MODIFY: optional pipeline context keys
├── AWS_DEPLOYMENT.md               # MODIFY: CI/CD section (implementation)
└── scripts/
    ├── deploy.sh                   # unchanged reference; manual fallback
    └── codebuild_push.sh           # unchanged; superseded for routine builds
```

**Structure Decision**: All CI/CD implementation lives under `infra/` alongside existing CDK and deploy scripts. Separate `ByodsPipelineStack` avoids coupling pipeline lifecycle to application stack updates (FR-011 URL stability).

## Complexity Tracking

> No constitution violations requiring justification.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |

## Phase 0: Research Summary

See [research.md](./research.md):

| Topic | Decision |
|-------|----------|
| Source | GitHub via CodeStar Connections |
| Orchestration | CodePipeline V2 — release + PR pipelines |
| Image build | Reuse `infra/buildspec.yml`; privileged CodeBuild |
| Image tags | Commit SHA + `:latest` (matches ECS task def) |
| ECS deploy | `aws ecs update-service --force-new-deployment` + wait stable |
| Infra deploy | Conditional CDK when `infra/**` changed in commit |
| Verification | curl health (blocking), readiness (report), webhook POST (blocking), gRPC (non-blocking); **auto-rollback on blocking failure** (FR-015) |
| Concurrency | Supersede in-flight release runs (FR-016) |
| Manual infra | `FORCE_INFRA=true` on pipeline re-run (FR-008) |
| Secrets | ECS Secrets Manager only; pipeline never reads `.env` |
| Bootstrap | Manual `deploy.sh all` for first-time environment |
| IaC | New `ByodsPipelineStack` in CDK |

## Phase 1: Design Summary

See [data-model.md](./data-model.md), [contracts/cicd-pipeline.md](./contracts/cicd-pipeline.md), [quickstart.md](./quickstart.md).

### Pipeline topology

```text
                    ┌─────────────────────────────────────────┐
  push main ───────►│  byods-webhook-release (CodePipeline)   │
                    │  Source → Infra* → Build → Deploy → Verify │
                    └─────────────────────────────────────────┘
                                         │
                    * Infra skips if no infra/** diff

                    ┌─────────────────────────────────────────┐
  PR opened ───────►│  byods-webhook-pr-validation           │
                    │  Source → Test (pytest + docker build)  │
                    └─────────────────────────────────────────┘
```

### CDK: `ByodsPipelineStack` (new file)

**Constructs to add**:

1. **S3 bucket** — pipeline artifacts, encryption, 30-day lifecycle
2. **CodeStar connection** — or import ARN via `-c githubConnectionArn=...`
3. **CodeBuild projects** (5):
   - `byods-webhook-build` → `infra/buildspec.yml`, privileged
   - `byods-webhook-infra` → `infra/buildspec-infra.yml`
   - `byods-webhook-deploy` → `infra/buildspec-deploy.yml`
   - `byods-webhook-verify` → `infra/buildspec-verify.yml`
   - `byods-webhook-test` → `infra/buildspec-test.yml`
4. **CodePipeline V2** × 2 with triggers and IAM roles
5. **CloudWatch log groups** — `/codebuild/byods-webhook-*`

**IAM highlights**:

- Build role: ECR push + logs (reuse patterns from `codebuild_push.sh` role)
- Deploy role: ECS UpdateService + CloudFormation DescribeStacks
- Infra role: CDK deploy permissions on `ByodsWebhookStack`
- Verify role: read-only stack outputs + outbound HTTPS (no secrets)
- Test role: logs only

### Buildspec additions

| File | Stage | Key behavior |
|------|-------|--------------|
| `buildspec.yml` | Build | Existing — ECR login, docker build/push SHA + latest |
| `buildspec-infra.yml` | Infra | Git diff gate; `cdk deploy ByodsWebhookStack -c desiredCount=1` |
| `buildspec-deploy.yml` | Deploy | Resolve cluster/service from stack outputs; force-new-deployment |
| `buildspec-verify.yml` | Verify | curl checks + JSON summary line |
| `buildspec-test.yml` | PR Test | pytest + docker build (no push) |

### Mapping to `deploy.sh` commands

| Manual | Automated stage |
|--------|-----------------|
| `deploy.sh image` | Build |
| `deploy.sh restart` | Deploy |
| `deploy.sh verify` | Verify |
| `deploy.sh infra 1` | Infra (when `infra/**` changed) |
| `deploy.sh secrets` | **Not automated** — operator manages Secrets Manager |
| `deploy.sh all` | **One-time bootstrap** only |
| `codebuild_push.sh` | Replaced by pipeline Build for routine use |

### Implementation phases (for `/speckit-tasks`)

**Phase A — Buildspecs & scripts**

1. Add `buildspec-infra.yml`, `buildspec-deploy.yml`, `buildspec-verify.yml`, `buildspec-test.yml`
2. Unit-test buildspec pre-check logic locally where possible (shell dry-run)

**Phase B — CDK pipeline stack**

3. Create `infra/pipeline_stack.py` with all resources per contract
4. Update `infra/app.py` to synth `ByodsPipelineStack`
5. Add CDK context keys: `githubOwner`, `githubRepo`, `githubBranch`, `githubConnectionArn`

**Phase C — Operator docs & validation**

6. Update `infra/AWS_DEPLOYMENT.md` CI/CD section with pipeline names, bootstrap order, troubleshooting
7. Run [quickstart.md](./quickstart.md) scenarios after deploy

**Phase D — GitHub integration**

8. Create CodeStar connection; authorize GitHub org/repo
9. Configure branch protection requiring PR pipeline status

### Future enhancements (out of v1 scope)

- ECS task definition with immutable image tag per commit (replace `:latest` + force deploy)
- Enable ECS deployment circuit breaker in `stack.py` for deploy-time auto-rollback (verify rollback implemented in buildspec)
- Staging environment pipeline
- Slack/SNS notifications on pipeline failure
- Fix gRPC ALB health check → enable blocking gRPC verify

## Agent Context

Active plan for coding agents: `specs/004-aws-cicd-pipeline/plan.md`
