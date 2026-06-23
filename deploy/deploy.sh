#!/bin/bash
# Lambda関数デプロイスクリプト
# Lambda Layer + Lambda関数を一括デプロイ

set -e

# デフォルト設定
FUNCTION_NAME="${LAMBDA_FUNCTION_NAME:-claude-news-analyzer}"
LAYER_NAME="${LAMBDA_LAYER_NAME:-claude-news-analyzer-dependencies}"
RUNTIME="python3.11"
HANDLER="lambda_handler.lambda_handler"
TIMEOUT=900  # 15分
MEMORY=1536  # 1.5GB
REGION="${AWS_REGION:-ap-northeast-1}"
S3_BUCKET="${S3_BUCKET_NAME:-claude-news-analyzer}"

# IAMロールARN（環境変数または手動設定）
ROLE_ARN="${LAMBDA_ROLE_ARN}"

echo "=" * 80
echo "Lambda関数デプロイを開始します"
echo "=" * 80
echo "関数名: $FUNCTION_NAME"
echo "レイヤー名: $LAYER_NAME"
echo "ランタイム: $RUNTIME"
echo "タイムアウト: ${TIMEOUT}秒"
echo "メモリ: ${MEMORY}MB"
echo "リージョン: $REGION"
echo "S3バケット: $S3_BUCKET"
echo "=" * 80

# プロジェクトルートに移動
cd "$(dirname "$0")/.."

# Lambda Layerが存在しない場合は構築
if [ ! -f "lambda-layer.zip" ]; then
    echo "Lambda Layerが見つかりません。構築します..."
    ./deploy/build_layer.sh
fi

echo ""
echo "=== Lambda Layer デプロイ ==="
# Lambda Layerを公開
echo "Lambda Layerを公開中..."
LAYER_ARN=$(aws lambda publish-layer-version \
  --layer-name ${LAYER_NAME} \
  --zip-file fileb://lambda-layer.zip \
  --compatible-runtimes ${RUNTIME} \
  --region ${REGION} \
  --query 'LayerVersionArn' \
  --output text)

if [ -z "$LAYER_ARN" ]; then
    echo "❌ Lambda Layerの公開に失敗しました"
    exit 1
fi

echo "✓ Lambda Layer作成完了: ${LAYER_ARN}"

echo ""
echo "=== Lambda関数パッケージ作成 ==="
# 既存のzipファイルを削除
rm -f lambda-function.zip

# 関数コードをzip化
echo "Lambda関数コードをパッケージング中..."
zip -r lambda-function.zip \
  lambda_handler.py \
  s3_handler.py \
  cloudwatch_logger.py \
  llm_fetcher.py \
  report_saver.py \
  report_html_renderer.py \
  bedrock_client.py \
  news_scraper.py \
  email_notifier.py \
  -q

function_size=$(du -h lambda-function.zip | cut -f1)
echo "✓ Lambda関数パッケージ作成完了: lambda-function.zip ($function_size)"

echo ""
echo "=== Lambda関数デプロイ ==="

# Lambda関数が存在するか確認
GET_FUNCTION_ERROR=$(mktemp)
if aws lambda get-function --function-name ${FUNCTION_NAME} --region ${REGION} --no-cli-pager > /dev/null 2>"${GET_FUNCTION_ERROR}"; then
    echo "Lambda関数が既に存在します。更新します..."

    # コードを更新
    aws lambda update-function-code \
      --function-name ${FUNCTION_NAME} \
      --zip-file fileb://lambda-function.zip \
      --region ${REGION} \
      --no-cli-pager > /dev/null

    echo "✓ Lambda関数コード更新完了"

    echo "Lambda関数コード更新の完了待機中..."
    aws lambda wait function-updated \
      --function-name ${FUNCTION_NAME} \
      --region ${REGION}

    # 設定を更新
    aws lambda update-function-configuration \
      --function-name ${FUNCTION_NAME} \
      --runtime ${RUNTIME} \
      --handler ${HANDLER} \
      --timeout ${TIMEOUT} \
      --memory-size ${MEMORY} \
      --layers ${LAYER_ARN} \
      --environment "Variables={S3_BUCKET_NAME=${S3_BUCKET},TZ=Asia/Tokyo}" \
      --region ${REGION} \
      --no-cli-pager > /dev/null

    echo "✓ Lambda関数設定更新完了"

    echo "Lambda関数設定更新の完了待機中..."
    aws lambda wait function-updated \
      --function-name ${FUNCTION_NAME} \
      --region ${REGION}

