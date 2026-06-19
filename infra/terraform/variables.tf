variable "project_name" {
  description = "Project name used for AWS resource names and tags."
  type        = string
  default     = "claude-news-analyzer"
}

variable "aws_region" {
  description = "Primary AWS region for Lambda, S3, EventBridge, SES, and Secrets Manager."
  type        = string
  default     = "ap-northeast-1"
}

variable "s3_bucket_name" {
  description = "S3 bucket name for config, prompts, and generated reports."
  type        = string
  default     = "claude-news-analyzer"
}

variable "lambda_function_name" {
  description = "Lambda function name."
  type        = string
  default     = "claude-news-analyzer"
}

variable "lambda_layer_name" {
  description = "Lambda layer name for Python dependencies."
  type        = string
  default     = "claude-news-analyzer-dependencies"
}

variable "lambda_memory_size" {
  description = "Lambda memory size in MB."
  type        = number
  default     = 1536
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds."
  type        = number
  default     = 900
}

variable "lambda_runtime" {
  description = "Lambda runtime."
  type        = string
  default     = "python3.11"
}

variable "bedrock_model_id" {
  description = "Bedrock model ID written into config/config.json in S3."
  type        = string
  default     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "bedrock_region" {
  description = "Bedrock runtime region written into config/config.json in S3."
  type        = string
  default     = "us-east-1"
}

variable "email_notification_enabled" {
  description = "Whether email_notification.enabled is true in the uploaded config."
  type        = bool
  default     = true
}

variable "ses_sender_identity" {
  description = "SES sender identity. When non-empty, it overrides email_notification.sender in config/config.json."
  type        = string
  default     = ""
}

variable "create_ses_identity" {
  description = "Create an SESv2 email identity for ses_sender_identity. Verification remains manual."
  type        = bool
  default     = false
}

variable "presign_secret_name" {
  description = "Secrets Manager secret name for the presigned URL signer IAM user credentials."
  type        = string
  default     = "claude-news-analyzer/s3-presign-user"
}

variable "daily_schedule_expression" {
  description = "EventBridge schedule for daily analysis."
  type        = string
  default     = "cron(0 0 * * ? *)"
}

variable "weekly_schedule_expression" {
  description = "EventBridge schedule for weekly analysis."
  type        = string
  default     = "cron(0 1 ? * SUN *)"
}

variable "monthly_schedule_expression" {
  description = "EventBridge schedule for monthly analysis."
  type        = string
  default     = "cron(0 2 1 * ? *)"
}

variable "quarterly_schedule_expression" {
  description = "EventBridge schedule for quarterly analysis."
  type        = string
  default     = "cron(0 3 1 1,4,7,10 ? *)"
}

variable "s3_force_destroy" {
  description = "Allow Terraform to delete the S3 bucket even when it contains objects."
  type        = bool
  default     = false
}

variable "enable_public_html_cloudfront" {
  description = "Create a CloudFront distribution that exposes only HTML under the public_html_prefix S3 prefix via OAC."
  type        = bool
  default     = true
}

variable "public_html_prefix" {
  description = "S3 prefix used for CloudFront-public HTML copies."
  type        = string
  default     = "public"

  validation {
    condition     = length(trim(var.public_html_prefix, "/")) > 0
    error_message = "public_html_prefix must not be empty."
  }
}

variable "cloudfront_price_class" {
  description = "CloudFront price class for the public HTML distribution."
  type        = string
  default     = "PriceClass_200"

  validation {
    condition = contains([
      "PriceClass_100",
      "PriceClass_200",
      "PriceClass_All"
    ], var.cloudfront_price_class)
    error_message = "cloudfront_price_class must be PriceClass_100, PriceClass_200, or PriceClass_All."
  }
}

variable "cloudfront_default_ttl" {
  description = "Default TTL in seconds for public HTML CloudFront cache."
  type        = number
  default     = 300
}

variable "cloudfront_max_ttl" {
  description = "Maximum TTL in seconds for public HTML CloudFront cache."
  type        = number
  default     = 86400
}
