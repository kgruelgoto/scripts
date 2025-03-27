#!/bin/bash

PROFILE=${1:-default}
CREDS_LOCATION=~/.aws/credentials

aws sso login --profile "$PROFILE"
CREDS=$(aws configure export-credentials --profile "$PROFILE" | jq -r '. | "[default]\naws_access_key_id=\(.AccessKeyId)\naws_secret_access_key=\(.SecretAccessKey)\naws_session_token=\(.SessionToken)"')
echo -e "$CREDS" > $CREDS_LOCATION

AWS_ACCESS_KEY_ID=$(echo "$CREDS" | grep 'aws_access_key_id' | cut -d'=' -f2)
AWS_SECRET_ACCESS_KEY=$(echo "$CREDS" | grep 'aws_secret_access_key' | cut -d'=' -f2)
AWS_SESSION_TOKEN=$(echo "$CREDS" | grep 'aws_session_token' | cut -d'=' -f2)
export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
export AWS_SESSION_TOKEN=$AWS_SESSION_TOKEN

echo "AWS credentials for $PROFILE set in $CREDS_LOCATION and as environment variables."