data "aws_caller_identity" "current" {
  provider = aws.primary
}

locals {
  repo_root = abspath("${path.module}/../..")

  common_tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }

  function_zip_path = "${local.repo_root}/lambda-function.zip"
  layer_zip_path    = "${local.repo_root}/lambda-layer.zip"

  base_config = jsondecode(file("${local.repo_root}/config/config.json"))
  email_config = merge(
    try(local.base_config.email_notification, {}),
    {
      enabled                             = var.email_notification_enabled
      sender                              = var.ses_sender_identity != "" ? var.ses_sender_identity : try(local.base_config.email_notification.sender, "")
      presigned_url_signing_secret_id     = var.presign_secret_name
      presigned_url_signing_secret_region = var.aws_region
      presigned_url_s3_region             = var.aws_region
    }
  )
  public_html_config = merge(
    try(local.base_config.public_html, {}),
    {
      enabled = var.public_html_enabled
      prefix  = trim(var.public_html_prefix, "/")
    }
  )
  rendered_config = merge(
    local.base_config,
    {
      bedrock_model      = var.bedrock_model_id
      bedrock_region     = var.bedrock_region
      email_notification = local.email_config
      public_html        = local.public_html_config
    }
  )

  schedules = {
    daily = {
      name                = "${var.project_name}-daily"
      schedule_expression = var.daily_schedule_expression
    }
    weekly = {
      name                = "${var.project_name}-weekly"
      schedule_expression = var.weekly_schedule_expression
    }
    monthly = {
      name                = "${var.project_name}-monthly"
      schedule_expression = var.monthly_schedule_expression
    }
    quarterly = {
      name                = "${var.project_name}-quarterly"
      schedule_expression = var.quarterly_schedule_expression
    }
  }

  prompt_objects = {
    "config/news_analysis_prompt.txt"           = "${local.repo_root}/config/news_analysis_prompt.txt"
    "config/weekly_news_analysis_prompt.txt"    = "${local.repo_root}/config/weekly_news_analysis_prompt.txt"
    "config/monthly_news_analysis_prompt.txt"   = "${local.repo_root}/config/monthly_news_analysis_prompt.txt"
    "config/quarterly_news_analysis_prompt.txt" = "${local.repo_root}/config/quarterly_news_analysis_prompt.txt"
  }
}

resource "aws_s3_bucket" "reports" {
  provider = aws.primary

  bucket        = var.s3_bucket_name
  force_destroy = var.s3_force_destroy

  tags = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "reports" {
  provider = aws.primary

  bucket = aws_s3_bucket.reports.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "reports" {
  provider = aws.primary

  bucket = aws_s3_bucket.reports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "reports" {
  provider = aws.primary

  bucket = aws_s3_bucket.reports.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_policy" "reports_cloudfront_public_html" {
  provider = aws.primary
  count    = var.public_html_enabled && var.public_html_cloudfront_distribution_arn != "" ? 1 : 0

  bucket = aws_s3_bucket.reports.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudFrontReadPublicHtml"
        Effect = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.reports.arn}/${local.public_html_config.prefix}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = var.public_html_cloudfront_distribution_arn
          }
        }
      }
    ]
  })
}

resource "aws_s3_object" "config" {
  provider = aws.primary

  bucket       = aws_s3_bucket.reports.id
  key          = "config/config.json"
  content      = jsonencode(local.rendered_config)
  content_type = "application/json; charset=utf-8"
  etag         = md5(jsonencode(local.rendered_config))

  tags = local.common_tags
}

resource "aws_s3_object" "prompts" {
  provider = aws.primary
  for_each = local.prompt_objects

  bucket       = aws_s3_bucket.reports.id
  key          = each.key
  source       = each.value
  content_type = "text/plain; charset=utf-8"
  etag         = filemd5(each.value)

  tags = local.common_tags
}

resource "aws_secretsmanager_secret" "presign_user" {
  provider = aws.primary

  name                    = var.presign_secret_name
  recovery_window_in_days = 7

  tags = local.common_tags
}

