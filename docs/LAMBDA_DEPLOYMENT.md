# AWS Lambda デプロイガイド

このドキュメントは AWS 運用者向けの実行手順書です。標準手順は Terraform + Makefile による初回構築、再デプロイ、S3 config アップロード、IAM、署名用 IAM ユーザー、Secrets Manager、SES、EventBridge、動作確認です。既存 AWS CLI 手順は末尾の manual/legacy 手順として残します。

例では以下を使います。必要に応じて置き換えてください。

```bash
export AWS_REGION="ap-northeast-1"
export S3_BUCKET_NAME="claude-news-analyzer"
export LAMBDA_FUNCTION_NAME="claude-news-analyzer"
export LAMBDA_ROLE_NAME="lambda-claude-news-analyzer"
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export PRESIGN_SECRET_NAME="claude-news-analyzer/s3-presign-user"
export PROJECT_NAME="claude-news-analyzer"
```

## 前提条件

- AWS CLI 設定済み
- Terraform 1.5+
- Docker（Lambda Layer 構築用）
- Python 3.11+
- zip コマンド
- Bedrock の対象モデルが利用可能な AWS アカウント
- SES で送信元アドレスまたはドメインを検証済み

必要な AWS 権限は Lambda、S3、IAM、EventBridge、CloudWatch Logs、Bedrock、SES、Secrets Manager です。

## 1. 標準手順: Terraform + Makefile

ローカル端末から以下の順序で構築・更新します。

```bash
make setup
source .venv/bin/activate
make test
make package-layer
make package-function
make tf-init
make tf-plan
make tf-apply
```

`make package-layer` は Docker を使って `lambda-layer.zip` を作成します。`make package-function` は Lambda 関数コードを `lambda-function.zip` に固めます。Terraform はこの2つの zip が存在する前提で Lambda Layer version と Lambda 関数を作成・更新します。

## 2. Terraform 変数

必要に応じてサンプルをコピーして編集します。

```bash
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
```

主な変数:

- `project_name`
- `aws_region`
- `s3_bucket_name`
- `lambda_function_name`
- `lambda_layer_name`
- `lambda_memory_size`
- `lambda_timeout`
- `lambda_runtime`
- `bedrock_model_id`
- `bedrock_region`
- `email_notification_enabled`
- `ses_sender_identity`
- `create_ses_identity`
- `presign_secret_name`
- `daily_schedule_expression`
- `weekly_schedule_expression`
- `monthly_schedule_expression`
- `quarterly_schedule_expression`
- `public_html_enabled`
- `public_html_prefix`
- `public_html_cloudfront_distribution_arn`
- `public_html_cloudfront_domain_name`

`infra/terraform/terraform.tfvars` は Git 管理しません。秘密値は書かないでください。

## 3. Terraform が管理する AWS リソース

- S3 bucket、SSE-S3 暗号化、バージョニング、公開アクセスブロック
- 手動作成した CloudFront distribution 向けの `public/` 限定 S3 bucket policy
- S3 `config/config.json` と 4 種類のプロンプト
- Lambda execution role と inline policy
- Lambda Layer version
- Lambda function
- CloudWatch Logs log group
- EventBridge rules、targets、Lambda permissions
- 旧 presigned URL 署名用 Secrets Manager secret container
- 旧 presigned URL 署名用 IAM user と read-only S3 policy
- 任意の SESv2 identity

Terraform は `config/config.json` を読み込み、以下の値を変数で上書きした JSON を S3 に保存します。

- `bedrock_model`
- `bedrock_region`
- `email_notification.enabled`
- `email_notification.sender`
- `public_html.enabled`
- `public_html.prefix`
- `public_html.base_url`

CloudFront distribution は Terraform では作成しません。Free plan で運用するため、AWS Console で CloudFront distribution を手動作成します。作成後に `public_html_cloudfront_distribution_arn` を設定すると、Terraform はその distribution に対して `public/*` の `s3:GetObject` だけを許可する bucket policy を作成します。`public_html_cloudfront_domain_name` は output と手順確認用です。

手動作成時の推奨設定:

- Pricing plan: Free
- Origin: S3 bucket regional domain
- Origin path: `/public`
- Origin access: Origin Access Control
- OAC signing behavior: always
- Viewer protocol policy: redirect HTTP to HTTPS
- Allowed methods: GET, HEAD
- Response headers policy: AWS managed SecurityHeadersPolicy
- Cache TTL: min 0, default 300, max 86400 を目安

