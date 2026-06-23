PYTHON ?= python3.11
VENV ?= .venv
AWS_REGION ?= ap-northeast-1
S3_BUCKET_NAME ?= claude-news-analyzer
LAMBDA_FUNCTION_NAME ?= claude-news-analyzer
TF_DIR ?= infra/terraform
CLOUDFRONT_DISTRIBUTION_ID ?=
PUBLIC_HTML_PREFIX ?= public
PATHS ?= /*
FUNCTION_BUILD_DIR ?= .lambda-build/function

.PHONY: setup test package-function package-layer tf-init tf-plan tf-apply tf-fmt tf-validate upload-config publish-existing-html cf-invalidate invoke-daily clean-build

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements.txt

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

package-function:
	rm -f lambda-function.zip
	rm -rf $(FUNCTION_BUILD_DIR)
	mkdir -p $(FUNCTION_BUILD_DIR)
	cp -R src/bedrock_news_analyzer $(FUNCTION_BUILD_DIR)/bedrock_news_analyzer
	find $(FUNCTION_BUILD_DIR) -type d -name __pycache__ -prune -exec rm -rf {} +
	cd $(FUNCTION_BUILD_DIR) && zip -r ../../lambda-function.zip bedrock_news_analyzer -q
	ls -lh lambda-function.zip

package-layer:
	./deploy/build_layer.sh

tf-init:
	terraform -chdir=$(TF_DIR) init

tf-plan:
	terraform -chdir=$(TF_DIR) plan

tf-apply:
	terraform -chdir=$(TF_DIR) apply

tf-fmt:
	terraform fmt -recursive $(TF_DIR)

tf-validate:
	terraform -chdir=$(TF_DIR) validate

upload-config:
	aws s3 cp config/config.json s3://$(S3_BUCKET_NAME)/config/config.json --region $(AWS_REGION)
	aws s3 cp config/news_analysis_prompt.txt s3://$(S3_BUCKET_NAME)/config/news_analysis_prompt.txt --region $(AWS_REGION)
	aws s3 cp config/weekly_news_analysis_prompt.txt s3://$(S3_BUCKET_NAME)/config/weekly_news_analysis_prompt.txt --region $(AWS_REGION)
	aws s3 cp config/monthly_news_analysis_prompt.txt s3://$(S3_BUCKET_NAME)/config/monthly_news_analysis_prompt.txt --region $(AWS_REGION)
	aws s3 cp config/quarterly_news_analysis_prompt.txt s3://$(S3_BUCKET_NAME)/config/quarterly_news_analysis_prompt.txt --region $(AWS_REGION)

publish-existing-html:
	aws s3 sync s3://$(S3_BUCKET_NAME)/daily/ s3://$(S3_BUCKET_NAME)/$(PUBLIC_HTML_PREFIX)/daily/ --exclude "*" --include "*.html" --region $(AWS_REGION)
	aws s3 sync s3://$(S3_BUCKET_NAME)/weekly/ s3://$(S3_BUCKET_NAME)/$(PUBLIC_HTML_PREFIX)/weekly/ --exclude "*" --include "*.html" --region $(AWS_REGION)
	aws s3 sync s3://$(S3_BUCKET_NAME)/monthly/ s3://$(S3_BUCKET_NAME)/$(PUBLIC_HTML_PREFIX)/monthly/ --exclude "*" --include "*.html" --region $(AWS_REGION)
	aws s3 sync s3://$(S3_BUCKET_NAME)/quarterly/ s3://$(S3_BUCKET_NAME)/$(PUBLIC_HTML_PREFIX)/quarterly/ --exclude "*" --include "*.html" --region $(AWS_REGION)

cf-invalidate:
	test -n "$(CLOUDFRONT_DISTRIBUTION_ID)"
	aws cloudfront create-invalidation --distribution-id $(CLOUDFRONT_DISTRIBUTION_ID) --paths "$(PATHS)"

invoke-daily:
	AWS_MAX_ATTEMPTS=1 aws lambda invoke \
		--function-name $(LAMBDA_FUNCTION_NAME) \
		--region $(AWS_REGION) \
		--cli-read-timeout 900 \
		--cli-connect-timeout 10 \
		--cli-binary-format raw-in-base64-out \
		--payload '{"analysis_type":"daily"}' \
		output-daily.json
	cat output-daily.json

clean-build:
	rm -f lambda-function.zip lambda-layer.zip output*.json
	rm -rf layer .lambda-build
