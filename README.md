# AI Digital Twin on AWS

A chat app where visitors talk to an AI "digital twin", deployed to AWS with Terraform.

**Live demo: https://dyodbgbt4zf5g.cloudfront.net**

> The demo is **bring-your-own-key**. Get a free API key at
> [console.groq.com/keys](https://console.groq.com/keys), paste it into the page and start chatting.
> The key stays in your browser tab's memory only. It is sent to the API with each request, used once, and never stored or logged.

## Architecture

```
Browser ──> CloudFront ──> S3 (static Next.js site)
   │
   └──────> API Gateway (HTTP API) ──> Lambda (FastAPI + Mangum) ──> Groq API
                                            │
                                            └──> S3 (conversation memory)
```

| Part | Tech |
|------|------|
| Frontend | Next.js (static export), React, Tailwind CSS |
| Backend | FastAPI on AWS Lambda via Mangum, Python 3.12 |
| LLM | Groq (`openai/gpt-oss-120b`), visitor-supplied key |
| Memory | JSON per session in a private S3 bucket |
| Infrastructure | Terraform: S3, CloudFront, API Gateway, Lambda, IAM (least privilege), optional Route 53 + ACM custom domain |
| Environments | Terraform workspaces: `dev`, `test`, `prod` |

## Project layout

```
backend/    FastAPI app, Lambda handler, deploy.py (builds the Lambda zip in Docker)
frontend/   Next.js app (static export to out/)
terraform/  All AWS infrastructure
scripts/    deploy.sh / deploy.ps1 / destroy.sh / destroy.ps1
```

## Run locally

```bash
# backend (needs uv)
cd backend
uv sync
uv run python server.py          # http://localhost:8000

# frontend
cd frontend
npm install
npm run dev                      # http://localhost:3000
```

The frontend calls `http://localhost:8000` unless `NEXT_PUBLIC_API_URL` is set.
The app asks for a Groq API key in the page, so no key is needed in any `.env` file.

## Deploy

Requirements: Terraform, AWS CLI (`aws configure`), Docker (used to build the Lambda package for Linux), Node.js, uv.

```bash
./scripts/deploy.sh dev          # macOS / Linux / Git Bash
.\scripts\deploy.ps1 -Environment dev    # Windows PowerShell
```

The script builds the Lambda zip, runs `terraform apply` in the matching workspace, builds the frontend with the new API URL and syncs it to S3.

Tear it down with `./scripts/destroy.sh dev` (or `destroy.ps1`), or run the **Destroy Environment** workflow.

## CI/CD (GitHub Actions)

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `ci.yml` | pull requests, and reused by deploy | backend unit tests, frontend lint + build (type-checked), `terraform fmt`/`validate`, secrets scan |
| `deploy.yml` | push to `main`, or manual run (dev / test / prod) | runs CI, then builds the Lambda zip, `terraform apply`, uploads the site, clears the CloudFront cache and smoke-tests the live URLs |
| `destroy.yml` | manual only | tears an environment down after you type its name to confirm |

GitHub authenticates to AWS with **OIDC**: no AWS keys are stored anywhere. The deploy role can only be assumed from this repository's `main` branch or a named environment (not from pull requests), and its permissions are limited to the app's `twin-*` resources.
Terraform state lives in an S3 bucket with a DynamoDB lock table, so local runs and CI share one state.

### One-time setup

```bash
# 1. Create the state bucket, lock table, GitHub OIDC provider and deploy role
cd terraform/bootstrap
terraform init
terraform apply -var="github_repository=<owner>/<repo>"

# 2. Move any existing local state to S3 (only if you deployed locally before)
cd ..
terraform init -migrate-state -force-copy   -backend-config="bucket=twin-terraform-state-<account-id>"   -backend-config="key=twin/terraform.tfstate"   -backend-config="region=<region>"   -backend-config="dynamodb_table=twin-terraform-locks"   -backend-config="encrypt=true"

# 3. Add the repository secrets (Settings > Secrets and variables > Actions)
gh secret set AWS_ROLE_ARN          # output github_actions_role_arn from step 1
gh secret set DEFAULT_AWS_REGION    # e.g. eu-north-1
gh secret set AWS_ACCOUNT_ID
```

After that, every push to `main` deploys to `dev`.

## Security notes

- No API keys in the repo or in the deployed backend. Visitors bring their own Groq key.
- The Lambda role can only read and write its own memory bucket.
- Provider errors are logged server-side and never returned to the browser.
- Session IDs are validated, and message length is capped.
- Guardrails in three layers: an input filter (`backend/guardrails.py`) blocks prompt-injection and dangerous requests before any model call, a hardened system prompt backs it up, and an output check stops the model from leaking its instructions. Run the tests with `cd backend && python -m unittest discover -s tests`.
