#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "click",
#     "boto3",
#     "tabulate",
# ]
# ///
"""
S3 Inventory Report Tool
This script generates a report from an S3 Inventory manifest for a given bucket.
"""
import sys
import os
import json
import gzip
import csv
import click
import boto3
from tabulate import tabulate
from botocore.exceptions import ClientError

def get_latest_inventory_manifest(s3_client, bucket, inventory_prefix):
    """Fetch the latest inventory manifest file from the given prefix, with progress feedback and periodic updates."""
    paginator = s3_client.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=bucket, Prefix=inventory_prefix)
    manifests = []
    file_count = 0
    click.echo("Searching for manifest.json files in S3 Inventory prefix...")
    for page in pages:
        for obj in page.get('Contents', []):
            file_count += 1
            if file_count % 1000 == 0:
                click.echo(f"Scanned {file_count} objects so far...")
            if obj['Key'].endswith('manifest.json'):
                manifests.append(obj['Key'])
    click.echo(f"Scanned {file_count} objects. Found {len(manifests)} manifest.json files.")
    if not manifests:
        raise RuntimeError("No manifest.json found in the specified prefix.")
    return sorted(manifests)[-1]

def download_and_parse_manifest(s3_client, bucket, manifest_key):
    """Download and parse the manifest.json file."""
    obj = s3_client.get_object(Bucket=bucket, Key=manifest_key)
    manifest = json.loads(obj['Body'].read())
    return manifest

def download_and_parse_inventory_csv(s3_client, bucket, key):
    """Download and parse a gzipped CSV inventory file."""
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    with gzip.GzipFile(fileobj=obj['Body']) as gz:
        reader = csv.reader(line.decode() for line in gz)
        return list(reader)

import csv as pycsv
def scan_s3_objects_to_csv(s3_client, bucket, prefix, output_file):
    """Scan all S3 objects under a prefix and write key metadata to a CSV file, updating progress in place."""
    paginator = s3_client.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
    file_count = 0
    with open(output_file, "w", newline="") as f:
        writer = pycsv.writer(f)
        writer.writerow(["Key", "Size", "LastModified", "StorageClass"])
        click.echo("Scanning S3 objects and writing to CSV...")
        for page in pages:
            for obj in page.get('Contents', []):
                file_count += 1
                if file_count % 1000 == 0:
                    print(f"\rScanned {file_count} objects so far...", end="", flush=True)
                writer.writerow([
                    obj['Key'],
                    obj.get('Size', ''),
                    obj.get('LastModified', ''),
                    obj.get('StorageClass', '')
                ])
        print(f"\rScanned {file_count} objects. Wrote results to {output_file}.")
    click.echo("")
    return output_file

