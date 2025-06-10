#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "click",
#     "requests",
# ]
# ///

import csv
import sys
from typing import Optional, List

import click
import requests


class AccountServiceClient:
    def __init__(self, base_url: str, client_name: str, client_secret: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "ClientName": client_name,
            "ClientSecret": client_secret,
            "Content-Type": "application/json",
        }

    def get_user_by_email(self, email: str) -> Optional[dict]:
        """Get user by email address"""
        try:
            response = requests.get(
                f"{self.base_url}/users", params={"email": email}, headers=self.headers
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            else:
                response.raise_for_status()
        except requests.exceptions.RequestException as e:
            click.echo(f"Error looking up user with email {email}: {e}", err=True)
            return None

    def remove_user_from_organization(self, org_key: str, user_key: str) -> bool:
        """Remove a user from an organization"""
        try:
            response = requests.delete(
                f"{self.base_url}/organizations/{org_key}/users/{user_key}",
                headers=self.headers,
            )

            if response.status_code == 204:
                return True
            else:
                response.raise_for_status()
        except requests.exceptions.RequestException as e:
            click.echo(
                f"Error removing user {user_key} from organization {org_key}: {e}",
                err=True,
            )
            return False


@click.command()
@click.option("--base-url", required=True, help="Base URL for Account Service API")
@click.option("--client-name", required=True, help="Client name for authentication")
@click.option("--client-secret", required=True, help="Client secret for authentication")
@click.option("--org-key", required=True, help="Organization key to remove users from")
@click.option(
    "--csv-file", required=True, help="CSV file with email addresses (use - for stdin)"
)
@click.option(
    "--email-column", default="email", help="Column name containing email addresses"
)
@click.option(
    "--dry-run", is_flag=True, help="Perform a dry run without making changes"
)
def main(
    base_url: str,
    client_name: str,
    client_secret: str,
    org_key: str,
    csv_file: str,
    email_column: str,
    dry_run: bool,
):
    """
    Remove users from an organization based on a CSV of email addresses.

    This script reads email addresses from a CSV file, looks up each user's key,
    and removes them from the specified organization.
    """
    client = AccountServiceClient(base_url, client_name, client_secret)

    # Stats counters
    total_emails = 0
    users_found = 0
    users_removed = 0
    users_not_found = 0

    click.echo(f"{'DRY RUN: ' if dry_run else ''}Processing CSV file: {csv_file}")

    try:
        if csv_file == "-" or csv_file == "/dev/stdin":
            f = sys.stdin
            # If running interactively, prompt for input
            if sys.stdin.isatty():
                click.echo(
                    "Reading CSV data from stdin. Press Ctrl-D (Unix) or Ctrl-Z (Windows) to end input."
                )
        else:
            f = open(csv_file, "r", newline="", encoding="utf-8")
        with f:
            reader = csv.DictReader(f)
            # Verify email column exists
            if not reader.fieldnames or email_column not in reader.fieldnames:
                click.echo(
                    f"Error: Column '{email_column}' not found in CSV. Available columns: {', '.join(reader.fieldnames or [])}",
                    err=True,
                )
                sys.exit(1)
            for row in reader:
                total_emails += 1
                email = row[email_column].strip()
                if not email:
                    click.echo(
                        f"Warning: Empty email found in row {total_emails}, skipping"
                    )
                    continue
                # Look up user by email
                user = client.get_user_by_email(email)
                if user:
                    users_found += 1
                    user_key = user["key"]
                    click.echo(f"Found user: {email} (key: {user_key})")
                    # Remove user from organization
                    if not dry_run:
                        success = client.remove_user_from_organization(
                            org_key, user_key
                        )
                        if success:
                            users_removed += 1
                            click.echo(
                                f"Removed user {email} from organization {org_key}"
                            )
                        else:
                            click.echo(
                                f"Failed to remove user {email} from organization {org_key}"
                            )
                    else:
                        click.echo(
                            f"DRY RUN: Would remove user {email} from organization {org_key}"
                        )
                        users_removed += 1
                else:
                    users_not_found += 1
                    click.echo(f"User not found: {email}")
    except Exception as e:
        click.echo(f"Error processing CSV file: {e}", err=True)
        sys.exit(1)

    # Print summary
    click.echo("\nSummary:")
    click.echo(f"Total emails processed: {total_emails}")
    click.echo(f"Users found: {users_found}")
    click.echo(f"Users not found: {users_not_found}")
    click.echo(
        f"Users {'that would be' if dry_run else ''} removed from organization: {users_removed}"
    )

    if dry_run:
        click.echo("\nThis was a dry run. No changes were made.")


if __name__ == "__main__":
    main()
