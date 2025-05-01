#!/usr/bin/env python
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "httpx",  # For making HTTP requests
#     "click",  # For creating a command-line interface
# ]
# ///

"""
Compares licenses between Stage and Live environments to find missing userkeys,
then assigns those users to the corresponding licenses in Live.

Uses the Account Service API endpoints:
- GET /accounts/{accountKey}/users to validate users exist in Live
- GET /accounts/{accountKeys}/licenses to fetch license data
- POST /licenses/{licenseKey}/users to assign users to licenses
"""

import json
import sys
import time
from typing import List, Tuple, Any, Dict, Set

import click
import httpx

# --- Configuration ---
STAGE_BASE_URL: str = "https://accsvcstageuswest2.servers.getgo.com/v2"
LIVE_BASE_URL: str = "https://accsvcuswest2.servers.getgo.com/v2"

# Client credentials to be provided at runtime
STAGE_CLIENT_NAME: str = ""
STAGE_CLIENT_SECRET: str = ""
LIVE_CLIENT_NAME: str = ""
LIVE_CLIENT_SECRET: str = ""

# --- Constants ---
DEFAULT_TIMEOUT = 30.0  # seconds for API requests

# --- Helper Functions ---


def fetch_account_users(
    client: httpx.Client, base_url: str, account_key: str
) -> Set[int]:
    """
    Fetches users for a specific account and returns a set of user keys.

    Args:
        client: The httpx client with authentication headers
        base_url: The base URL for the API
        account_key: Account key to fetch users for

    Returns:
        Set of user keys that exist in the account
    """
    url = f"{base_url.rstrip('/')}/accounts/{account_key}/users"
    params = {"ids": "false"}

    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        users = response.json()

        if not isinstance(users, list):
            raise ValueError(f"Expected list of users but got {type(users)}")

        # Extract user keys into a set for efficient lookup
        user_keys = set()
        for user in users:
            if isinstance(user, dict) and "key" in user:
                try:
                    user_keys.add(int(user["key"]))
                except (ValueError, TypeError) as e:
                    click.echo(
                        f"Warning: Skipping user with invalid key format: {user.get('key')} ({e})",
                        err=True,
                    )

        return user_keys

    except httpx.HTTPStatusError as e:
        err_body = ""
        try:
            err_body = e.response.json()
        except json.JSONDecodeError:
            err_body = e.response.text

        status = e.response.status_code
        if status == 404:
            raise click.ClickException(f"Account not found. Details: {err_body}")
        elif status in (401, 403):
            raise click.ClickException(
                f"Authentication failed. Check credentials. Details: {err_body}"
            )
        else:
            raise click.ClickException(f"HTTP Error {status}: {err_body}")

    except httpx.RequestError as e:
        raise click.ClickException(f"Network/Request Error: {e}")
    except Exception as e:
        raise click.ClickException(f"Unexpected error fetching users: {e}")


def fetch_licenses(
    client: httpx.Client, base_url: str, account_keys: List[str]
) -> List[dict]:
    """
    Fetches licenses for the given account keys using the Account Service API.

    Args:
        client: The httpx client with authentication headers
        base_url: The base URL for the API
        account_keys: List of account keys to fetch licenses for

    Returns:
        List of license objects containing key and userkeys
    """
    # Join account keys with commas for the API request
    account_keys_str = ",".join(map(str, account_keys))
    url = f"{base_url.rstrip('/')}/accounts/{account_keys_str}/licenses"

    try:
        response = client.get(
            url,
        )
        response.raise_for_status()
        licenses = response.json()

        if not isinstance(licenses, list):
            raise ValueError(f"Expected list of licenses but got {type(licenses)}")

        return licenses

    except httpx.HTTPStatusError as e:
        err_body = ""
        try:
            err_body = e.response.json()
        except json.JSONDecodeError:
            err_body = e.response.text

        status = e.response.status_code
        if status == 404:
            raise click.ClickException(f"Account(s) not found. Details: {err_body}")
        elif status in (401, 403):
            raise click.ClickException(
                f"Authentication failed. Check credentials. Details: {err_body}"
            )
        else:
            raise click.ClickException(f"HTTP Error {status}: {err_body}")

    except httpx.RequestError as e:
        raise click.ClickException(f"Network/Request Error: {e}")
    except Exception as e:
        raise click.ClickException(f"Unexpected error fetching licenses: {e}")


