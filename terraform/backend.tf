terraform {
  backend "s3" {
    # Bucket, key, region and lock table are passed by the deploy/destroy scripts and the
    # GitHub Actions workflows with -backend-config (see scripts/deploy.sh).
  }
}