## 4. Terraform 実行

初回:

```bash
make tf-init
make tf-plan
make tf-apply
```

更新時:

```bash
make package-function
make tf-plan
make tf-apply
```

依存ライブラリを変更した場合は `make package-layer` も実行してください。`terraform plan` で作成/変更対象を確認してから `apply` します。

既存の手動作成済みリソースを Terraform 管理へ移す場合は、`apply` の前に import してください。少なくとも既存 S3 バケット、Lambda 関数、IAM ロール、Secrets Manager Secret、EventBridge ルールが同名で存在する場合は import 対象です。

```bash
terraform -chdir=infra/terraform import 'aws_s3_bucket.reports' "${S3_BUCKET_NAME}"
terraform -chdir=infra/terraform import 'aws_lambda_function.analyzer' "${LAMBDA_FUNCTION_NAME}"
terraform -chdir=infra/terraform import 'aws_iam_role.lambda' "${LAMBDA_ROLE_NAME}"
terraform -chdir=infra/terraform import 'aws_iam_role_policy.lambda' "${LAMBDA_ROLE_NAME}:${PROJECT_NAME}-permissions"
terraform -chdir=infra/terraform import 'aws_secretsmanager_secret.presign_user' "${PRESIGN_SECRET_NAME}"
terraform -chdir=infra/terraform import 'aws_cloudwatch_event_rule.analysis["daily"]' "${PROJECT_NAME}-daily"
terraform -chdir=infra/terraform import 'aws_cloudwatch_event_rule.analysis["weekly"]' "${PROJECT_NAME}-weekly"
terraform -chdir=infra/terraform import 'aws_cloudwatch_event_rule.analysis["monthly"]' "${PROJECT_NAME}-monthly"
terraform -chdir=infra/terraform import 'aws_cloudwatch_event_rule.analysis["quarterly"]' "${PROJECT_NAME}-quarterly"
terraform -chdir=infra/terraform import 'aws_cloudwatch_event_target.analysis["daily"]' "${PROJECT_NAME}-daily/1"
terraform -chdir=infra/terraform import 'aws_cloudwatch_event_target.analysis["weekly"]' "${PROJECT_NAME}-weekly/1"
terraform -chdir=infra/terraform import 'aws_cloudwatch_event_target.analysis["monthly"]' "${PROJECT_NAME}-monthly/1"
terraform -chdir=infra/terraform import 'aws_cloudwatch_event_target.analysis["quarterly"]' "${PROJECT_NAME}-quarterly/1"
terraform -chdir=infra/terraform import 'aws_lambda_permission.allow_eventbridge["daily"]' "${PROJECT_NAME}/${PROJECT_NAME}-daily-event"
terraform -chdir=infra/terraform import 'aws_lambda_permission.allow_eventbridge["weekly"]' "${PROJECT_NAME}/${PROJECT_NAME}-weekly-event"
terraform -chdir=infra/terraform import 'aws_lambda_permission.allow_eventbridge["monthly"]' "${PROJECT_NAME}/${PROJECT_NAME}-monthly-event"
terraform -chdir=infra/terraform import 'aws_lambda_permission.allow_eventbridge["quarterly"]' "${PROJECT_NAME}/${PROJECT_NAME}-quarterly-event"

```

import 後は必ず `make tf-plan` で差分を確認してください。既存運用値と Terraform 変数が異なる場合、Terraform は変数側へ更新します。

## 5. 旧 presigned URL 署名用 IAM ユーザーと Secret 値

現在のメール通知は CloudFront URL を使うため、この署名用 IAM ユーザーと Secret は新規通知では使いません。既存環境の互換リソースとして Terraform に残しています。長期アクセスキーは Terraform で作成しません。`aws_iam_access_key` は秘密値を Terraform state に保存するためです。

`terraform apply` 後の output で IAM ユーザー名と Secret 名を確認します。

```bash
terraform -chdir=infra/terraform output signer_iam_user_name
terraform -chdir=infra/terraform output presign_secret_name
```

アクセスキーを手動作成し、Secret に JSON 文字列で保存します。`aws_session_token` は含めないでください。