def find_missing_userkeys(
    live_client: httpx.Client,
    stage_client: httpx.Client,
    account_key: str,
    verbose: bool = False,
) -> Tuple[List[Tuple[Any, List[Any]]], int]:
    """
    Compares licenses between Stage and Live environments to find userkeys
    present in Stage but missing in Live for matching license keys.
    Only includes users that exist in the Live account.

    Args:
        live_client: httpx client configured for Live environment
        stage_client: httpx client configured for Stage environment
        account_key: Account key to check
        verbose: Whether to print detailed progress messages

    Returns:
        Tuple of (list of (license_key, missing_userkeys_list), count of skipped users)
    """
    results = []
    skipped_users_count = 0

    # First, fetch all users from Live account to validate against
    click.echo("Fetching users from Live account...")
    try:
        live_users = fetch_account_users(live_client, LIVE_BASE_URL, account_key)
        click.echo(f"Found {len(live_users)} users in Live account")
    except click.ClickException as e:
        click.echo(f"Error fetching Live users: {e}", err=True)
        sys.exit(1)

    # Fetch license data from both environments
    try:
        live_data = fetch_licenses(live_client, LIVE_BASE_URL, [account_key])
        stage_data = fetch_licenses(stage_client, STAGE_BASE_URL, [account_key])
    except click.ClickException as e:
        click.echo(f"Error fetching licenses: {e}", err=True)
        sys.exit(1)

    # Create dictionaries mapping 'key' to the set of 'userkeys' for faster comparison
    live_userkeys_map: Dict[str, Set[int]] = {}
    for item in live_data:
        if isinstance(item, dict) and "key" in item and "userkeys" in item:
            ukeys = item.get("userkeys", [])
            if isinstance(ukeys, list):
                try:
                    live_userkeys_map[str(item["key"])] = set(int(k) for k in ukeys)
                except (ValueError, TypeError) as e:
                    click.echo(
                        f"Warning: Skipping Live item with key '{item['key']}' due to non-integer userkey: {e}",
                        err=True,
                    )
            else:
                click.echo(
                    f"Warning: Skipping Live item with key '{item['key']}' because 'userkeys' is not a list.",
                    err=True,
                )

    stage_userkeys_map: Dict[str, Set[int]] = {}
    for item in stage_data:
        if isinstance(item, dict) and "key" in item and "userkeys" in item:
            ukeys = item.get("userkeys", [])
            if isinstance(ukeys, list):
                try:
                    stage_userkeys_map[str(item["key"])] = set(int(k) for k in ukeys)
                except (ValueError, TypeError) as e:
                    click.echo(
                        f"Warning: Skipping Stage item with key '{item['key']}' due to non-integer userkey: {e}",
                        err=True,
                    )
            else:
                click.echo(
                    f"Warning: Skipping Stage item with key '{item['key']}' because 'userkeys' is not a list.",
                    err=True,
                )

    # Find differences and validate users exist in Live
    for key, stage_keys_set in stage_userkeys_map.items():
        if key in live_userkeys_map:
            live_keys_set = live_userkeys_map[key]
            # Calculate difference: keys in stage but not in live
            missing_keys = stage_keys_set - live_keys_set

            if missing_keys:
                # Filter out users that don't exist in Live account
                valid_missing_keys = [k for k in missing_keys if k in live_users]
                skipped_users = missing_keys - set(valid_missing_keys)
                skipped_users_count += len(skipped_users)

                if skipped_users and verbose:
                    click.echo(
                        f"Warning: Skipping {len(skipped_users)} users for license '{key}' - users do not exist in Live account",
                        err=True,
                    )

                if valid_missing_keys:  # Only add if there are valid missing keys
                    # Convert set back to a sorted list for consistent output
                    results.append((key, sorted(valid_missing_keys)))

    return results, skipped_users_count


