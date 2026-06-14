# Tasks: AWS CI/CD Pipeline for BYODS Webhook Server

**Input**: Design documents from `/specs/004-aws-cicd-pipeline/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Not requested in spec. Validation tasks reference `quickstart.md` scenarios (manual pipeline runs). PR pipeline runs existing `pytest` suite via `buildspec-test.yml`.

**Organization**: Tasks grouped by user story. All implementation under `infra/`; no application (`src/`) changes.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story label (US1–US4)

## Path Conventions

Infrastructure at repository root: `infra/`, specs at `specs/004-aws-cicd-pipeline/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: CDK context and contract alignment with clarify session decisions

- [x] T001 Add pipeline context keys (`githubOwner`, `githubRepo`, `githubBranch`, `githubConnectionArn`) to `infra/cdk.json`
- [x] T002 [P] Update `specs/004-aws-cicd-pipeline/contracts/cicd-pipeline.md` with FR-015 verify rollback, FR-008 `FORCE_INFRA` override, and FR-016 supersede execution mode

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared buildspecs and shell helpers used by multiple pipeline stages—MUST complete before user story pipeline wiring

**⚠️ CRITICAL**: No user story pipeline work until this phase is complete

- [x] T003 Create `infra/scripts/pipeline_common.sh` with `resolve_cluster_service()`, `resolve_stack_output()`, and `resolve_health_urls()` helpers for CodeBuild stages
- [x] T004 [P] Create `infra/buildspec-deploy.yml` with ECS `force-new-deployment`, `services-stable` wait, FR-017 failure exit, and post_build export of `previous_task_definition_arn` to `deploy-meta/env`
- [x] T005 [P] Create `infra/buildspec-infra.yml` with `infra/**` git-diff skip gate, `FORCE_INFRA=true` bypass (FR-008), and CDK deploy of `ByodsWebhookStack` with `desiredCount=1`
- [x] T006 [P] Create `infra/buildspec-test.yml` for PR validation: `pytest` (skip live gRPC integration) plus `docker build` without ECR push per `contracts/cicd-pipeline.md`

**Checkpoint**: Buildspecs and shared scripts ready—pipeline CDK wiring can begin

---

## Phase 3: User Story 1 - Automated Application Release (Priority: P1) 🎯 MVP

**Goal**: Merge to `main` automatically builds image, pushes to ECR, and rolls out to ECS without manual `deploy.sh`

**Independent Test**: Merge trivial app-only change to `main`; `byods-webhook-release` completes Build+Deploy; ECR has commit SHA tag; ECS service stable—quickstart Scenario 2

### Implementation for User Story 1

- [x] T007 [US1] Confirm `infra/buildspec.yml` uses `IMAGE_TAG=$CODEBUILD_RESOLVED_SOURCE_VERSION`, pushes commit SHA and `:latest` tags to ECR
- [x] T008 [US1] Create `infra/pipeline_stack.py` with S3 artifact bucket, GitHub CodeStar connection, `byods-webhook-build` CodeBuild project (privileged), and IAM roles per `contracts/cicd-pipeline.md`
- [x] T009 [US1] Add `byods-webhook-release` CodePipeline V2 with GitHub source (`Joezanini/byods-webhook-server`, branch `main`) and supersede in-flight executions (FR-016) in `infra/pipeline_stack.py`
- [x] T010 [US1] Wire Build stage to `infra/buildspec.yml` with `REPOSITORY_URI`, `ECR_REPO`, and region env vars in `infra/pipeline_stack.py`
- [x] T011 [US1] Wire Deploy stage to `infra/buildspec-deploy.yml` in `infra/pipeline_stack.py` with deploy CodeBuild IAM (ECS UpdateService, CloudFormation DescribeStacks)
- [x] T012 [US1] Update `infra/app.py` to instantiate `ByodsPipelineStack` alongside `ByodsWebhookStack`
- [x] T013 [US1] Add CloudFormation outputs `ReleasePipelineName`, `ArtifactBucketName`, and `EcrBuildProjectName` to `infra/pipeline_stack.py`
- [x] T014 [US1] Deploy `ByodsPipelineStack` via `cdk deploy ByodsPipelineStack` and validate application-only release per `specs/004-aws-cicd-pipeline/quickstart.md` Scenario 2

**Checkpoint**: User Story 1 complete—routine merges deploy without `deploy.sh image` or `deploy.sh restart`

---

## Phase 4: User Story 2 - Post-Deploy Verification (Priority: P2)

