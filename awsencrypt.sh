#!/bin/bash
PLAINTEXT=$1
PROFILE=${2:-default}
FORMAT=${3:-json}
aws kms encrypt --key-id alias/identityplatform --profile "$PROFILE" --plaintext "$PLAINTEXT" --output "$FORMAT" --query CiphertextBlob --cli-binary-format raw-in-base64-out