def add_users_to_license(
    client: httpx.Client, base_url: str, license_key: Any, user_keys: List[Any]
) -> Tuple[bool, str]:
    """Makes the API call to add users to a license, chunking users into groups of 999 max."""
    if not user_keys:
        return True, "Skipped - No users to add."

    # Define chunk size (stay under 1000)
    CHUNK_SIZE = 999
    total_users = len(user_keys)
    chunks = [user_keys[i : i + CHUNK_SIZE] for i in range(0, total_users, CHUNK_SIZE)]

    success_count = 0
    failure_messages = []

    for i, chunk in enumerate(chunks):
        url = f"{base_url.rstrip('/')}/licenses/{license_key}/users"
        try:
            response = client.post(url, json=chunk)
            response.raise_for_status()  # Raises HTTPStatusError for 4xx/5xx responses
            # Account Service returns 204 No Content on success for this endpoint
            if response.status_code == 204:
                success_count += len(chunk)
            else:
                # Should technically not happen if raise_for_status() is used, but defensive
                failure_messages.append(
                    f"Chunk {i+1}: Unexpected Status: {response.status_code} Body: {response.text}"
                )

        except httpx.HTTPStatusError as e:
            # More specific error handling based on Account Service documentation
            err_body = ""
            try:
                err_body = e.response.json()  # Try to get JSON error details
            except json.JSONDecodeError:
                err_body = e.response.text  # Fallback to raw text

            status = e.response.status_code
            if status == 404:
                # Could be license or one/more users not found, or mismatch account
                msg = f"Chunk {i+1}: Error 404: Not Found. License '{license_key}' or one/more users not found, or user/license account mismatch. Details: {err_body}"
            elif status == 409:
                msg = f"Chunk {i+1}: Error 409: Conflict. One or more users might already be licensed. Details: {err_body}"
            elif status == 422:
                msg = f"Chunk {i+1}: Error 422: Unprocessable. Insufficient seats on license '{license_key}'? Details: {err_body}"
            elif status == 400:
                msg = f"Chunk {i+1}: Error 400: Bad Request. Invalid user key format or list too long? Details: {err_body}"
            elif status == 401 or status == 403:
                msg = f"Chunk {i+1}: Error {status}: Authentication/Authorization Failed. Check ClientName/ClientSecret. Details: {err_body}"
            else:
                msg = f"Chunk {i+1}: HTTP Error {status}: {e}. Details: {err_body}"
            failure_messages.append(msg)
        except httpx.RequestError as e:
            failure_messages.append(f"Chunk {i+1}: Network/Request Error: {e}")
        except Exception as e:
            failure_messages.append(
                f"Chunk {i+1}: Unexpected Error during API call: {e}"
            )

    # Determine overall success or failure
    if success_count == total_users:
        return True, f"Success ({total_users} users in {len(chunks)} chunks)"
    elif success_count > 0:
        return (
            False,
            f"Partial success: {success_count}/{total_users} users added. Errors: {'; '.join(failure_messages)}",
        )
    else:
        return (
            False,
            f"Complete failure: 0/{total_users} users added. Errors: {'; '.join(failure_messages)}",
        )


# --- CLI Definition ---


