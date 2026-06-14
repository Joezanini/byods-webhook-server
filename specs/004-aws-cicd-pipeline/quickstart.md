# Quickstart: AWS CI/CD Pipeline Validation

**Feature**: `004-aws-cicd-pipeline` | **Date**: 2026-06-13

Validate the CI/CD pipeline end-to-end after implementation. See [contracts/cicd-pipeline.md](./contracts/cicd-pipeline.md) for stage definitions and [data-model.md](./data-model.md) for entity semantics.

---

## Prerequisites

1. **Application stack deployed** (one-time manual bootstrap if greenfield):

   ```bash
   AWS_REGION=us-east-1 ./infra/scripts/deploy.sh all
   ```

   Requires repo-root `.env` with Webex credentials for first secrets sync only.

2. **Webex secrets in Secrets Manager** populated (`byods-webhook-server/webex`).

3. **GitHub CodeStar connection** created and status `Available` in AWS Console (Region: `us-east-1`).

4. **Pipeline stack deployed**:

   ```bash
   cd infra
   source .venv/bin/activate  # or create venv + pip install -r requirements.txt
   export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
   export CDK_DEFAULT_REGION=us-east-1
   cdk deploy ByodsPipelineStack -c githubConnectionArn=<connection-arn>
   ```

5. **GitHub branch protection** (recommended): require `byods-webhook-pr-validation` status check before merging to `main`.

---

## Scenario 1: Pull-request validation (no production impact)

**Goal**: Prove FR-012 / SC-007 — build and test without ECS changes.

1. Push a feature branch and open a PR against `main`.
2. Open CodePipeline → `byods-webhook-pr-validation` → confirm execution started.
3. Open CodeBuild logs for `byods-webhook-test`.

**Expected**:

- `pytest` passes (unit + non-live integration tests).
- `docker build` succeeds.
- No ECR push in logs.
- No `ecs update-service` calls.
- Production `/health` unchanged during run.

**Failure triage**: Fix test or Dockerfile errors; re-push to PR branch to re-trigger.

---

## Scenario 2: Application-only release (P1)

**Goal**: Prove FR-001, FR-002, FR-004 — merge to `main` builds, pushes, and rolls out.

1. Merge a trivial non-infra change to `main` (e.g., comment in `README.md`).
2. Watch `byods-webhook-release` pipeline:
   - **Infra**: should log "No infra changes; skipping" and succeed quickly.
   - **Build**: ECR push for commit SHA + `latest`.
   - **Deploy**: `services-stable` wait succeeds.
   - **Verify**: health + webhook checks pass.

3. Confirm image in ECR:

   ```bash
   aws ecr describe-images --repository-name byods-webhook-server --region us-east-1 \
     --query 'sort_by(imageDetails,& imagePushedAt)[-1].imageTags'
   ```

4. Confirm ECS picked up deployment:

   ```bash
   aws ecs describe-services \
     --cluster "$(aws cloudformation describe-stacks --stack-name ByodsWebhookStack \
       --query 'Stacks[0].Outputs[?OutputKey==`EcsClusterName`].OutputValue' --output text)" \
     --services "$(aws cloudformation describe-stacks --stack-name ByodsWebhookStack \
       --query 'Stacks[0].Outputs[?OutputKey==`EcsServiceName`].OutputValue' --output text)" \
     --region us-east-1 \
     --query 'services[0].deployments'
   ```

**Expected**:

- Median wall time < 20 minutes (SC-002).
- `https://hooks.atozbuildingcrm.com/health` returns 200.
- Verify stage JSON summary shows `"overall":"pass"`.

---

## Scenario 3: Failed build blocks deploy (FR-004)

**Goal**: Prove failed image build does not roll out.

1. Temporarily break the Dockerfile on a test branch (e.g., invalid `FROM` instruction).
2. Merge to `main` (or use a test branch wired to release pipeline in dev account).
3. Confirm **Build** stage fails and **Deploy** / **Verify** do not run.
4. Confirm production still serves previous image (health check still 200).

**Cleanup**: Revert Dockerfile fix and re-merge.

---

## Scenario 4: Infrastructure change (P3)

**Goal**: Prove FR-007 — CDK deploy runs when `infra/**` changes.

1. Merge a safe infra-only change (e.g., CloudWatch log retention comment or env var in `stack.py`).
2. Confirm **Infra** stage runs `cdk deploy` (not skipped).
3. Confirm **Build** → **Deploy** → **Verify** still complete.
4. Confirm public URLs unchanged (SC-006):

   ```bash
   curl -fsS https://hooks.atozbuildingcrm.com/health
   curl -fsS https://hooks.atozbuildingcrm.com/ready
   ```

**Failure triage**: If stack enters `UPDATE_ROLLBACK_COMPLETE`:

```bash
aws cloudformation delete-stack --stack-name ByodsWebhookStack --region us-east-1
# Re-run manual bootstrap or fix CDK and re-trigger pipeline
```

---

## Scenario 5: Verification behavior (P2)

**Goal**: Prove FR-005/006 and gRPC non-blocking rule.

After a successful release, inspect Verify stage log for:

| Check | Expected log |
|-------|----------------|
| Health | `pass`, HTTP 200 |
| Readiness | HTTP code logged; 503 logged as warning if token issue |
| Webhook POST | HTTP 400 (or similar) counted as pass |
| gRPC | `skipped` or warning — pipeline still `Succeeded` |

Manual cross-check:

```bash
curl -fsS https://hooks.atozbuildingcrm.com/health
curl -sS -o /dev/null -w '%{http_code}\n' https://hooks.atozbuildingcrm.com/ready
curl -sS -o /dev/null -w '%{http_code}\n' \
  -X POST https://hooks.atozbuildingcrm.com/webhooks/webex \
  -H 'Content-Type: application/json' -d '{}'
```

---

## Scenario 6: Secrets audit (P4)

**Goal**: Prove FR-009/010 / SC-005.

1. Search CodeBuild logs for all projects — no `WEBEX_*` secret values.
2. Confirm pipeline IAM roles lack `secretsmanager:GetSecretValue` on `byods-webhook-server/webex`.
3. Confirm repo has no `.env` committed.

Runtime secrets remain loaded by ECS task from Secrets Manager (unchanged from manual deploy).

---

## Operator checklist (post-implementation)

- [ ] CodeStar connection `Available`
- [ ] `ByodsPipelineStack` deployed
- [ ] PR pipeline green on sample PR
- [ ] Release pipeline green on merge to `main`
- [ ] ECR shows commit SHA tag + `latest`
- [ ] Verify JSON summary in logs
- [ ] Branch protection requires PR pipeline
- [ ] `AWS_DEPLOYMENT.md` updated with pipeline section (implementation task)

---

## Related documents

- [spec.md](../spec.md) — requirements and success criteria
- [plan.md](../plan.md) — implementation plan
- [research.md](../research.md) — design decisions
- [../../infra/AWS_DEPLOYMENT.md](../../infra/AWS_DEPLOYMENT.md) — production deployment reference
