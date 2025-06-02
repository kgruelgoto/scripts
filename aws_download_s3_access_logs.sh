#!/bin/bash

# =============================
# Script: download-s3_access_logs.sh
# Description: Downloads ALB access logs from S3 bucket based on region and date
# Once you have the load balancer log aggregate, run 
#   awk '($1 == "http" || $1 == "h2" || $1 == "https") { print $14}' 50x_errors_YYYY-MM-DD.txt > 50x_errors_urls_YYYY-MM-DD.txt 
# to extract the urls and then 
#   sort 50x_errors_urls_YYYY-MM-DD.txt > 50x_errors_urls_YYYY-MM-DD.sorted.txt 
# =============================

# Check for required arguments
if [ "$#" -ne 3 ]; then
    echo "Usage: $0 <region> <YYYY/MM/DD> <S3 prefix path>"
    echo "Example: $0 us-east-1 2023/02/25 iam-live-alb-access-logs/AWSLogs/663917429408/elasticloadbalancing"
    exit 1
fi

REGION=$1
DATE=$2
PREFIX=$3

# Configuration (update these as needed)
BUCKET_NAME="getgo-identityplatform-${REGION//-/}"
OUTPUT_FOLDER="alb-logs/$REGION/$DATE"

# Create the output folder if it doesn't exist
echo "Creating output folder..."
mkdir -p "$OUTPUT_FOLDER"

# Build S3 path
S3_PATH="s3://$BUCKET_NAME/$PREFIX/$REGION/$DATE/"
echo $S3_PATH

# Download logs using AWS CLI
echo "Downloading ALB access logs for region: $REGION and date: $DATE..."
aws s3 cp --region "$REGION" "$S3_PATH" "$OUTPUT_FOLDER" --recursive

# Check if the AWS CLI command ran successfully
if [ "$?" -eq 0 ]; then
     echo "Logs downloaded successfully to: $OUTPUT_FOLDER"
 else
     echo "Failed to download logs. Please check your AWS CLI configuration, bucket name, and prefix."
     exit 1
fi

# Extract all .gz files
echo "Extracting downloaded .gz files..."
for file in "$OUTPUT_FOLDER"/*.gz; do
    if [ -f "$file" ]; then
        echo "Extracting file: $file"
        gunzip "$file"  # This will extract and remove the .gz file automatically
        if [ "$?" -eq 0 ]; then
            echo "Successfully extracted: $file"
        else
            echo "Failed to extract: $file. Please check the archive."
            exit 1
        fi
    else
        echo "No .gz files found in $OUTPUT_FOLDER"
    fi
done

echo "Extraction complete. Logs are available in $OUTPUT_FOLDER."

# Step 3: Scan extracted logs for HTTP 50x status codes
echo "Scanning logs for HTTP status codes in the 50x range..."
for log_file in "$OUTPUT_FOLDER"/*; do
    if [ -f "$log_file" ]; then
        # AWK command to extract and print 50x lines
        MATCHING_LINES=$(awk '{if ($9 ~ /^50[0-9]$/) print $0}' "$log_file")
        if [ ! -z "$MATCHING_LINES" ]; then
            echo "File with 50x HTTP codes: $log_file"
            echo "$MATCHING_LINES"
            echo "---------------------------------------------------"
        fi
    fi
done

exit 0