@click.command()
@click.option(
    "--account-key",
    required=True,
    help="Account key to process.",
)
@click.option(
    "--stage-client-name",
    required=True,
    help="Stage environment Client Name for authentication.",
)
@click.option(
    "--stage-client-secret",
    required=True,
    help="Stage environment Client Secret for authentication.",
)
@click.option(
    "--live-client-name",
    required=True,
    help="Live environment Client Name for authentication.",
)
@click.option(
    "--live-client-secret",
    required=True,
    help="Live environment Client Secret for authentication.",
)
@click.option(
    "--stage-base-url",
    default=STAGE_BASE_URL,
    show_default=True,
    help="Stage environment base URL.",
)
@click.option(
    "--live-base-url",
    default=LIVE_BASE_URL,
    show_default=True,
    help="Live environment base URL.",
)
@click.option(
    "--timeout",
    default=DEFAULT_TIMEOUT,
    type=float,
    show_default=True,
    help="HTTP request timeout in seconds.",
)
@click.option(
    "--delay",
    default=0.1,
    type=float,
    show_default=True,
    help="Delay in seconds between API calls to avoid rate limiting.",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    help="Print success messages in addition to errors.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Only show what would be done without making changes.",
)
def main(
    account_key: str,
    stage_client_name: str,
    stage_client_secret: str,
    live_client_name: str,
    live_client_secret: str,
    stage_base_url: str,
    live_base_url: str,
    timeout: float,
    delay: float,
    verbose: bool,
    dry_run: bool,
):
    """
    Compares licenses between Stage and Live environments, finds missing userkeys,
    validates users exist in Live account, and assigns those users to the corresponding
    licenses in Live.
    """
    # Set up clients for both environments
    stage_headers = {
        "ClientName": stage_client_name,
        "ClientSecret": stage_client_secret,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    live_headers = {
        "ClientName": live_client_name,
        "ClientSecret": live_client_secret,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Create clients for both environments
    with httpx.Client(
        headers=stage_headers, timeout=timeout
    ) as stage_client, httpx.Client(
        headers=live_headers, timeout=timeout
    ) as live_client:

        click.echo("Finding and validating missing userkeys between Stage and Live...")
        missing_userkeys, skipped_users = find_missing_userkeys(
            live_client, stage_client, account_key, verbose
        )

        if not missing_userkeys:
            click.echo("No valid missing userkeys found between Stage and Live.")
            if skipped_users > 0:
                click.echo(
                    click.style(
                        f"Note: {skipped_users} users were skipped because they don't exist in Live account",
                        fg="yellow",
                    )
                )
            return

        click.echo(
            f"\nFound {len(missing_userkeys)} licenses with valid missing userkeys:"
        )
        total_users = sum(len(users) for _, users in missing_userkeys)
        for license_key, user_keys in missing_userkeys:
            click.echo(f"License {license_key}: {len(user_keys)} missing users")

        if skipped_users > 0:
            click.echo(
                click.style(
                    f"\nNote: {skipped_users} users were skipped because they don't exist in Live account",
                    fg="yellow",
                )
            )

        if dry_run:
            click.echo("\nDRY RUN - No changes will be made")
            return

        if not click.confirm("\nProceed with assigning users to licenses in Live?"):
            click.echo("Operation cancelled.")
            return

        success_count = 0
        failure_count = 0
        skipped_count = 0

        click.echo("\nStarting user assignments...")
        with click.progressbar(
            missing_userkeys,
            label="Assigning users",
            item_show_func=lambda item: (
                f"License {item[0] if item else '?'}" if item else ""
            ),
        ) as bar:
            for license_key, user_keys in bar:
                if not user_keys:
                    skipped_count += 1
                    if verbose:
                        click.echo(
                            f"\nLicense {license_key}: Skipped - No users to add"
                        )
                    time.sleep(delay)
                    continue

                success, message = add_users_to_license(
                    live_client, live_base_url, license_key, user_keys
                )

                if success:
                    success_count += 1
                    if verbose and "Skipped" not in message:
                        click.echo(f"\nLicense {license_key}: {message}")
                    elif "Skipped" in message:
                        skipped_count += 1
                        if verbose:
                            click.echo(f"\nLicense {license_key}: {message}")
                else:
                    failure_count += 1
                    click.echo(f"\nLicense {license_key}: Failed! {message}", err=True)

                time.sleep(delay)

        # --- Summary ---
        click.echo("\n--- Processing Complete ---")
        click.echo(f"Total licenses processed: {len(missing_userkeys)}")
        click.echo(f"Total users processed: {total_users}")
        click.echo(click.style(f"Successful assignments: {success_count}", fg="green"))
        click.echo(
            click.style(f"Skipped (no users to add): {skipped_count}", fg="yellow")
        )
        if skipped_users > 0:
            click.echo(
                click.style(
                    f"Users skipped (not in Live): {skipped_users}", fg="yellow"
                )
            )
        click.echo(click.style(f"Failed assignments: {failure_count}", fg="red"))
        click.echo("--------------------------")

        if failure_count > 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