```bash
aws iam create-access-key \
  --user-name "$(terraform -chdir=infra/terraform output -raw signer_iam_user_name)"

aws secretsmanager put-secret-value \
  --secret-id "$(terraform -chdir=infra/terraform output -raw presign_secret_name)" \
  --region "${AWS_REGION}" \
  --secret-string '{"aws_access_key_id":"AKIA...","aws_secret_access_key":"..."}'
```

ローテーション時は Secret を新しいアクセスキーへ更新し、古いキーはメール内 URL の有効期限が切れてから無効化してください。古いキーを即時無効化すると、そのキーで署名済みの URL も利用できなくなります。

## 6. SES identity

`create_ses_identity = true` かつ `ses_sender_identity` が空でない場合、Terraform は SESv2 identity を作成します。ただし、メールアドレスやドメインの検証完了は手動確認です。SES sandbox 環境では宛先メールアドレスも検証済みである必要があります。本番送信する場合は SES sandbox 解除を申請してください。

既存の検証済み identity を使う場合は `create_ses_identity = false` のままで、`ses_sender_identity` だけ指定してください。

## 7. 手動実行確認

日次分析:

```bash
make invoke-daily
cat output-daily.json
aws logs tail "/aws/lambda/${LAMBDA_FUNCTION_NAME}" --follow --region "${AWS_REGION}"
```

週次・月次・四半期は前段レポートが S3 に存在する状態で、payload の `analysis_type` を変えて実行します。

## 8. リリース前チェック

```bash
make test
make package-function
make package-layer
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform init -backend=false
terraform -chdir=infra/terraform validate
make tf-plan
git status --short
```

確認事項:

- `lambda-function.zip`, `lambda-layer.zip`, `.terraform/`, `*.tfstate`, `*.tfvars` が Git の未追跡対象に出ないこと
- Terraform plan/state に IAM アクセスキー値やメール認証情報が入っていないこと
- Lambda 環境変数に `S3_BUCKET_NAME` と `TZ` があること
- EventBridge rule が `daily`, `weekly`, `monthly`, `quarterly` の4種類あること
- S3 `config/` に `config.json` と4種類のプロンプトがあること
- CloudWatch Logs に実行ログが出ること
- `public_html_cloudfront_distribution_arn` を設定している場合、S3 bucket policy の Resource が `public/*` のみであること

## Manual/legacy AWS CLI 手順

以下は Terraform 移行前の手動手順です。標準運用では Makefile + Terraform を使ってください。

## 1. S3 バケット作成

```bash
aws s3 mb "s3://${S3_BUCKET_NAME}" --region "${AWS_REGION}"
aws s3 ls "s3://${S3_BUCKET_NAME}/"
```

既存バケットを使う場合は作成せず、以降の `S3_BUCKET_NAME` だけ合わせてください。

## 2. config とプロンプトを S3 にアップロード

Lambda は `config/config.json` の `prompt_paths` を参照し、`analysis_type` ごとに日次・週次・月次・四半期プロンプトを切り替えます。

```bash
aws s3 cp config/config.json "s3://${S3_BUCKET_NAME}/config/config.json"
aws s3 cp config/news_analysis_prompt.txt "s3://${S3_BUCKET_NAME}/config/news_analysis_prompt.txt"
aws s3 cp config/weekly_news_analysis_prompt.txt "s3://${S3_BUCKET_NAME}/config/weekly_news_analysis_prompt.txt"
aws s3 cp config/monthly_news_analysis_prompt.txt "s3://${S3_BUCKET_NAME}/config/monthly_news_analysis_prompt.txt"
aws s3 cp config/quarterly_news_analysis_prompt.txt "s3://${S3_BUCKET_NAME}/config/quarterly_news_analysis_prompt.txt"
aws s3 ls "s3://${S3_BUCKET_NAME}/config/"
```

現在の `config/config.json` では、`email_notification.enabled_analysis_types` が `daily`, `weekly`, `monthly`, `quarterly` を含みます。SES や Secrets Manager の準備が未完了の環境では、通知を無効化するか、通知対象を絞ってからアップロードしてください。

## 3. Lambda 実行ロール作成

信頼ポリシーは `deploy/policies/trust-policy.json`、権限ポリシーは `deploy/policies/permissions-policy.json` を正本とします。ポリシー本文を変更する場合は、README ではなくこのファイルと `deploy/policies/*.json` を更新してください。

