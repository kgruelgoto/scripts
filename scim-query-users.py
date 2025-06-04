# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "httpx",
#     "python-dotenv",
#     "rich",
# ]
# ///

"""
Script to authenticate with OAuth password flow and query /Users with filters

This script performs the following:
1. Authenticates using OAuth2 password flow
2. Makes filtered queries against the /Users endpoint
3. Displays the results in a formatted way
"""

import os
import sys
import json
import base64
import httpx
from dotenv import load_dotenv
from rich import print as rprint
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from urllib.parse import quote

# Load environment variables
load_dotenv()

# Create console for nice output
console = Console()

# Configuration - either from environment or will be prompted
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
ENVIRONMENT = os.getenv("ENVIRONMENT", "ED1").upper()  # Default to ED1

# Environment URLs
ENV_URLS = {
    "ED1": {
        "auth": "https://authenticationed1.lmiinc.test.expertcity.com",
        "identity": "https://iamed1.serversdev.getgo.com"
    },
    "RC1": {
        "auth": "https://authenticationrc1.lmiinc.test.expertcity.com",
        "identity": "https://iamrc1.serversdev.getgo.com"
    },
    "STAGE": {
        "auth": "https://authenticationstage.lmiinc.test.expertcity.com",
        "identity": "https://iamstage.servers.getgo.com"
    },
    "LIVE": {
        "auth": "https://identity.goto.com",
        "identity": "https://iam.servers.getgo.com"
    }
}

class OAuthClient:
    def __init__(self, client_id, client_secret, environment):
        self.client_id = client_id
        self.client_secret = client_secret
        self.environment = environment
        self.token = None
        self.auth_url = ENV_URLS[environment]["auth"]
        self.identity_url = ENV_URLS[environment]["identity"]
        self.client = httpx.Client(verify=False)  # In production, certificate verification should be enabled
    
    def encode_credentials(self):
        """Encode client credentials for OAuth authentication"""
        credentials = f"{self.client_id}:{self.client_secret}"
        return base64.b64encode(credentials.encode()).decode()
    
    def authenticate(self, username, password):
        """Authenticate using password grant flow"""
        auth_header = f"Basic {self.encode_credentials()}"
        data = {
            'grant_type': 'password',
            'username': username,
            'password': password
        }
        
        try:
            with console.status(f"Authenticating with {self.environment}..."):
                response = self.client.post(
                    f"{self.auth_url}/oauth/token",
                    headers={"Authorization": auth_header},
                    data=data
                )
                
                if response.status_code == 200:
                    self.token = response.json()
                    rprint(f"[green]Authentication successful![/green]")
                    return True
                else:
                    rprint(f"[red]Authentication failed: {response.status_code}[/red]")
                    rprint(response.text)
                    return False
        except Exception as e:
            rprint(f"[red]Authentication error: {str(e)}[/red]")
            return False
    
    def query_users(self, filter_string=None, sort_by=None, sort_order=None, count=None, start_index=None):
        """Query users with optional filter, sorting, and pagination"""
        if not self.token:
            rprint("[red]Not authenticated. Please authenticate first.[/red]")
            return None

        params = {}
        if filter_string:
            params["filter"] = filter_string
        if sort_by:
            params["sortBy"] = sort_by
        if sort_order:
            params["sortOrder"] = sort_order
        if count:
            params["count"] = count
        if start_index:
            params["startIndex"] = start_index
            
        # Add no-cache header for strongly consistent reads
        headers = {
            "Authorization": f"{self.token['token_type']} {self.token['access_token']}",
            "Cache-Control": "no-cache"
        }
        
        try:
            with console.status(f"Querying users..."):
                response = self.client.get(
                    f"{self.identity_url}/identity/v1/Users",
                    headers=headers,
                    params=params
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    rprint(f"[red]Query failed: {response.status_code}[/red]")
                    rprint(response.text)
                    return None
        except Exception as e:
            rprint(f"[red]Query error: {str(e)}[/red]")
            return None
            
    def display_results(self, results):
        """Display query results in a table format"""
        if not results or "resources" not in results:
            rprint("[yellow]No results or invalid response format.[/yellow]")
            return
            
        resources = results.get("resources", [])
        total = results.get("totalResults", 0)
        
        if not resources:
            rprint(f"[yellow]No users found. Total results: {total}[/yellow]")
            return
            
        table = Table(title=f"Users ({total} total)")
        table.add_column("ID", style="dim")
        table.add_column("Username")
        table.add_column("Display Name")
        table.add_column("Created")
        
        for user in resources:
            table.add_row(
                user.get("id", ""),
                user.get("userName", ""),
                user.get("displayName", ""),
                user.get("meta", {}).get("created", "")
            )
            
        console.print(table)
        
        # Print full JSON for the first user as an example
        if resources:
            rprint("[bold]First user details:[/bold]")
            rprint(json.dumps(resources[0], indent=2))

def prompt_for_input():
    """Prompt for missing configuration"""
    global CLIENT_ID, CLIENT_SECRET, ENVIRONMENT
    
    if ENVIRONMENT not in ENV_URLS:
        ENVIRONMENT = Prompt.ask("Environment", choices=list(ENV_URLS.keys()), default="ED1")
    
    if not CLIENT_ID:
        CLIENT_ID = Prompt.ask("Client ID")
    
    if not CLIENT_SECRET:
        CLIENT_SECRET = Prompt.ask("Client Secret", password=True)

def main():
    prompt_for_input()
    
    client = OAuthClient(CLIENT_ID, CLIENT_SECRET, ENVIRONMENT)
    
    # Authenticate
    username = Prompt.ask("Username (email)")
    password = Prompt.ask("Password", password=True)
    
    if not client.authenticate(username, password):
        sys.exit(1)
    
    while True:
        console.rule("[bold]User Query[/bold]")
        rprint("[cyan]Query options:[/cyan]")
        rprint("1. Find user by email")
        rprint("2. Find users by display name")
        rprint("3. Custom filter query")
        rprint("4. Exit")
        
        choice = Prompt.ask("Select an option", choices=["1", "2", "3", "4"], default="1")
        
        if choice == "4":
            break
            
        filter_string = None
        if choice == "1":
            email = Prompt.ask("Enter email address")
            filter_string = f'userName eq "{email}"'
        elif choice == "2":
            name = Prompt.ask("Enter display name (or part of it)")
            filter_string = f'displayName sw "{name}"'
        elif choice == "3":
            filter_string = Prompt.ask("Enter custom filter (e.g. 'userName eq \"test@example.com\"')")
        
        sort_by = Prompt.ask("Sort by (leave empty for default)", default="")
        sort_order = Prompt.ask("Sort order (asc/desc)", choices=["asc", "desc"], default="asc") if sort_by else ""
        count = Prompt.ask("Result count (leave empty for default)", default="")
        
        results = client.query_users(
            filter_string=filter_string,
            sort_by=sort_by or None,
            sort_order=sort_order or None,
            count=count or None
        )
        
        if results:
            client.display_results(results)
            
        continue_query = Prompt.ask("Continue querying? (y/n)", choices=["y", "n"], default="y")
        if continue_query.lower() != "y":
            break

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        rprint("\n[yellow]Script terminated by user.[/yellow]")
    except Exception as e:
        rprint(f"[red]An error occurred: {str(e)}[/red]")
