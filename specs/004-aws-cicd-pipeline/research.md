# Research: AWS CI/CD Pipeline for BYODS Webhook Server

**Feature**: `004-aws-cicd-pipeline` | **Date**: 2026-06-13

## 1. Source repository integration

**Decision**: GitHub (`Joezanini/byods-webhook-server`) via **AWS CodeStar Connections** as the CodePipeline source provider.

**Rationale**: Remote is GitHub; CodePipeline native GitHub source requires a CodeStar connection (OAuth app) in the target account. CodeCommit would require mirroring and adds no value here.

**Alternatives considered**:

| Alternative | Rejected because |
|-------------|------------------|
| CodeCommit mirror | Extra repo to maintain; team already uses GitHub |
| S3 zip source (like `codebuild_push.sh`) | No PR webhooks; loses commit metadata and path filters |
| GitHub Actions calling AWS | Valid but spec requires AWS-native CI/CD; would duplicate orchestration outside CodePipeline |

**Operator prerequisite**: One-time Console step to create and authorize the CodeStar connection (`byods-webhook-github`).

---

## 2. Pipeline orchestration

**Decision**: **AWS CodePipeline V2** with two pipelines:

| Pipeline | Trigger | Purpose |
|----------|---------|---------|
| `byods-webhook-release` | Push to `main` | Build → optional infra → deploy → verify |
| `byods-webhook-pr-validation` | Pull request opened/updated (all branches) | Test + Docker build only; no ECS changes |

**Rationale**: Separating release and PR pipelines satisfies FR-012 (pre-merge validation without production deploy) and FR-001/002 (automated release on merge). V2 triggers support branch and event filters without polling.

**Alternatives considered**:

| Alternative | Rejected because |
|-------------|------------------|
| Single pipeline with manual approval before deploy | Adds friction on every merge; spec targets 95% hands-off releases |
| CodeBuild webhooks only (no CodePipeline) | Harder to visualize stages, artifacts, and verification audit trail |
| CodeDeploy blue/green | Task definition pins `:latest`; blue/green needs imagedefinitions + new task def revision—valid v2 improvement, not required for v1 |

**Concurrency**: Release pipeline uses **superseded** execution mode (default)—new push to `main` stops in-flight execution. Prevents overlapping ECS rollouts.

---

## 3. Container image build

**Decision**: Reuse existing [`infra/buildspec.yml`](../../infra/buildspec.yml) in a CodeBuild project with **privileged mode** and `aws/codebuild/amazonlinux-x86_64-standard:5.0`.

**Rationale**: buildspec already performs ECR login, `docker build`, tag `:latest`, and push. `codebuild_push.sh` proves the same buildspec works remotely. Privileged mode is required for Docker-in-Docker on CodeBuild.

**Image tagging**:

- `IMAGE_TAG=$CODEBUILD_RESOLVED_SOURCE_VERSION` (commit SHA) — immutable audit tag
- Also push `:latest` — matches current ECS task definition (`from_ecr_repository(repository, tag="latest")`) and `deploy.sh restart` behavior

**Alternatives considered**:

| Alternative | Rejected because |
|-------------|------------------|
| Keep `codebuild_push.sh` zip-to-S3 flow inside pipeline | Redundant when CodePipeline supplies source; adds S3 staging bucket per build |
| Amazon ECR pull-through / Copilot | Over-scoped; existing Dockerfile and ECR repo are sufficient |

---

## 4. ECS rollout (application deploy)

**Decision**: CodeBuild **Deploy** stage running the equivalent of [`deploy.sh restart`](../../infra/scripts/deploy.sh):

1. Resolve `EcsClusterName` / `EcsServiceName` from CloudFormation outputs (`ByodsWebhookStack`)
2. `aws ecs update-service --force-new-deployment`
3. `aws ecs wait services-stable` (timeout aligned with `health_check_grace_period=180s`)

**Rationale**: Task definition image reference is `:latest`; pushing a new image does not change the task definition revision. Force-new-deployment is what operators run today and matches FR-002 without CDK task-def churn on every app commit.

**Alternatives considered**:

| Alternative | Rejected because |
|-------------|------------------|
| CodePipeline native ECS deploy action + `imagedefinitions.json` | Requires CDK change to use SHA tag in task definition each deploy |
| ECS circuit breaker rollback | Currently `enable=False` in stack; enabling is a follow-up hardening task |

**Failure behavior**: If deploy stage fails, previous tasks keep running last pulled `:latest` layers until rollout succeeds—aligns with FR-004.

---

## 5. Infrastructure deploy stage

**Decision**: Conditional **Infra** CodeBuild stage at the start of the release pipeline when `infra/**` changed in the triggering commit (detected via `git diff-tree --no-commit-id --name-only -r $CODEBUILD_RESOLVED_SOURCE_VERSION`).

