param(
    [Parameter(Mandatory=$true)]
    [string]$Environment,
    [string]$ProjectName = "twin"
)

# Validate environment parameter
if ($Environment -notmatch '^(dev|test|prod)$') {
    Write-Host "Error: Invalid environment '$Environment'" -ForegroundColor Red
    Write-Host "Available environments: dev, test, prod" -ForegroundColor Yellow
    exit 1
}

Write-Host "Preparing to destroy $ProjectName-$Environment infrastructure..." -ForegroundColor Yellow

# Navigate to terraform directory
Set-Location (Join-Path (Split-Path $PSScriptRoot -Parent) "terraform")

# Get AWS Account ID for backend configuration
$awsAccountId = "$(aws sts get-caller-identity --query Account --output text)".Trim()
$awsRegion = if ($env:DEFAULT_AWS_REGION) { $env:DEFAULT_AWS_REGION } else { "eu-north-1" }

# Initialize terraform with S3 backend
Write-Host "Initializing Terraform with S3 backend..." -ForegroundColor Yellow
terraform init -input=false `
  "-backend-config=bucket=$ProjectName-terraform-state-$awsAccountId" `
  "-backend-config=key=$ProjectName/terraform.tfstate" `
  "-backend-config=region=$awsRegion" `
  "-backend-config=dynamodb_table=$ProjectName-terraform-locks" `
  "-backend-config=encrypt=true"
if ($LASTEXITCODE -ne 0) { Write-Host "terraform init failed" -ForegroundColor Red; exit 1 }

# Check if workspace exists
$workspaces = terraform workspace list
if (-not ($workspaces | Select-String $Environment)) {
    Write-Host "Error: Workspace '$Environment' does not exist" -ForegroundColor Red
    Write-Host "Available workspaces:" -ForegroundColor Yellow
    terraform workspace list
    exit 1
}

# Select the workspace
terraform workspace select $Environment

Write-Host "Emptying S3 buckets..." -ForegroundColor Yellow

# Define bucket names with account ID
$FrontendBucket = "$ProjectName-$Environment-frontend-$awsAccountId"
$MemoryBucket = "$ProjectName-$Environment-memory-$awsAccountId"

# Empty each bucket if it exists (aws sets a non-zero exit code; try/catch won't see it)
foreach ($bucket in @($FrontendBucket, $MemoryBucket)) {
    aws s3 ls "s3://$bucket" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Emptying $bucket..." -ForegroundColor Gray
        aws s3 rm "s3://$bucket" --recursive
    } else {
        Write-Host "  $bucket not found or already empty" -ForegroundColor Gray
    }
}

Write-Host "Running terraform destroy..." -ForegroundColor Yellow

# Terraform reads the Lambda zip even when destroying, so make a placeholder if it is missing
if (-not (Test-Path "..\backend\lambda-deployment.zip")) {
    Write-Host "Creating placeholder lambda package for destroy operation..." -ForegroundColor Gray
    python -c "import zipfile; zipfile.ZipFile('../backend/lambda-deployment.zip', 'w').writestr('placeholder.txt', 'destroy')"
}

# Run terraform destroy with auto-approve
if ($Environment -eq "prod" -and (Test-Path "prod.tfvars")) {
    terraform destroy -var-file="prod.tfvars" -var="project_name=$ProjectName" -var="environment=$Environment" -auto-approve
} else {
    terraform destroy -var="project_name=$ProjectName" -var="environment=$Environment" -auto-approve
}

if ($LASTEXITCODE -ne 0) { Write-Host "terraform destroy failed" -ForegroundColor Red; exit 1 }

Write-Host "Infrastructure for $Environment has been destroyed!" -ForegroundColor Green
Write-Host ""
Write-Host "  To remove the workspace completely, run:" -ForegroundColor Cyan
Write-Host "   terraform workspace select default" -ForegroundColor White
Write-Host "   terraform workspace delete $Environment" -ForegroundColor White