**Goal**: Automated HTTP smoke tests after deploy with JSON summary; blocking failures trigger ECS rollback (FR-015)

**Independent Test**: Successful release shows verify pass JSON; simulated health failure rolls back task definition—quickstart Scenarios 5 and 3

### Implementation for User Story 2

- [x] T015 [P] [US2] Create `infra/buildspec-verify.yml` with blocking health and webhook checks, non-blocking readiness/gRPC, and final JSON summary line per `contracts/cicd-pipeline.md`
- [x] T016 [US2] Add rollback block to `infra/buildspec-verify.yml` that reads `previous_task_definition_arn` from deploy artifact and runs `aws ecs update-service --task-definition` on blocking failure (FR-015)
- [x] T017 [US2] Add `byods-webhook-verify` CodeBuild project and Verify stage after Deploy in `infra/pipeline_stack.py`
- [x] T018 [US2] Grant verify CodeBuild role ECS `UpdateService`/`DescribeServices` for rollback only in `infra/pipeline_stack.py`; confirm no Secrets Manager permissions
- [x] T019 [US2] Redeploy `ByodsPipelineStack` and validate verify pass/fail plus rollback per `specs/004-aws-cicd-pipeline/quickstart.md` Scenario 5

**Checkpoint**: User Stories 1 and 2 complete—releases verified with automatic rollback on blocking smoke-test failure

---

## Phase 5: User Story 3 - Controlled Infrastructure Updates (Priority: P3)

**Goal**: Infra stage runs on `infra/**` changes or manual `FORCE_INFRA` re-run; skipped on app-only merges (FR-007, FR-008)

**Independent Test**: Infra-only merge runs CDK deploy stage; app-only merge skips infra; manual re-run with `FORCE_INFRA=true` runs infra—quickstart Scenario 4

### Implementation for User Story 3

- [x] T020 [US3] Add `byods-webhook-infra` CodeBuild project and Infra stage (before Build) in `infra/pipeline_stack.py` using `infra/buildspec-infra.yml`
- [x] T021 [US3] Configure CodePipeline manual re-run variable `FORCE_INFRA` passed to Infra CodeBuild environment in `infra/pipeline_stack.py` (FR-008)
- [x] T022 [US3] Grant infra CodeBuild role CDK/CloudFormation deploy permissions on `ByodsWebhookStack` in `infra/pipeline_stack.py`
- [x] T023 [US3] Document infra skip rules, force-infra manual re-run steps, and `UPDATE_ROLLBACK_COMPLETE` recovery in `infra/AWS_DEPLOYMENT.md`
- [x] T024 [US3] Validate infra-change pipeline run per `specs/004-aws-cicd-pipeline/quickstart.md` Scenario 4

**Checkpoint**: User Stories 1–3 complete—infra and app releases automated with correct gating

---

## Phase 6: User Story 4 - Secure Credential Handling (Priority: P4)

**Goal**: PR validation without production deploy; pipeline IAM excludes Webex secrets; no `.env` in CI (FR-009, FR-010, FR-012, FR-013)

**Independent Test**: PR pipeline runs pytest and docker build only; CodeBuild logs contain no secret values; ECS still loads Secrets Manager at runtime—quickstart Scenarios 1 and 6

### Implementation for User Story 4

- [x] T025 [US4] Add `byods-webhook-test` CodeBuild project wired to `infra/buildspec-test.yml` with logs-only IAM in `infra/pipeline_stack.py`
- [x] T026 [US4] Create `byods-webhook-pr-validation` CodePipeline V2 with PR opened/updated trigger and Test stage in `infra/pipeline_stack.py` (FR-012)
- [x] T027 [US4] Audit all pipeline and CodeBuild IAM policies in `infra/pipeline_stack.py` to exclude `secretsmanager:GetSecretValue` on `byods-webhook-server/webex` (FR-009, FR-010)
- [x] T028 [P] [US4] Document CI/CD secrets policy, no-`.env`-in-CI rule, and manual `register_webhooks.py` boundary in `infra/AWS_DEPLOYMENT.md` (FR-013)
- [x] T029 [US4] Add CloudFormation output `PrPipelineName` to `infra/pipeline_stack.py`
- [x] T030 [US4] Validate PR pipeline and secrets audit per `specs/004-aws-cicd-pipeline/quickstart.md` Scenarios 1 and 6

**Checkpoint**: All user stories complete—full release and PR pipelines with secure credential boundaries

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation sync, GitHub integration, and end-to-end validation

