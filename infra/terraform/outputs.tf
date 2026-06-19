output "lambda_function_name" {
  description = "Lambda function name."
  value       = aws_lambda_function.analyzer.function_name
}

output "lambda_function_arn" {
  description = "Lambda function ARN."
  value       = aws_lambda_function.analyzer.arn
}

output "s3_bucket_name" {
  description = "S3 bucket name."
  value       = aws_s3_bucket.reports.bucket
}

output "eventbridge_rule_names" {
  description = "EventBridge rule names by analysis type."
  value       = { for key, rule in aws_cloudwatch_event_rule.analysis : key => rule.name }
}

output "presign_secret_name" {
  description = "Secrets Manager secret name for presigned URL signer credentials."
  value       = aws_secretsmanager_secret.presign_user.name
}

output "signer_iam_user_name" {
  description = "IAM user name for presigned URL signing. Terraform does not create access keys for this user."
  value       = aws_iam_user.presign_user.name
}

output "cloudfront_distribution_id" {
  description = "Manually managed CloudFront distribution ID for public HTML reports, derived from public_html_cloudfront_distribution_arn when set."
  value       = var.public_html_cloudfront_distribution_arn != "" ? element(split("/", var.public_html_cloudfront_distribution_arn), length(split("/", var.public_html_cloudfront_distribution_arn)) - 1) : null
}

output "cloudfront_domain_name" {
  description = "Manually managed CloudFront domain name for public HTML reports."
  value       = var.public_html_cloudfront_domain_name != "" ? var.public_html_cloudfront_domain_name : null
}

output "public_html_base_url" {
  description = "Base URL for public HTML reports."
  value       = var.public_html_cloudfront_domain_name != "" ? "https://${var.public_html_cloudfront_domain_name}" : null
}
