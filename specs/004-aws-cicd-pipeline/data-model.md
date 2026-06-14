# Data Model: AWS CI/CD Pipeline

**Feature**: `004-aws-cicd-pipeline` | **Date**: 2026-06-13

This feature adds **delivery infrastructure metadata**, not application domain data. Entities describe pipeline runs, artifacts, and verification outcomes stored in AWS (CodePipeline, CodeBuild, CloudWatch, ECR)—not a new application database.

---

## Entity: PipelineRun

Represents one execution of `byods-webhook-release` or `byods-webhook-pr-validation`.

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `id` | string | CodePipeline execution ID | Unique per pipeline |
| `pipeline_name` | enum | `byods-webhook-release` \| `byods-webhook-pr-validation` | Required |
| `trigger_type` | enum | `push` \| `pull_request` | Required |
| `source_branch` | string | Git ref (e.g. `main`, `004-aws-cicd-pipeline`) | Required |
| `commit_sha` | string | Full Git commit hash | 40-char hex |
| `status` | enum | `InProgress` \| `Succeeded` \| `Failed` \| `Superseded` | Required |
| `started_at` | datetime | Execution start | ISO 8601 |
| `finished_at` | datetime | Execution end | Null while in progress |
| `stage_results` | list\<StageResult\> | Ordered stage outcomes | At least one for release pipeline |

**State transitions**:

```text
[Triggered] → InProgress → Succeeded
                        → Failed
                        → Superseded (newer execution on same pipeline)
```

**Relationships**:

- One `PipelineRun` → zero or one `ReleaseArtifact` (release pipeline only)
- One `PipelineRun` → zero or one `DeployTarget` update (release pipeline only)
- One `PipelineRun` → one `VerificationResult` (release pipeline, after deploy)

---

## Entity: StageResult

Child record of a pipeline stage (Infra, Build, Deploy, Verify, or Test).

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `stage_name` | string | e.g. `Build`, `Deploy`, `Verify`, `Test` | Required |
| `action_name` | string | CodeBuild project name | Required |
| `status` | enum | `Succeeded` \| `Failed` \| `Skipped` | Required |
| `log_group` | string | CloudWatch log group | `/codebuild/...` |
| `log_stream` | string | CloudWatch log stream | Optional until complete |
| `duration_seconds` | integer | Wall time | ≥ 0 |

**Rules**:

- Release pipeline: `Build` failure MUST prevent `Deploy` and `Verify` from running (CodePipeline default).
- `Infra` stage with no file changes reports `Skipped` (exit 0 in buildspec pre-check).

---

## Entity: ReleaseArtifact

Container image produced by a successful Build stage.

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `repository_name` | string | ECR repo | `byods-webhook-server` |
| `repository_uri` | string | Full ECR URI | `{account}.dkr.ecr.{region}.amazonaws.com/byods-webhook-server` |
| `commit_tag` | string | Immutable tag | Git commit SHA |
| `latest_tag` | string | Rolling tag | Always `latest` |
| `digest` | string | Image manifest digest | Optional; from ECR describe |
| `pushed_at` | datetime | Push timestamp | After build success |
| `source_commit` | string | Same as PipelineRun.commit_sha | Must match |

**Relationships**:

- Many `ReleaseArtifact` → one ECR repository (lifecycle: keep last 5 per stack rule)
- One `ReleaseArtifact` ← one successful `PipelineRun` Build stage

---

## Entity: DeployTarget

Production ECS service receiving rollouts.

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `stack_name` | string | CloudFormation stack | `ByodsWebhookStack` |
| `cluster_name` | string | ECS cluster | From stack output `EcsClusterName` |
| `service_name` | string | ECS service | From stack output `EcsServiceName` |
| `desired_count` | integer | Running tasks | ≥ 0; production = 1 |
| `task_definition_family` | string | ECS task family | From service describe |
| `image_reference` | string | Container image ref | `{repo}:latest` today |
| `rollout_status` | enum | `Stable` \| `InProgress` \| `Failed` | From `aws ecs wait services-stable` |

**State transitions** (deploy stage):

```text
Stable → InProgress (force-new-deployment) → Stable | Failed
```

**Relationships**:

- One `DeployTarget` ← many `PipelineRun` deploy stages over time
- `DeployTarget` owned by `ByodsWebhookStack`; pipeline stack only holds IAM permission to update

---

## Entity: VerificationResult

Post-deploy smoke check outcome attached to a release `PipelineRun`.

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `pipeline_run_id` | string | Parent execution | FK to PipelineRun.id |
| `health_check` | CheckResult | GET `/health` | Required |
| `readiness_check` | CheckResult | GET `/ready` | Required (report-only gate) |
| `webhook_check` | CheckResult | POST `/webhooks/webex` | Required |
| `grpc_check` | CheckResult | Optional grpcurl probe | Non-blocking |
| `overall_status` | enum | `Passed` \| `Failed` | Failed if any blocking check fails |

### Embedded: CheckResult

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Endpoint tested |
| `http_status` | integer | Response code (0 if connection error) |
| `passed` | boolean | Meets gate criteria |
| `blocking` | boolean | Fails overall if false |
| `message` | string | Human-readable detail |

**Gate rules**:

| Check | `blocking` | Pass condition |
|-------|------------|----------------|
| health | true | HTTP 200 |
| readiness | false | Any HTTP response; log 503 as warning |
| webhook | true | HTTP 4xx/5xx with body (not connection error) |
| grpc | false | Log result; never fail pipeline in v1 |

---

## Entity: SecretReference

Named credentials **not** stored in git; referenced at runtime only.

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `secret_name` | string | Secrets Manager name | `byods-webhook-server/webex` |
| `secret_arn` | string | Full ARN | From stack output |
| `keys` | list\<string\> | JSON keys | 5 Webex keys per deployment guide |
| `managed_by` | enum | `operator` \| `pipeline` | v1: `operator` only |
| `consumed_by` | string | ECS task execution role | At task startup |

**Rules**:

- Pipeline IAM roles MUST NOT include `secretsmanager:GetSecretValue` on Webex secret (build/verify don't need Webex creds).
- `managed_by=pipeline` reserved for future automated rotation workflows—not v1 scope.

---

## Entity: SourceConnection

GitHub linkage for CodePipeline.

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `connection_arn` | string | CodeStar connection ARN | `arn:aws:codestar-connections:...` |
| `provider` | string | `GitHub` | Fixed |
| `repository` | string | `Joezanini/byods-webhook-server` | Must match remote |
| `status` | enum | `PENDING` \| `AVAILABLE` | Must be `AVAILABLE` before pipeline runs |

---

## Cross-entity rules (from FR-*)

| Rule ID | Rule |
|---------|------|
| R-001 | Failed Build → no Deploy (FR-004) |
| R-002 | Deploy uses `:latest` after push (FR-002, matches deploy.sh) |
| R-003 | Infra stage skipped when no `infra/**` diff (FR-008) |
| R-004 | PR pipeline produces no ReleaseArtifact push (FR-012) |
| R-005 | Verification HTTP health blocking (FR-005) |
| R-006 | Public hostnames unchanged by pipeline (FR-011) — deploy target URLs read from stack outputs / env, not hardcoded in buildspec except defaults for verify |