else
    if grep -q "ResourceNotFoundException" "${GET_FUNCTION_ERROR}"; then
        echo "Lambda関数が存在しません。新規作成します..."
    else
        echo "❌ Lambda関数の存在確認に失敗しました"
        echo ""
        cat "${GET_FUNCTION_ERROR}"
        echo ""
        echo "AWSアカウント、リージョン、認証情報、lambda:GetFunction 権限を確認してください。"
        echo "確認コマンド:"
        echo "  aws sts get-caller-identity"
        echo "  aws lambda get-function --function-name ${FUNCTION_NAME} --region ${REGION}"
        rm -f "${GET_FUNCTION_ERROR}"
        exit 1
    fi

    # IAMロールARNのチェック
    if [ -z "$ROLE_ARN" ]; then
        echo "❌ エラー: LAMBDA_ROLE_ARN 環境変数が設定されていません"
        echo ""
        echo "IAMロールARNを設定してください:"
        echo "  export LAMBDA_ROLE_ARN=arn:aws:iam::YOUR_ACCOUNT_ID:role/lambda-execution-role"
        echo ""
        echo "または、AWS Management ConsoleでIAMロールを作成し、ARNを取得してください"
        exit 1
    fi

    # Lambda関数を作成
    aws lambda create-function \
      --function-name ${FUNCTION_NAME} \
      --runtime ${RUNTIME} \
      --role ${ROLE_ARN} \
      --handler ${HANDLER} \
      --timeout ${TIMEOUT} \
      --memory-size ${MEMORY} \
      --layers ${LAYER_ARN} \
      --zip-file fileb://lambda-function.zip \
      --environment "Variables={S3_BUCKET_NAME=${S3_BUCKET},TZ=Asia/Tokyo}" \
      --region ${REGION} \
      --no-cli-pager > /dev/null

    echo "✓ Lambda関数作成完了"
fi

rm -f "${GET_FUNCTION_ERROR}"

echo ""
echo "=== デプロイ完了 ==="
echo "✓ Lambda関数名: ${FUNCTION_NAME}"
echo "✓ Lambda Layer ARN: ${LAYER_ARN}"
echo "✓ リージョン: ${REGION}"
echo ""
echo "次のステップ:"
echo "  1. Lambda関数をテスト実行:"
echo "     aws lambda invoke \\"
echo "       --function-name ${FUNCTION_NAME} \\"
echo "       --region ${REGION} \\"
echo "       output.json"
echo ""
echo "  2. EventBridgeスケジュールを設定（毎日0:00 UTC = 9:00 JST）:"
echo "     aws events put-rule \\"
echo "       --name claude-news-analyzer-daily \\"
echo "       --schedule-expression 'cron(0 0 * * ? *)' \\"
echo "       --region ${REGION}"
echo ""
echo "     LAMBDA_ARN=\"arn:aws:lambda:${REGION}:YOUR_ACCOUNT_ID:function:${FUNCTION_NAME}\""
echo "     cat > /tmp/claude-news-analyzer-daily-target.json <<EOF"
echo "     ["
echo "       {"
echo "         \"Id\": \"1\","
echo "         \"Arn\": \"\${LAMBDA_ARN}\","
echo "         \"Input\": \"{\\\"analysis_type\\\":\\\"daily\\\"}\""
echo "       }"
echo "     ]"
echo "     EOF"
echo ""
echo "     aws events put-targets \\"
echo "       --rule claude-news-analyzer-daily \\"
echo "       --targets file:///tmp/claude-news-analyzer-daily-target.json \\"
echo "       --region ${REGION}"
echo ""
echo "     週次・月次・四半期も同じ file JSON 方式で targets ファイルを作成してください。"
echo "     詳細は LAMBDA_DEPLOYMENT.md の EventBridge スケジュール手順を参照してください。"
echo "     shorthand 形式はシェル引用や JSON エスケープで失敗しやすいため避けます。"
