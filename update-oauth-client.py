# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "click",
#   "httpx",
#   "httpx-auth",
#   "deepdiff"
# ]
# ///

import click
import httpx
import json
import time
import base64
from deepdiff import DeepDiff
from typing import Dict, Any

BASE_URL = {
    "ed1": "https://identity.ed1.goto.com",
    "rc1": "https://identity.rc1.goto.com",
    "stage": "https://identity.stage.goto.com",
    "live": "https://identity.goto.com",
}


def format_diff_output(diff: Dict[str, Any]) -> str:
    """Format DeepDiff output to be more user-friendly."""
    if not diff:
        return "No differences found."

    formatted_output = []

    # Handle values that were changed
    if "values_changed" in diff:
        formatted_output.append("\n🔄 CHANGED VALUES:")
        for path, change in diff["values_changed"].items():
            # Clean up the path for display
            clean_path = path.replace("root", "").replace("['", "").replace("']", "")
            formatted_output.append(f"  • {clean_path}:")
            formatted_output.append(f"      FROM: {change['old_value']}")
            formatted_output.append(f"      TO:   {change['new_value']}")

    # Handle items that were added
    if "dictionary_item_added" in diff:
        formatted_output.append("\n➕ ADDED ITEMS:")
        for path in diff["dictionary_item_added"]:
            clean_path = path.replace("root", "").replace("['", "").replace("']", "")
            formatted_output.append(f"  • {clean_path}")

    # Handle items that were removed
    if "dictionary_item_removed" in diff:
        formatted_output.append("\n➖ REMOVED ITEMS:")
        for path in diff["dictionary_item_removed"]:
            clean_path = path.replace("root", "").replace("['", "").replace("']", "")
            formatted_output.append(f"  • {clean_path}")

    # Handle lists that were changed
    if "iterable_item_added" in diff:
        formatted_output.append("\n📋 ADDED TO LISTS:")
        for path, value in diff["iterable_item_added"].items():
            clean_path = path.replace("root", "").replace("['", "").replace("']", "")
            formatted_output.append(f"  • {clean_path}: {value}")

    if "iterable_item_removed" in diff:
        formatted_output.append("\n📋 REMOVED FROM LISTS:")
        for path, value in diff["iterable_item_removed"].items():
            clean_path = path.replace("root", "").replace("['", "").replace("']", "")
            formatted_output.append(f"  • {clean_path}: {value}")

    return "\n".join(formatted_output)