- If no infra changes: stage exits 0 immediately (~seconds)
- If infra changes: run CDK deploy equivalent to `deploy.sh infra 1` (`cdk deploy ByodsWebhookStack -c desiredCount=1 --require-approval never`)
- **First-time environment bootstrap** remains manual via `deploy.sh all` (two-phase `desiredCount=0` → image → `desiredCount=1`) — pipeline assumes stack and ECR already exist

**Rationale**: FR-007/008 require infra deploy on IaC changes but skip for app-only commits. Git diff in CodeBuild is simpler than CodePipeline stage-level conditions (limited) and avoids false infra runs.

**Alternatives considered**:

| Alternative | Rejected because |
|-------------|------------------|
| Always run CDK deploy | Slow (~5–10 min) on every merge; unnecessary CloudFormation drift checks |
| Separate manual infra pipeline | Violates FR-007 automation goal for infra changes |

**Recovery**: Document `UPDATE_ROLLBACK_COMPLETE` stack deletion in quickstart (from deployment guide).

---

## 6. Post-deploy verification

**Decision**: CodeBuild **Verify** stage after deploy, mirroring [`deploy.sh verify`](../../infra/scripts/deploy.sh) HTTP checks:

| Check | URL / action | Gate |
|-------|----------------|------|
| Health | `https://hooks.atozbuildingcrm.com/health` | **Blocking** — must return 200 |
| Readiness | `https://hooks.atozbuildingcrm.com/ready` | **Report only** — 503 acceptable if refresh token missing pre-bootstrap |
| Webhook route | POST `/webhooks/webex` with `{}` | **Blocking** — must get HTTP response (400 OK) |
| gRPC ListVirtualAgents | `media.atozbuildingcrm.com:443` | **Non-blocking** — log skip/warn due to ALB health-check token issue |

**Rationale**: Matches FR-005/006 and deployment guide known limitation. Operators still get a single CodeBuild log with pass/fail summary.

---

## 7. Pull-request validation

**Decision**: Separate pipeline triggered on PR events; CodeBuild runs:

1. `pip install -r requirements.txt` (+ dev deps if present)
2. `pytest` (unit + integration tests that don't need live Webex)
3. `docker build` (no push) to validate Dockerfile

**Rationale**: FR-012 and SC-007. No ECR push, no ECS API calls—IAM policy scoped accordingly.

---

## 8. Secrets and credentials

**Decision**:

- **Runtime Webex secrets**: Remain in Secrets Manager (`byods-webhook-server/webex`); ECS task execution role already grants read. Pipeline does **not** run `deploy.sh secrets` or read repo `.env`.
- **CI credentials**: IAM roles for CodePipeline/CodeBuild only (ECR push, ECS update, CloudFormation for infra stage, CloudWatch Logs).
- **GitHub**: CodeStar connection ARN stored in CDK; no PAT in repo.

**Rationale**: FR-009/010 and constitution V (secrets never in git). Secret rotation is operator-managed in Secrets Manager + optional manual restart—not automated in v1.

**Alternatives considered**:

| Alternative | Rejected because |
|-------------|------------------|
| SSM Parameter Store for Webex in pipeline | Duplicates Secrets Manager; ECS already wired |
| Pipeline sync from GitHub Secrets | Would require storing Webex creds in GitHub; violates single secret store in AWS |

---

## 9. IaC placement for pipeline resources

**Decision**: New CDK stack **`ByodsPipelineStack`** in `infra/pipeline_stack.py`, deployed after `ByodsWebhookStack` exists. Entry in `infra/app.py` or separate synth target.

**Resources**:

- S3 artifact bucket (pipeline artifacts, encryption, lifecycle)
- CodeStar connection (or import existing ARN via context)
- 4 CodeBuild projects + 2 CodePipelines
- IAM roles (least privilege per project)
- CloudWatch log groups (`/codebuild/byods-webhook-*`)

**Rationale**: Keeps application stack (`ByodsWebhookStack`) unchanged for webhook/media stability (FR-011). Pipeline stack can be redeployed independently.

---

## 10. Cost and performance

**Decision**: Accept ~$1–5/month pipeline overhead (CodePipeline $1/active pipeline × 2, CodeBuild per-minute on small compute) atop existing ~$30–35/month ECS/ALB footprint.

**Performance target**: Application-only release (build + deploy + verify) target **< 20 minutes** median (SC-002)—achievable with `BUILD_GENERAL1_SMALL`, ~3–5 min build, ~3 min ECS stable wait, ~1 min verify.

---

## Resolved clarifications

All Technical Context items resolved; no `NEEDS CLARIFICATION` remains for implementation.
