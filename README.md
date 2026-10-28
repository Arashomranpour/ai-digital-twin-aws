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

Tear it down with `./scripts/destroy.sh dev` (or `destroy.ps1`).

## Security notes

- No API keys in the repo or in the deployed backend. Visitors bring their own Groq key.
- The Lambda role can only read and write its own memory bucket.
- Provider errors are logged server-side and never returned to the browser.
- Session IDs are validated, and message length is capped.