resource "aws_iam_user" "presign_user" {
  provider = aws.primary

  name = "${var.project_name}-s3-presign-user"
  path = "/service/${var.project_name}/"

  tags = local.common_tags
}

resource "aws_iam_user_policy" "presign_user_s3_read" {
  provider = aws.primary

  name = "${var.project_name}-presign-s3-read"
  user = aws_iam_user.presign_user.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = [
          "${aws_s3_bucket.reports.arn}/daily/*",
          "${aws_s3_bucket.reports.arn}/weekly/*",
          "${aws_s3_bucket.reports.arn}/monthly/*",
          "${aws_s3_bucket.reports.arn}/quarterly/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role" "lambda" {
  provider = aws.primary

  name = "lambda-${var.project_name}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "lambda" {
  provider = aws.primary

  name = "${var.project_name}-permissions"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = "${aws_s3_bucket.reports.arn}/config/*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject"
        ]
        Resource = [
          "${aws_s3_bucket.reports.arn}/responses/*",
          "${aws_s3_bucket.reports.arn}/daily/*",
          "${aws_s3_bucket.reports.arn}/weekly/*",
          "${aws_s3_bucket.reports.arn}/monthly/*",
          "${aws_s3_bucket.reports.arn}/quarterly/*",
          "${aws_s3_bucket.reports.arn}/${local.public_html_config.prefix}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket"
        ]
        Resource = aws_s3_bucket.reports.arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = [
          "arn:aws:bedrock:*:*:inference-profile/*",
          "arn:aws:bedrock:*::foundation-model/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "ses:SendEmail"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_secretsmanager_secret.presign_user.arn
      }
    ]
  })
}

resource "aws_lambda_layer_version" "dependencies" {
  provider = aws.primary

  filename            = local.layer_zip_path
  layer_name          = var.lambda_layer_name
  compatible_runtimes = [var.lambda_runtime]
  source_code_hash    = filebase64sha256(local.layer_zip_path)
}

resource "aws_lambda_function" "analyzer" {
  provider = aws.primary

  function_name    = var.lambda_function_name
  role             = aws_iam_role.lambda.arn
  handler          = "lambda_handler.lambda_handler"
  runtime          = var.lambda_runtime
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory_size
  filename         = local.function_zip_path
  source_code_hash = filebase64sha256(local.function_zip_path)
  layers           = [aws_lambda_layer_version.dependencies.arn]

  environment {
    variables = {
      S3_BUCKET_NAME = aws_s3_bucket.reports.id
      TZ             = "Asia/Tokyo"
    }
  }

  depends_on = [
    aws_iam_role_policy.lambda,
    aws_s3_object.config,
    aws_s3_object.prompts
  ]

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "lambda" {
  provider = aws.primary

  name              = "/aws/lambda/${var.lambda_function_name}"
  retention_in_days = 30

  tags = local.common_tags
}

resource "aws_cloudwatch_event_rule" "analysis" {
  provider = aws.primary
  for_each = local.schedules

  name                = each.value.name
  schedule_expression = each.value.schedule_expression
  state               = "ENABLED"

  tags = local.common_tags
}

resource "aws_cloudwatch_event_target" "analysis" {
  provider = aws.primary
  for_each = local.schedules

  rule      = aws_cloudwatch_event_rule.analysis[each.key].name
  target_id = "1"
  arn       = aws_lambda_function.analyzer.arn
  input = jsonencode({
    analysis_type = each.key
  })
}

resource "aws_lambda_permission" "allow_eventbridge" {
  provider = aws.primary
  for_each = local.schedules

  statement_id  = "${var.project_name}-${each.key}-event"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.analyzer.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.analysis[each.key].arn
}

resource "aws_sesv2_email_identity" "sender" {
  provider = aws.primary
  count    = var.create_ses_identity && var.ses_sender_identity != "" ? 1 : 0

  email_identity = var.ses_sender_identity

  tags = local.common_tags
}