@click.command()
@click.option("--username", required=True, help="Your OAuth username.")
@click.option("--password", required=True, help="Your OAuth password.")
@click.option(
    "--env",
    required=True,
    type=click.Choice(["ed1", "rc1", "stage", "live"], case_sensitive=False),
    help="Deployment environment.",
)
@click.option("--client_id", required=True, help="The client ID to authenticate with.")
@click.option(
    "--client_secret", required=True, help="The client secret to authenticate with."
)
@click.option("--scopes", default=None, help="Comma-separated list of scopes.")
@click.option(
    "--grant_types", default=None, help="Comma-separated list of grant types."
)
@click.option("--roles", default=None, help="Comma-separated list of roles.")
@click.option(
    "--implicit_scopes", default=None, help="Comma-separated list of implicit scopes."
)
@click.option("--update_client_id", required=True, help="The client ID to update.")
@click.option("--update_data", default=None, type=click.File("r"))
@click.option(
    "--show-full-json", is_flag=True, help="Show full JSON of before/after client state"
)
def update_client(
    username,
    password,
    client_id,
    client_secret,
    env,
    scopes=None,
    grant_types=None,
    roles=None,
    implicit_scopes=None,
    update_client_id=None,
    update_data=None,
    show_full_json=False,
):
    """Authenticate and update an existing client."""

    # Check required parameters
    if env not in BASE_URL:
        click.echo(f"Invalid env specified: {env}")
        return

    # Set the correct URLs based on the environment
    oauth_token_url = f"{BASE_URL[env]}/oauth/token"
    portal_service_url = f"{BASE_URL[env]}/oauthportal"

    click.echo(f"Using environment: {env}")
    click.echo(f"Token URL: {oauth_token_url}")
    click.echo(f"Portal Service URL: {portal_service_url}")

    # Step 1: Directly get token using client credentials/password grant
    click.echo(f"Authenticating as {username} with client {client_id}...")

    # Create Basic Auth header for token request
    auth_str = f"{client_id}:{client_secret}"
    basic_auth = base64.b64encode(auth_str.encode()).decode()

    headers = {
        "Authorization": f"Basic {basic_auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {"grant_type": "password", "username": username, "password": password}

    with httpx.Client(timeout=30.0) as client:
        try:
            # Get token
            token_response = client.post(oauth_token_url, headers=headers, data=data)

            # Check for errors
            if token_response.status_code != 200:
                click.echo(f"Failed to get token. Status: {token_response.status_code}")
                click.echo(f"Response: {token_response.text}")
                return

            token_data = token_response.json()
            access_token = token_data.get("access_token")

            if not access_token:
                click.echo("No access token in response")
                click.echo(f"Response: {token_data}")
                return

            click.echo("Successfully obtained access token")

            # Set authorization header for subsequent requests
            auth_headers = {"Authorization": f"Bearer {access_token}"}

            # Prepare the update request data
            update_request_data = {}

            if scopes:
                update_request_data["scopes"] = scopes.split(",")
            if grant_types:
                update_request_data["grants"] = grant_types.split(",")
            if roles:
                update_request_data["roles"] = roles.split(",")
            if implicit_scopes:
                update_request_data["implicitScopes"] = implicit_scopes.split(",")

            # Load update data from the provided file
            if update_data:
                update_data_json = json.load(update_data)
                update_request_data.update(update_data_json)

            if not update_request_data:
                click.echo(
                    "No update data provided. Please specify at least one field to update."
                )
                return

            click.echo(f"Update data: {json.dumps(update_request_data, indent=2)}")

            # Retrieve the existing client before the update
            click.echo(f"Retrieving client {update_client_id}...")

            try:
                existing_client_url = f"{portal_service_url}/clients/{update_client_id}"
                existing_client_response = client.get(
                    existing_client_url, headers=auth_headers
                )
                existing_client_response.raise_for_status()
                existing_client = existing_client_response.json()

                click.echo(f"Successfully retrieved client {update_client_id}")

                # Perform the update
                click.echo(f"Updating client {update_client_id}...")
                update_url = f"{portal_service_url}/clients/{update_client_id}"
                update_response = client.patch(
                    update_url, json=update_request_data, headers=auth_headers
                )
                update_response.raise_for_status()
                updated_client = update_response.json()

                click.echo(f"Successfully updated client {update_client_id}")

                # Calculate and display the differences
                diff = DeepDiff(existing_client, updated_client, verbose_level=2)

                click.echo("\n" + "=" * 50)
                click.echo("🎉 CLIENT UPDATED SUCCESSFULLY")
                click.echo("=" * 50)

                # Display full JSON if requested
                if show_full_json:
                    click.echo("\nExisting Client:")
                    click.echo(json.dumps(existing_client, indent=4))
                    click.echo("\nUpdated Client:")
                    click.echo(json.dumps(updated_client, indent=4))

                # Display the formatted differences
                click.echo("\n📊 SUMMARY OF CHANGES:")
                formatted_diff = format_diff_output(diff)
                click.echo(formatted_diff)

            except httpx.HTTPStatusError as e:
                click.echo(f"Error retrieving or updating client: {e}")
                click.echo(f"Status code: {e.response.status_code}")
                click.echo(f"Response: {e.response.text}")

        except Exception as e:
            click.echo(f"Error: {str(e)}")


if __name__ == "__main__":
    update_client()