def save_report_summary(summary, output_file):
    with open(output_file, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    click.echo(f"[INFO] Saved summary report to {output_file}")

@click.command()
@click.option('--bucket', required=True, help='S3 bucket name')
@click.option('--inventory-prefix', required=True, help='Prefix where S3 Inventory is stored')
@click.option('--profile', default=None, help='AWS profile to use')
def main(bucket, inventory_prefix, profile):
    """Generate a report from the latest S3 Inventory manifest, or scan S3 if not found. Save results and summary."""
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    s3 = session.client('s3')
    summary = {
        "bucket": bucket,
        "prefix": inventory_prefix,
        "source": None,
        "object_count": 0,
        "total_size_bytes": 0,
        "report_file": None,
        "sample_rows": [],
    }
    try:
        try:
            manifest_key = get_latest_inventory_manifest(s3, bucket, inventory_prefix)
            click.echo(f"\n[INFO] Using manifest: {manifest_key}")
            manifest = download_and_parse_manifest(s3, bucket, manifest_key)
            if not manifest or 'files' not in manifest or not manifest['files']:
                click.echo("[ERROR] Manifest found, but no inventory files listed.", err=True)
                raise RuntimeError("No inventory files in manifest.")
            csv_files = [f['key'] for f in manifest['files']]
            total_size = sum(f.get('size', 0) for f in manifest['files'])
            click.echo(f"[INFO] Found {len(csv_files)} inventory file(s), total size: {total_size/1024/1024:.2f} MB\n")
            all_rows = []
            headers_printed = False
            with click.progressbar(csv_files, label="Downloading and parsing inventory files") as bar:
                for key in bar:
                    try:
                        rows = download_and_parse_inventory_csv(s3, bucket, key)
                    except Exception as e:
                        click.echo(f"[ERROR] Failed to download or parse {key}: {e}", err=True)
                        continue
                    if not headers_printed and rows:
                        click.echo("[INFO] Sample rows from first inventory file:")
                        click.echo(tabulate([rows[0]] + rows[1:6], headers="firstrow"))
                        summary["sample_rows"] = [rows[0]] + rows[1:6]
                        headers_printed = True
                    all_rows.extend(rows)
            if all_rows:
                output_file = f"s3_inventory_report_{bucket.replace('-', '_')}.csv"
                with open(output_file, "w", newline="") as f:
                    writer = pycsv.writer(f)
                    for row in all_rows:
                        writer.writerow(row)
                click.echo(f"\n[INFO] Saved full inventory data to {output_file}")
                click.echo("\n[INFO] Sample of first 20 rows from all inventory files:")
                click.echo(tabulate(all_rows[:20], headers="firstrow"))
                click.echo(f"[INFO] Total objects in inventory: {len(all_rows)-1}")
                summary["source"] = "inventory"
                summary["object_count"] = len(all_rows) - 1
                summary["total_size_bytes"] = total_size
                summary["report_file"] = output_file
            else:
                click.echo("[WARNING] No inventory data rows found.")
        except Exception as manifest_error:
            click.echo(f"[INFO] No manifest found or error occurred: {manifest_error}")
            # Fallback: scan S3 directly
            output_file = f"s3_inventory_report_{bucket.replace('-', '_')}_live.csv"
            file_count = 0
            total_size = 0
            sample_rows = []
            with open(output_file, "w", newline="") as f:
                writer = pycsv.writer(f)
                writer.writerow(["Key", "Size", "LastModified", "StorageClass"])
                click.echo("Scanning S3 objects and writing to CSV...")
                paginator = s3.get_paginator('list_objects_v2')
                pages = paginator.paginate(Bucket=bucket, Prefix=inventory_prefix)
                for page in pages:
                    for obj in page.get('Contents', []):
                        file_count += 1
                        total_size += obj.get('Size', 0)
                        if file_count <= 6:
                            sample_rows.append([
                                obj['Key'],
                                obj.get('Size', ''),
                                obj.get('LastModified', ''),
                                obj.get('StorageClass', '')
                            ])
                        if file_count % 1000 == 0:
                            print(f"\rScanned {file_count} objects so far...", end="", flush=True)
                        writer.writerow([
                            obj['Key'],
                            obj.get('Size', ''),
                            obj.get('LastModified', ''),
                            obj.get('StorageClass', '')
                        ])
                print(f"\rScanned {file_count} objects. Wrote results to {output_file}.")
            click.echo("")
            click.echo(f"[INFO] Saved full scan data to {output_file}")
            if sample_rows:
                click.echo("[INFO] Sample rows from scan:")
                click.echo(tabulate(sample_rows, headers="firstrow"))
                summary["sample_rows"] = sample_rows
            click.echo(f"[INFO] Total objects in scan: {file_count}")
            summary["source"] = "live_scan"
            summary["object_count"] = file_count
            summary["total_size_bytes"] = total_size
            summary["report_file"] = output_file
        # Save summary JSON
        summary_file = f"s3_inventory_report_{bucket.replace('-', '_')}_summary.json"
        save_report_summary(summary, summary_file)
    except ClientError as e:
        click.echo(f"[AWS ERROR] {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"[ERROR] {e}", err=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