- [x] T031 Run complete operator checklist in `specs/004-aws-cicd-pipeline/quickstart.md` and fix any gaps in `infra/` or docs
- [x] T032 [P] Sync clarify-session decisions (FR-015 rollback, FR-008 force-infra, FR-016 supersede) into `specs/004-aws-cicd-pipeline/plan.md`
- [x] T033 Configure GitHub branch protection on `main` requiring `byods-webhook-pr-validation` status check before merge

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies—start immediately
- **Foundational (Phase 2)**: Depends on Setup—**BLOCKS all user stories**
- **User Story 1 (Phase 3)**: Depends on Foundational—**MVP**; delivers Build+Deploy release pipeline
- **User Story 2 (Phase 4)**: Depends on US1 release pipeline skeleton (Verify stage appended)
- **User Story 3 (Phase 5)**: Depends on US1 (Infra stage prepended); buildspec-infra from Foundational
- **User Story 4 (Phase 6)**: Depends on Foundational; PR pipeline independent of release Verify/Infra but shares `pipeline_stack.py`
- **Polish (Phase 7)**: Depends on US1–US4 completion

### User Story Dependencies

- **US1 (P1)**: After Foundational—no dependency on other stories
- **US2 (P2)**: After US1—Verify stage extends release pipeline
- **US3 (P3)**: After US1—Infra stage extends release pipeline; uses T005 buildspec
- **US4 (P4)**: After Foundational—can parallelize with US2/US3 once US1 creates `pipeline_stack.py` (coordinate edits to same file sequentially)

### Within Each User Story

- Buildspecs before CDK stage wiring
- CDK stack changes before AWS deploy validation tasks
- `pipeline_stack.py` edits should be sequential when multiple stories touch the same file

### Parallel Opportunities

- **Phase 1**: T002 ∥ T001 (after T001 if contract references cdk context keys)
- **Phase 2**: T004, T005, T006 ∥ after T003 (or T004–T006 ∥ if no shared script dependency—T003 first recommended)
- **Phase 4**: T015 ∥ before T016–T18 (verify buildspec before rollback integration)
- **Phase 6**: T028 ∥ other doc tasks after T027
- **Phase 7**: T032 ∥ T031

---

## Parallel Example: Foundational Phase

```bash
# After T003 completes, launch buildspec creation in parallel:
Task T004: "Create infra/buildspec-deploy.yml ..."
Task T005: "Create infra/buildspec-infra.yml ..."
Task T006: "Create infra/buildspec-test.yml ..."
```

---

## Parallel Example: User Story 4

```bash
# After IAM audit (T027), documentation can run in parallel with pipeline deploy validation:
Task T028: "Document CI/CD secrets policy in infra/AWS_DEPLOYMENT.md ..."
Task T030: "Validate PR pipeline per quickstart Scenarios 1 and 6 ..."
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL)
3. Complete Phase 3: User Story 1 (T007–T014)
4. **STOP and VALIDATE**: quickstart Scenario 2—merge to `main` deploys without manual scripts
5. Demo/release to production before adding verify, infra, PR pipelines

### Incremental Delivery

1. Setup + Foundational → buildspecs ready
2. US1 → automated build + deploy (MVP)
3. US2 → verify + rollback on smoke failure
4. US3 → conditional infra + force-infra
5. US4 → PR validation + secrets IAM audit
6. Polish → branch protection + full quickstart

### Suggested MVP Scope

**User Story 1 only** (T001–T014): delivers FR-001, FR-002, FR-004, FR-016 and core SC-001/SC-003/SC-006 value.

---

## Notes

- One-time environment bootstrap remains manual: `AWS_REGION=us-east-1 ./infra/scripts/deploy.sh all`
- `infra/scripts/deploy.sh` stays as operator fallback; pipeline orchestrates equivalent steps
- `infra/scripts/codebuild_push.sh` superseded for routine builds once pipeline live
- Coordinate `infra/pipeline_stack.py` edits across US1–US4 to avoid merge conflicts
- FR-015 rollback requires deploy stage to capture previous task definition before rollout (T004, T016)

---

## Task Summary

| Phase | Tasks | Story |
|-------|-------|-------|
| Setup | T001–T002 (2) | — |
| Foundational | T003–T006 (4) | — |
| US1 Automated Release | T007–T014 (8) | P1 MVP |
| US2 Verification | T015–T019 (5) | P2 |
| US3 Infrastructure | T020–T024 (5) | P3 |
| US4 Secure Credentials | T025–T030 (6) | P4 |
| Polish | T031–T033 (3) | — |
| **Total** | **33 tasks** | |
