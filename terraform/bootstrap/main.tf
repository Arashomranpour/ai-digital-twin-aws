# One-time setup for CI/CD. Applied by hand with its own local state, separate from the app stack:
#   1. S3 bucket + DynamoDB table that hold the app's remote Terraform state and locks
#   2. GitHub OIDC provider + IAM role that GitHub Actions assumes (no long-lived AWS keys)
#
#   cd terraform/bootstrap && terraform init && terraform apply

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  description = "Region for the state bucket and lock table (same as the app)"
  type        = string
  default     = "eu-north-1"
}

variable "github_repository" {
  description = "GitHub repository in the form owner/repo (no URL)"
  type        = string
}

variable "project_name" {
  description = "Prefix used by the app's resources (the deploy role is limited to this prefix)"
  type        = string
  default     = "twin"
}

data "aws_caller_identity" "current" {}

locals {
  account_id   = data.aws_caller_identity.current.account_id
  state_bucket = "${var.project_name}-terraform-state-${local.account_id}"
  lock_table   = "${var.project_name}-terraform-locks"
  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }
}

# ---------- Remote state ----------

resource "aws_s3_bucket" "terraform_state" {
  bucket = local.state_bucket
  tags   = merge(local.tags, { Name = "Terraform State Store" })
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "terraform_locks" {
  name         = local.lock_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = merge(local.tags, { Name = "Terraform State Locks" })
}

# ---------- GitHub Actions -> AWS via OIDC ----------

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # AWS validates GitHub's certificate chain itself, so no thumbprint is needed
}

resource "aws_iam_role" "github_actions" {
  name = "github-actions-${var.project_name}-deploy"
  tags = merge(local.tags, { Repository = var.github_repository })

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          # Only this repo, and only the main branch or a named deployment environment.
          # Pull requests (including from forks) cannot assume the role.
          StringLike = {
            "token.actions.githubusercontent.com:sub" = [
              "repo:${var.github_repository}:ref:refs/heads/main",
              "repo:${var.github_repository}:environment:*",
            ]
          }
        }
      }
    ]
  })
}

# Least privilege: only what Terraform needs to manage this app, only on twin-* resources
resource "aws_iam_role_policy" "github_deploy" {
  name = "deploy-${var.project_name}"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AppBuckets"
        Effect = "Allow"
        Action = "s3:*"
        Resource = [
          "arn:aws:s3:::${var.project_name}-*-frontend-${local.account_id}",
          "arn:aws:s3:::${var.project_name}-*-frontend-${local.account_id}/*",
          "arn:aws:s3:::${var.project_name}-*-memory-${local.account_id}",
          "arn:aws:s3:::${var.project_name}-*-memory-${local.account_id}/*",
        ]
      },
      {
        Sid      = "StateBucketList"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketVersioning", "s3:GetBucketLocation"]
        Resource = aws_s3_bucket.terraform_state.arn
      },
      {
        Sid      = "StateObjects"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.terraform_state.arn}/*"
      },
      {
        Sid      = "StateLocks"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:DescribeTable"]
        Resource = aws_dynamodb_table.terraform_locks.arn
      },
      {
        Sid      = "Lambda"
        Effect   = "Allow"
        Action   = "lambda:*"
        Resource = "arn:aws:lambda:*:${local.account_id}:function:${var.project_name}-*"
      },
      {
        Sid      = "ApiGateway"
        Effect   = "Allow"
        Action   = ["apigateway:GET", "apigateway:POST", "apigateway:PUT", "apigateway:PATCH", "apigateway:DELETE"]
        Resource = "arn:aws:apigateway:*::/*"
      },
      {
        Sid      = "CloudFront"
        Effect   = "Allow"
        Action   = "cloudfront:*"
        Resource = "*"
      },
      {
        Sid    = "AppRoles"
        Effect = "Allow"
        Action = [
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:GetRole",
          "iam:UpdateAssumeRolePolicy",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfilesForRole",
          "iam:PutRolePolicy",
          "iam:GetRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:DetachRolePolicy",
        ]
        Resource = "arn:aws:iam::${local.account_id}:role/${var.project_name}-*"
      },
      {
        # The only managed policy the app's roles may have, so this role cannot hand out admin rights
        Sid      = "AttachOnlyLambdaLogging"
        Effect   = "Allow"
        Action   = "iam:AttachRolePolicy"
        Resource = "arn:aws:iam::${local.account_id}:role/${var.project_name}-*"
        Condition = {
          ArnEquals = {
            "iam:PolicyARN" = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
          }
        }
      },
      {
        Sid      = "PassRoleToLambda"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = "arn:aws:iam::${local.account_id}:role/${var.project_name}-*"
        Condition = {
          StringEquals = { "iam:PassedToService" = "lambda.amazonaws.com" }
        }
      },
    ]
  })
}

output "state_bucket_name" {
  value = aws_s3_bucket.terraform_state.id
}

output "lock_table_name" {
  value = aws_dynamodb_table.terraform_locks.name
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions.arn
}

output "account_id" {
  value = local.account_id
}
