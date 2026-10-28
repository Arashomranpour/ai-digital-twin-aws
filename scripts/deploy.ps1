param(
    [ValidateSet("dev", "test", "prod")]
    [string]$Environment = "dev",
    [string]$ProjectName = "twin"
)

$ErrorActionPreference = "Stop"

function Invoke-Step {
    # Native commands don't throw on failure in PowerShell; check the exit code.
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Command failed (exit $LASTEXITCODE): $Command" }
}

$Root = Split-Path -Parent $PSScriptRoot
Write-Host "Deploying $ProjectName to $Environment..."

# 1. Build Lambda package (needs Docker running)
Write-Host "Building Lambda package..."
Push-Location "$Root\backend"
try { Invoke-Step { uv run deploy.py } } finally { Pop-Location }

# 2. Terraform workspace & apply
Push-Location "$Root\terraform"
try {
    Invoke-Step { terraform init -input=false }
    Invoke-Step { terraform workspace select -or-create $Environment }

    $tfArgs = @("apply", "-var=project_name=$ProjectName", "-var=environment=$Environment", "-auto-approve")
    if ($Environment -eq "prod") { $tfArgs += "-var-file=prod.tfvars" }

    Write-Host "Applying Terraform..."
    Invoke-Step { terraform @tfArgs }

    # "$(...)" always gives a string; a bare command with no output (e.g. an empty
    # custom_domain_url) is $null, and even a [string] cast of it stays $null
    $ApiUrl         = "$(terraform output -raw api_gateway_url)".Trim()
    $FrontendBucket = "$(terraform output -raw s3_frontend_bucket)".Trim()
    $CloudFrontUrl  = "$(terraform output -raw cloudfront_url)".Trim()
    $CustomUrl      = "$(terraform output -raw custom_domain_url)".Trim()
}
finally { Pop-Location }

# 3. Build + deploy frontend
Push-Location "$Root\frontend"
try {
    Write-Host "Setting API URL for production..."
    Set-Content -Path ".env.production" -Value "NEXT_PUBLIC_API_URL=$ApiUrl" -Encoding ascii

    Invoke-Step { npm install }
    Invoke-Step { npm run build }
    Invoke-Step { aws s3 sync ./out "s3://$FrontendBucket/" --delete }
}
finally { Pop-Location }

# 4. Final messages
Write-Host ""
Write-Host "Deployment complete!"
Write-Host "CloudFront URL : $CloudFrontUrl"
if ($CustomUrl) { Write-Host "Custom domain  : $CustomUrl" }
Write-Host "API Gateway    : $ApiUrl"