`deploy/policies/permissions-policy.json` には以下が含まれます。

- `config/*` の読み取り
- `responses/*`, `daily/*`, `weekly/*`, `monthly/*`, `quarterly/*`, `public/*` の読み書き
- CloudWatch Logs 書き込み
- Bedrock `InvokeModel`
- SES `SendEmail`
- Secrets Manager `GetSecretValue`

`secretsmanager:GetSecretValue` の Resource には `ACCOUNT_ID` プレースホルダーがあります。実アカウント ID に置換してから適用してください。

```bash
sed "s/ACCOUNT_ID/${ACCOUNT_ID}/g" deploy/policies/permissions-policy.json > /tmp/claude-news-analyzer-permissions-policy.json

aws iam create-role \
  --role-name "${LAMBDA_ROLE_NAME}" \
  --assume-role-policy-document file://deploy/policies/trust-policy.json

aws iam put-role-policy \
  --role-name "${LAMBDA_ROLE_NAME}" \
  --policy-name claude-news-analyzer-permissions \
  --policy-document file:///tmp/claude-news-analyzer-permissions-policy.json

export LAMBDA_ROLE_ARN="$(aws iam get-role \
  --role-name "${LAMBDA_ROLE_NAME}" \
  --query 'Role.Arn' \
  --output text)"
```

既存ロールを更新する場合は `create-role` を実行せず、`put-role-policy` だけを実行します。

## 4. Legacy: 署名用 IAM ユーザーと Secrets Manager

現在のメール通知は CloudFront URL を使うため、この手順は旧 presigned URL 通知を復旧する場合だけ参照します。7 日間に近い presigned URL が必要な場合、Lambda 実行ロールの一時認証情報ではなく、署名専用 IAM ユーザーの長期アクセスキーを Secrets Manager に保存して署名していました。

```json
{
  "presigned_url_signer_type": "iam_user_secret",
  "presigned_url_signing_secret_id": "claude-news-analyzer/s3-presign-user",
  "presigned_url_signing_secret_region": "ap-northeast-1",
  "presigned_url_s3_region": "ap-northeast-1",
  "presigned_url_expires_seconds": 604800
}
```

署名用 IAM ユーザーには、メールで共有するオブジェクトへの `s3:GetObject` のみを許可します。書き込み権限やバケット一覧権限は付けません。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": [
        "arn:aws:s3:::claude-news-analyzer/daily/*",
        "arn:aws:s3:::claude-news-analyzer/weekly/*",
        "arn:aws:s3:::claude-news-analyzer/monthly/*",
        "arn:aws:s3:::claude-news-analyzer/quarterly/*"
      ]
    }
  ]
}
```

過去データ移行などで旧 `responses/*` をメール共有する必要がある場合だけ、`responses/*` の `s3:GetObject` を追加してください。S3 バケットを SSE-KMS で暗号化している場合は、対象 KMS キーの `kms:Decrypt` も署名用 IAM ユーザーに追加します。

アクセスキーを作成し、Secrets Manager に JSON 文字列で保存します。`aws_session_token` は含めないでください。一時認証情報と判定され、メール通知は失敗します。

```bash
aws secretsmanager create-secret \
  --name claude-news-analyzer/s3-presign-user \
  --region "${AWS_REGION}" \
  --secret-string '{"aws_access_key_id":"AKIA...","aws_secret_access_key":"..."}'
```

既存 Secret を更新する場合:

```bash
aws secretsmanager put-secret-value \
  --secret-id claude-news-analyzer/s3-presign-user \
  --region "${AWS_REGION}" \
  --secret-string '{"aws_access_key_id":"AKIA...","aws_secret_access_key":"..."}'
```

ローテーション時は Secret を新しいアクセスキーへ更新し、古いキーはメール内 URL の有効期限が切れてから無効化してください。古いキーを即時無効化すると、そのキーで署名済みの URL も利用できなくなります。

## 5. SES 設定

送信元メールアドレスまたはドメインを SES Verified identity として検証します。

```bash
aws ses verify-email-identity \
  --email-address sender@example.com \
  --region "${AWS_REGION}"
```

SES sandbox 環境では宛先メールアドレスも検証済みである必要があります。本番送信する場合は SES sandbox 解除を申請してください。

`config/config.json` の `email_notification.sender`, `recipients`, `ses_region` が SES の設定と一致していることを確認します。

## 6. Lambda Layer 構築

```bash
./deploy/build_layer.sh
ls -lh lambda-layer.zip
```

`lambda-layer.zip` が Lambda の直接アップロード上限を超える場合は、トラブルシューティングの「Lambda Layer が大きすぎる」を参照してください。

## 7. Lambda 関数デプロイ

```bash
export LAMBDA_ROLE_ARN="${LAMBDA_ROLE_ARN:-arn:aws:iam::${ACCOUNT_ID}:role/${LAMBDA_ROLE_NAME}}"
export S3_BUCKET_NAME="${S3_BUCKET_NAME}"
export AWS_REGION="${AWS_REGION}"

./deploy/deploy.sh
```

`deploy/deploy.sh` は `S3_BUCKET_NAME` と `TZ=Asia/Tokyo` を Lambda 環境変数に設定します。既存の `claude-news-analyzer` がある場合、関数を削除せず `update-function-code` と `update-function-configuration` で更新します。

設定確認:

```bash
aws lambda get-function-configuration \
  --function-name "${LAMBDA_FUNCTION_NAME}" \
  --region "${AWS_REGION}" \
  --query 'Environment.Variables'
```

## 8. 手動実行

日次分析:

```bash
AWS_MAX_ATTEMPTS=1 aws lambda invoke \
  --function-name "${LAMBDA_FUNCTION_NAME}" \
  --region "${AWS_REGION}" \
  --cli-read-timeout 900 \
  --cli-connect-timeout 10 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"analysis_type":"daily"}' \
  output-daily.json

cat output-daily.json
aws logs tail "/aws/lambda/${LAMBDA_FUNCTION_NAME}" --follow --region "${AWS_REGION}"
```

週次・月次・四半期は前段レポートが S3 に存在する状態で実行します。

```bash
AWS_MAX_ATTEMPTS=1 aws lambda invoke \
  --function-name "${LAMBDA_FUNCTION_NAME}" \
  --region "${AWS_REGION}" \
  --cli-read-timeout 900 \
  --cli-connect-timeout 10 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"analysis_type":"weekly"}' \
  output-weekly.json

AWS_MAX_ATTEMPTS=1 aws lambda invoke \
  --function-name "${LAMBDA_FUNCTION_NAME}" \
  --region "${AWS_REGION}" \
  --cli-read-timeout 900 \
  --cli-connect-timeout 10 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"analysis_type":"monthly"}' \
  output-monthly.json

AWS_MAX_ATTEMPTS=1 aws lambda invoke \
  --function-name "${LAMBDA_FUNCTION_NAME}" \
  --region "${AWS_REGION}" \
  --cli-read-timeout 900 \
  --cli-connect-timeout 10 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"analysis_type":"quarterly"}' \
  output-quarterly.json
```

期待されるレスポンス:

```json
{
  "statusCode": 200,
  "body": "{\"success\": true, \"message\": \"daily ニュース分析が正常に完了しました\"}"
}
```

## 9. EventBridge スケジュール

同じ Lambda 関数に対して、日次・週次・月次・四半期の 4 つの EventBridge ルールを作成します。各ターゲットの `Input` で `analysis_type` を渡します。

`put-targets` は shorthand ではなく file JSON 方式で指定します。シェルの引用、JSON の二重エスケープ、AWS CLI shorthand parser の解釈差による失敗を避けるためです。

```bash
export LAMBDA_ARN="$(aws lambda get-function \
  --function-name "${LAMBDA_FUNCTION_NAME}" \
  --region "${AWS_REGION}" \
  --query 'Configuration.FunctionArn' \
  --output text)"

aws events put-rule \
  --name claude-news-analyzer-daily \
  --schedule-expression 'cron(0 0 * * ? *)' \
  --state ENABLED \
  --region "${AWS_REGION}"

cat > /tmp/claude-news-analyzer-daily-target.json <<EOF
[
  {
    "Id": "1",
    "Arn": "${LAMBDA_ARN}",
    "Input": "{\"analysis_type\":\"daily\"}"
  }
]
EOF

aws events put-targets \
  --rule claude-news-analyzer-daily \
  --targets file:///tmp/claude-news-analyzer-daily-target.json \
  --region "${AWS_REGION}"

aws lambda add-permission \
  --function-name "${LAMBDA_FUNCTION_NAME}" \
  --statement-id claude-news-analyzer-daily-event \
  --action 'lambda:InvokeFunction' \
  --principal events.amazonaws.com \
  --source-arn "arn:aws:events:${AWS_REGION}:${ACCOUNT_ID}:rule/claude-news-analyzer-daily" \
  --region "${AWS_REGION}"
```

週次、月次、四半期:

```bash
aws events put-rule \
  --name claude-news-analyzer-weekly \
  --schedule-expression 'cron(0 1 ? * SUN *)' \
  --state ENABLED \
  --region "${AWS_REGION}"

cat > /tmp/claude-news-analyzer-weekly-target.json <<EOF
[
  {
    "Id": "1",
    "Arn": "${LAMBDA_ARN}",
    "Input": "{\"analysis_type\":\"weekly\"}"
  }
]
EOF

aws events put-targets \
  --rule claude-news-analyzer-weekly \
  --targets file:///tmp/claude-news-analyzer-weekly-target.json \
  --region "${AWS_REGION}"

aws lambda add-permission \
  --function-name "${LAMBDA_FUNCTION_NAME}" \
  --statement-id claude-news-analyzer-weekly-event \
  --action 'lambda:InvokeFunction' \
  --principal events.amazonaws.com \
  --source-arn "arn:aws:events:${AWS_REGION}:${ACCOUNT_ID}:rule/claude-news-analyzer-weekly" \
  --region "${AWS_REGION}"

aws events put-rule \
  --name claude-news-analyzer-monthly \
  --schedule-expression 'cron(0 2 1 * ? *)' \
  --state ENABLED \
  --region "${AWS_REGION}"

cat > /tmp/claude-news-analyzer-monthly-target.json <<EOF
[
  {
    "Id": "1",
    "Arn": "${LAMBDA_ARN}",
    "Input": "{\"analysis_type\":\"monthly\"}"
  }
]
EOF

aws events put-targets \
  --rule claude-news-analyzer-monthly \
  --targets file:///tmp/claude-news-analyzer-monthly-target.json \
  --region "${AWS_REGION}"

aws lambda add-permission \
  --function-name "${LAMBDA_FUNCTION_NAME}" \
  --statement-id claude-news-analyzer-monthly-event \
  --action 'lambda:InvokeFunction' \
  --principal events.amazonaws.com \
  --source-arn "arn:aws:events:${AWS_REGION}:${ACCOUNT_ID}:rule/claude-news-analyzer-monthly" \
  --region "${AWS_REGION}"

aws events put-rule \
  --name claude-news-analyzer-quarterly \
  --schedule-expression 'cron(0 3 1 1,4,7,10 ? *)' \
  --state ENABLED \
  --region "${AWS_REGION}"

cat > /tmp/claude-news-analyzer-quarterly-target.json <<EOF
[
  {
    "Id": "1",
    "Arn": "${LAMBDA_ARN}",
    "Input": "{\"analysis_type\":\"quarterly\"}"
  }
]
EOF

aws events put-targets \
  --rule claude-news-analyzer-quarterly \
  --targets file:///tmp/claude-news-analyzer-quarterly-target.json \
  --region "${AWS_REGION}"

aws lambda add-permission \
  --function-name "${LAMBDA_FUNCTION_NAME}" \
  --statement-id claude-news-analyzer-quarterly-event \
  --action 'lambda:InvokeFunction' \
  --principal events.amazonaws.com \
  --source-arn "arn:aws:events:${AWS_REGION}:${ACCOUNT_ID}:rule/claude-news-analyzer-quarterly" \
  --region "${AWS_REGION}"
```

既に同じ `statement-id` が存在する場合、`add-permission` は失敗します。既存権限を確認し、必要に応じて `remove-permission` 後に再実行してください。

```bash
aws lambda get-policy \
  --function-name "${LAMBDA_FUNCTION_NAME}" \
  --region "${AWS_REGION}"
```

## 10. 動作確認

S3 出力:

```bash
TODAY="$(TZ=Asia/Tokyo date +%Y-%m-%d)"
aws s3 ls "s3://${S3_BUCKET_NAME}/daily/"
aws s3 ls "s3://${S3_BUCKET_NAME}/weekly/"
aws s3 ls "s3://${S3_BUCKET_NAME}/monthly/"
aws s3 ls "s3://${S3_BUCKET_NAME}/quarterly/"
aws s3 cp "s3://${S3_BUCKET_NAME}/daily/${TODAY}.md" ./
aws s3 cp "s3://${S3_BUCKET_NAME}/daily/${TODAY}.html" ./
aws s3 cp "s3://${S3_BUCKET_NAME}/daily/${TODAY}_articles.txt" ./
```

分析結果は `.md` と `.html` の両方を保存します。`public_html.enabled` が `true` の場合は、HTML だけを `public/` 配下にも追加保存します。日次の例:

- 既存の保存先: `s3://${S3_BUCKET_NAME}/daily/${TODAY}.html`
- CloudFront 公開用実体: `s3://${S3_BUCKET_NAME}/public/daily/${TODAY}.html`
- 公開 URL: `https://<cloudfront-domain>/daily/${TODAY}.html`

既存 HTML を初回公開する場合:

```bash
make publish-existing-html
```

CloudFront のキャッシュを明示的に破棄する場合:

```bash
CLOUDFRONT_DISTRIBUTION_ID="<manual-cloudfront-distribution-id>" make cf-invalidate
```

CloudFront は Free plan で手動作成し、通常の S3 origin + OAC を使います。S3 website endpoint や public bucket policy は使いません。`config/`、Markdown、記事一覧 txt、元の `daily/weekly/monthly/quarterly/` は公開対象外です。公開確認では `https://<cloudfront-domain>/daily/<file>.html` が 200、`https://<cloudfront-domain>/config/config.json` が 403 または 404、S3 直 URL が匿名アクセス不可であることを確認してください。

週次・月次・四半期の入力には `.md` を優先して使い、移行期間の互換用として過去の `.txt` も参照します。四半期分析は `quarterly/FY2026-Q1.md` と `quarterly/FY2026-Q1.html` のように保存します。メール通知には、対象処理で生成したHTMLレポートと `index.html` の CloudFront リンクだけを載せます。日次の収集記事一覧は `_articles.txt` として保存しますが、メール通知には含めません。

メール通知:

- SES 送信元と sandbox 環境の宛先が検証済みであること
- `public_html.base_url` が CloudFront のベースURLになっていること
- メール本文の分析結果リンクが CloudFront の `.html` を指していること
- メール本文に `index.html` の CloudFront リンクが含まれること
- 日次メール本文に `_articles.txt` が含まれないこと

CloudWatch Logs:

```bash
aws logs tail "/aws/lambda/${LAMBDA_FUNCTION_NAME}" --follow --region "${AWS_REGION}"
```

## トラブルシューティング

### Lambda 関数がタイムアウトする

原因は記事数、本文取得、Bedrock 応答待ちのいずれかであることが多いです。

- `config/config.json` の `max_articles_per_site` を減らす
- Lambda タイムアウトが 900 秒になっているか確認する
- `parallel_content_workers` を調整する
- `bedrock_read_timeout` が 600 秒以上になっているか確認する

### S3 アクセス拒否

Lambda 実行ロールに最新の権限を反映します。

```bash
sed "s/ACCOUNT_ID/${ACCOUNT_ID}/g" deploy/policies/permissions-policy.json > /tmp/claude-news-analyzer-permissions-policy.json

aws iam put-role-policy \
  --role-name "${LAMBDA_ROLE_NAME}" \
  --policy-name claude-news-analyzer-permissions \
  --policy-document file:///tmp/claude-news-analyzer-permissions-policy.json
```

必要なプレフィックスは `config/*`, `daily/*`, `weekly/*`, `monthly/*`, `quarterly/*`, 旧互換の `responses/*` です。

### CloudFront URL がメールに出ない

`public_html.base_url` が空でないこと、CloudFront distribution の domain name を `public_html_cloudfront_domain_name` に設定して `make tf-apply` 済みであることを確認します。

### Legacy: presigned URL が 7 日より早く失効する

`presigned_url_signer_type` が `iam_user_secret` で、Secret に `aws_session_token` が含まれていないことを確認します。メール本文の URL に `X-Amz-Security-Token` が含まれる場合、一時認証情報で署名されています。

### 週次分析の入力が見つからない

週次分析は前週の日次ファイルを `daily/` から読み込みます。新しい `daily/YYYY-MM-DD.md` を優先し、移行期間の互換用として `daily/YYYY-MM-DD.txt` と `responses/YYYY-MM-DD.txt` も読み取り対象です。

```bash
aws s3 ls "s3://${S3_BUCKET_NAME}/daily/"
aws s3 ls "s3://${S3_BUCKET_NAME}/responses/"
```

### 月次分析の入力が見つからない

月次分析は前月内に終了日を持つ週次ファイルを `weekly/` から読み込みます。新しいファイル名は `weekly/YYYY-MM-DD_YYYY-MM-DD.md` です。過去の `.txt` も互換参照しますが、同じ期間で `.md` と `.txt` が両方ある場合は `.md` だけを使います。

```bash
aws s3 ls "s3://${S3_BUCKET_NAME}/weekly/"
```

### 四半期分析の入力が見つからない、または不足する

四半期分析は直前四半期の3か月分の月次ファイルを `monthly/` から読み込みます。新しい `monthly/YYYY-MM.md` を優先し、互換用として `monthly/YYYY-MM.txt` も読み取ります。同じ月で `.md` と `.txt` が両方ある場合は `.md` だけを使います。

```bash
aws s3 ls "s3://${S3_BUCKET_NAME}/monthly/"
```

入力が0件の場合は失敗します。1から2件だけ存在する場合は CloudWatch Logs に不足警告を出し、利用可能な月次レポートだけで分析します。

### CreateFunction で Function already exist になる

アカウント、リージョン、`lambda:GetFunction` 権限を確認します。

```bash
aws sts get-caller-identity
aws lambda get-function \
  --function-name "${LAMBDA_FUNCTION_NAME}" \
  --region "${AWS_REGION}"
```

通常は Lambda 関数を削除せず、`./deploy/deploy.sh` で更新します。

### Lambda Layer が大きすぎる

Layer zip を S3 に置いてから公開します。

```bash
aws s3 cp lambda-layer.zip "s3://${S3_BUCKET_NAME}/layers/lambda-layer.zip"

aws lambda publish-layer-version \
  --layer-name claude-news-analyzer-dependencies \
  --content "S3Bucket=${S3_BUCKET_NAME},S3Key=layers/lambda-layer.zip" \
  --compatible-runtimes python3.11 \
  --region "${AWS_REGION}"
```

公開された Layer ARN を Lambda 関数に設定してください。

## ロールバック

スケジュール実行を止め、必要に応じて S3 の結果を退避します。

```bash
aws events disable-rule --name claude-news-analyzer-daily --region "${AWS_REGION}"
aws events disable-rule --name claude-news-analyzer-weekly --region "${AWS_REGION}"
aws events disable-rule --name claude-news-analyzer-monthly --region "${AWS_REGION}"
aws events disable-rule --name claude-news-analyzer-quarterly --region "${AWS_REGION}"

aws s3 sync "s3://${S3_BUCKET_NAME}/daily/" ./responses/daily/
aws s3 sync "s3://${S3_BUCKET_NAME}/weekly/" ./responses/weekly/
aws s3 sync "s3://${S3_BUCKET_NAME}/monthly/" ./responses/monthly/
aws s3 sync "s3://${S3_BUCKET_NAME}/quarterly/" ./responses/quarterly/
aws s3 sync "s3://${S3_BUCKET_NAME}/responses/" ./responses/legacy/
```

ローカルで確認する場合:

```bash
export S3_BUCKET_NAME="${S3_BUCKET_NAME}"
PYTHONPATH=src python -m bedrock_news_analyzer.lambda_handler
```

## コスト目安

日次 30 回、週次 4-5 回、月次 1 回、四半期 1 回の実行では、Lambda/S3/CloudWatch Logs は小額に収まる想定です。Bedrock の料金はモデル、入力トークン、出力トークン量に依存するため別途確認してください。

## 参考

- AWS Lambda 公式ドキュメント: https://docs.aws.amazon.com/lambda/
- Lambda Layers: https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html
- EventBridge スケジュール式: https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-create-rule-schedule.html
- CloudWatch Logs: https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/
