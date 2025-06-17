#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "click",
#     "httpx",
#     "colorama",
#     "deepdiff",
#     "tabulate",
# ]
# ///

import json
import sys
import os
from typing import Dict, Any, List, Optional, Tuple, Set
import time
import html
from collections import defaultdict

import click
import httpx
from colorama import Fore, Style, init
from deepdiff import DeepDiff
from tabulate import tabulate

# Initialize colorama
init(autoreset=True)


class Backoff:
    """Implements exponential backoff strategy"""

    def __init__(self, initial_delay_ms=100, max_delay_ms=30000, max_tries=10):
        self.initial_delay_ms = initial_delay_ms
        self.max_delay_ms = max_delay_ms
        self.max_tries = max_tries
        self.tries = 0

    def backoff(self):
        """Execute backoff delay and increment tries counter"""
        self.tries += 1
        if self.tries > self.max_tries:
            raise Exception(f"Exceeded maximum retries ({self.max_tries})")

        delay = min(self.initial_delay_ms * (2 ** (self.tries - 1)), self.max_delay_ms)
        # Add jitter (±10%)
        jitter = delay * 0.1
        actual_delay = delay + (jitter * (2 * (0.5 - (time.time() % 1))))

        time.sleep(actual_delay / 1000)  # Convert ms to seconds


class PlanSettingsClient:
    """Client for accessing plan settings from the Account Service API"""

    def __init__(self, base_url: str, client_name: str, client_secret: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "ClientName": client_name,
            "ClientSecret": client_secret,
            "Content-Type": "application/json",
        }

    def get_plan_settings(self, plan_name: str) -> Dict[str, Any]:
        """Get settings for a specific plan"""
        backoff = Backoff()

        while True:
            try:
                with httpx.Client() as client:
                    response = client.get(
                        f"{self.base_url}/plans/{plan_name}/product",
                        headers=self.headers,
                    )

                    if response.status_code == 200:
                        return response.json()
                    else:
                        response.raise_for_status()
            except httpx.HTTPStatusError as e:
                # Client errors (4xx) should not be retried
                if 400 <= e.response.status_code < 500:
                    click.echo(f"Error: {e}", err=True)
                    raise

                # Server errors (5xx) get retried with backoff
                click.echo(
                    f"Error getting plan settings, try={backoff.tries}: {e}", err=True
                )
                backoff.backoff()
            except httpx.RequestError as e:
                click.echo(
                    f"Error getting plan settings, try={backoff.tries}: {e}", err=True
                )
                backoff.backoff()


def format_value(value: Any) -> str:
    """Format a value for display"""
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2)
    elif value is None:
        return "null"
    elif isinstance(value, bool):
        return str(value).lower()
    else:
        return str(value)


def print_diff_item(
    path: str,
    change_type: str,
    old_val: Any = None,
    new_val: Any = None,
    indent: int = 0,
):
    """Print a single difference item with appropriate formatting"""
    indent_str = "  " * indent
    path_parts = path.split(".")
    key = path_parts[-1]

    if change_type == "added":
        click.echo(
            f"{indent_str}{Fore.GREEN}+ {key}: {format_value(new_val)}{Style.RESET_ALL}"
        )
    elif change_type == "removed":
        click.echo(
            f"{indent_str}{Fore.RED}- {key}: {format_value(old_val)}{Style.RESET_ALL}"
        )
    elif change_type == "changed":
        click.echo(f"{indent_str}{Fore.YELLOW}~ {key}: {Style.RESET_ALL}")
        click.echo(
            f"{indent_str}  {Fore.RED}- {format_value(old_val)}{Style.RESET_ALL}"
        )
        click.echo(
            f"{indent_str}  {Fore.GREEN}+ {format_value(new_val)}{Style.RESET_ALL}"
        )
    elif change_type == "dictionary_item_added":
        if isinstance(new_val, dict):
            click.echo(f"{indent_str}{Fore.GREEN}+ {key}: {Style.RESET_ALL}")
            for k, v in new_val.items():
                print_diff_item(f"{path}.{k}", "added", new_val=v, indent=indent + 1)
        else:
            click.echo(
                f"{indent_str}{Fore.GREEN}+ {key}: {format_value(new_val)}{Style.RESET_ALL}"
            )
    elif change_type == "dictionary_item_removed":
        if isinstance(old_val, dict):
            click.echo(f"{indent_str}{Fore.RED}- {key}: {Style.RESET_ALL}")
            for k, v in old_val.items():
                print_diff_item(f"{path}.{k}", "removed", old_val=v, indent=indent + 1)
        else:
            click.echo(
                f"{indent_str}{Fore.RED}- {key}: {format_value(old_val)}{Style.RESET_ALL}"
            )
    elif change_type == "values_changed":
        click.echo(f"{indent_str}{Fore.YELLOW}~ {key}: {Style.RESET_ALL}")
        click.echo(
            f"{indent_str}  {Fore.RED}- {format_value(old_val)}{Style.RESET_ALL}"
        )
        click.echo(
            f"{indent_str}  {Fore.GREEN}+ {format_value(new_val)}{Style.RESET_ALL}"
        )
    elif change_type == "type_changes":
        click.echo(
            f"{indent_str}{Fore.YELLOW}~ {key} (type changed): {Style.RESET_ALL}"
        )
        click.echo(
            f"{indent_str}  {Fore.RED}- {format_value(old_val)} ({type(old_val).__name__}){Style.RESET_ALL}"
        )
        click.echo(
            f"{indent_str}  {Fore.GREEN}+ {format_value(new_val)} ({type(new_val).__name__}){Style.RESET_ALL}"
        )
    else:
        click.echo(
            f"{indent_str}{Fore.CYAN}? {key}: Unknown change type: {change_type}{Style.RESET_ALL}"
        )


def html_diff_item(
    path: str,
    change_type: str,
    old_val: Any = None,
    new_val: Any = None,
    indent: int = 0,
) -> str:
    """Generate HTML for a single difference item"""
    indent_str = "&nbsp;&nbsp;" * indent
    path_parts = path.split(".")
    key = path_parts[-1]
    html_output = []

    if change_type == "added":
        html_output.append(
            f"{indent_str}<span class='added'>+ {html.escape(key)}: {html.escape(format_value(new_val))}</span>"
        )
    elif change_type == "removed":
        html_output.append(
            f"{indent_str}<span class='removed'>- {html.escape(key)}: {html.escape(format_value(old_val))}</span>"
        )
    elif change_type == "changed":
        html_output.append(
            f"{indent_str}<span class='changed'>~ {html.escape(key)}:</span>"
        )
        html_output.append(
            f"{indent_str}&nbsp;&nbsp;<span class='removed'>- {html.escape(format_value(old_val))}</span>"
        )
        html_output.append(
            f"{indent_str}&nbsp;&nbsp;<span class='added'>+ {html.escape(format_value(new_val))}</span>"
        )
    elif change_type == "dictionary_item_added":
        if isinstance(new_val, dict):
            html_output.append(
                f"{indent_str}<span class='added'>+ {html.escape(key)}:</span>"
            )
            for k, v in new_val.items():
                html_output.append(
                    html_diff_item(f"{path}.{k}", "added", new_val=v, indent=indent + 1)
                )
        else:
            html_output.append(
                f"{indent_str}<span class='added'>+ {html.escape(key)}: {html.escape(format_value(new_val))}</span>"
            )
    elif change_type == "dictionary_item_removed":
        if isinstance(old_val, dict):
            html_output.append(
                f"{indent_str}<span class='removed'>- {html.escape(key)}:</span>"
            )
            for k, v in old_val.items():
                html_output.append(
                    html_diff_item(
                        f"{path}.{k}", "removed", old_val=v, indent=indent + 1
                    )
                )
        else:
            html_output.append(
                f"{indent_str}<span class='removed'>- {html.escape(key)}: {html.escape(format_value(old_val))}</span>"
            )
    elif change_type == "values_changed":
        html_output.append(
            f"{indent_str}<span class='changed'>~ {html.escape(key)}:</span>"
        )
        html_output.append(
            f"{indent_str}&nbsp;&nbsp;<span class='removed'>- {html.escape(format_value(old_val))}</span>"
        )
        html_output.append(
            f"{indent_str}&nbsp;&nbsp;<span class='added'>+ {html.escape(format_value(new_val))}</span>"
        )
    elif change_type == "type_changes":
        html_output.append(
            f"{indent_str}<span class='changed'>~ {html.escape(key)} (type changed):</span>"
        )
        html_output.append(
            f"{indent_str}&nbsp;&nbsp;<span class='removed'>- {html.escape(format_value(old_val))} ({type(old_val).__name__})</span>"
        )
        html_output.append(
            f"{indent_str}&nbsp;&nbsp;<span class='added'>+ {html.escape(format_value(new_val))} ({type(new_val).__name__})</span>"
        )
    else:
        html_output.append(
            f"{indent_str}<span class='unknown'>? {html.escape(key)}: Unknown change type: {change_type}</span>"
        )

    return "<br>".join(html_output)


def process_diff(diff: Dict[str, Any], source_name: str, target_name: str):
    """Process and display differences between two JSON objects"""
    if not diff:
        click.echo(f"No differences found between {source_name} and {target_name}")
        return

    click.echo(
        f"\n{Fore.CYAN}=== Differences between {source_name} and {target_name} ==={Style.RESET_ALL}\n"
    )

    # Process added items
    if "dictionary_item_added" in diff:
        for item in diff["dictionary_item_added"]:
            path = item.replace("root['", "").replace("']", "").replace("']['", ".")
            parts = path.split(".")

            # Navigate to the added value
            target_obj = diff.t2
            for part in parts:
                if part in target_obj:
                    target_obj = target_obj[part]
                else:
                    target_obj = None
                    break

            print_diff_item(path, "dictionary_item_added", new_val=target_obj)

    # Process removed items
    if "dictionary_item_removed" in diff:
        for item in diff["dictionary_item_removed"]:
            path = item.replace("root['", "").replace("']", "").replace("']['", ".")
            parts = path.split(".")

            # Navigate to the removed value
            source_obj = diff.t1
            for part in parts:
                if part in source_obj:
                    source_obj = source_obj[part]
                else:
                    source_obj = None
                    break

            print_diff_item(path, "dictionary_item_removed", old_val=source_obj)

    # Process changed values
    if "values_changed" in diff:
        for item, change in diff["values_changed"].items():
            path = item.replace("root['", "").replace("']", "").replace("']['", ".")
            print_diff_item(
                path,
                "values_changed",
                old_val=change["old_value"],
                new_val=change["new_value"],
            )

    # Process type changes
    if "type_changes" in diff:
        for item, change in diff["type_changes"].items():
            path = item.replace("root['", "").replace("']", "").replace("']['", ".")
            print_diff_item(
                path,
                "type_changes",
                old_val=change["old_value"],
                new_val=change["new_value"],
            )


def process_diff_html(diff: Dict[str, Any], source_name: str, target_name: str) -> str:
    """Process differences between two JSON objects and return HTML"""
    html_output = []

    if not diff:
        html_output.append(
            f"<p>No differences found between {source_name} and {target_name}</p>"
        )
        return "\n".join(html_output)

    html_output.append(f"<h2>Differences between {source_name} and {target_name}</h2>")
    html_output.append("<div class='diff-section'>")

    # Process added items
    if "dictionary_item_added" in diff:
        for item in diff["dictionary_item_added"]:
            path = item.replace("root['", "").replace("']", "").replace("']['", ".")
            parts = path.split(".")

            # Navigate to the added value
            target_obj = diff.t2
            for part in parts:
                if part in target_obj:
                    target_obj = target_obj[part]
                else:
                    target_obj = None
                    break

            html_output.append(
                html_diff_item(path, "dictionary_item_added", new_val=target_obj)
            )

    # Process removed items
    if "dictionary_item_removed" in diff:
        for item in diff["dictionary_item_removed"]:
            path = item.replace("root['", "").replace("']", "").replace("']['", ".")
            parts = path.split(".")

            # Navigate to the removed value
            source_obj = diff.t1
            for part in parts:
                if part in source_obj:
                    source_obj = source_obj[part]
                else:
                    source_obj = None
                    break

            html_output.append(
                html_diff_item(path, "dictionary_item_removed", old_val=source_obj)
            )

    # Process changed values
    if "values_changed" in diff:
        for item, change in diff["values_changed"].items():
            path = item.replace("root['", "").replace("']", "").replace("']['", ".")
            html_output.append(
                html_diff_item(
                    path,
                    "values_changed",
                    old_val=change["old_value"],
                    new_val=change["new_value"],
                )
            )

    # Process type changes
    if "type_changes" in diff:
        for item, change in diff["type_changes"].items():
            path = item.replace("root['", "").replace("']", "").replace("']['", ".")
            html_output.append(
                html_diff_item(
                    path,
                    "type_changes",
                    old_val=change["old_value"],
                    new_val=change["new_value"],
                )
            )

    html_output.append("</div>")
    return "\n".join(html_output)


def extract_diff_items(diff: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract individual difference items from a DeepDiff object"""
    diff_items = []

    # Process added items
    if "dictionary_item_added" in diff:
        for item in diff["dictionary_item_added"]:
            path = item.replace("root['", "").replace("']", "").replace("']['", ".")
            parts = path.split(".")

            # Navigate to the added value
            target_obj = diff.t2
            for part in parts:
                if part in target_obj:
                    target_obj = target_obj[part]
                else:
                    target_obj = None
                    break

            diff_items.append({"path": path, "type": "added", "new_val": target_obj})

    # Process removed items
    if "dictionary_item_removed" in diff:
        for item in diff["dictionary_item_removed"]:
            path = item.replace("root['", "").replace("']", "").replace("']['", ".")
            parts = path.split(".")

            # Navigate to the removed value
            source_obj = diff.t1
            for part in parts:
                if part in source_obj:
                    source_obj = source_obj[part]
                else:
                    source_obj = None
                    break

            diff_items.append({"path": path, "type": "removed", "old_val": source_obj})

    # Process changed values
    if "values_changed" in diff:
        for item, change in diff["values_changed"].items():
            path = item.replace("root['", "").replace("']", "").replace("']['", ".")
            diff_items.append(
                {
                    "path": path,
                    "type": "changed",
                    "old_val": change["old_value"],
                    "new_val": change["new_value"],
                }
            )

    # Process type changes
    if "type_changes" in diff:
        for item, change in diff["type_changes"].items():
            path = item.replace("root['", "").replace("']", "").replace("']['", ".")
            diff_items.append(
                {
                    "path": path,
                    "type": "type_changed",
                    "old_val": change["old_value"],
                    "new_val": change["new_value"],
                }
            )

    return diff_items


def generate_flow_graph(
    settings_by_env: Dict[str, Dict[str, Any]],
    env_order: List[str],
    only_differences: bool = True,
    output_file: str = None,
):
    """Generate a flow graph visualization of differences between environments"""
    # Filter to only include available environments
    available_envs = [env for env in env_order if env in settings_by_env]

    if len(available_envs) < 2:
        click.echo("Need at least two environments to compare")
        return

    # Compare each environment with the next one in the sequence
    env_diffs = []
    for i in range(len(available_envs) - 1):
        source_env = available_envs[i]
        target_env = available_envs[i + 1]

        source_settings = settings_by_env[source_env]
        target_settings = settings_by_env[target_env]

        # Use DeepDiff for comparison
        diff = DeepDiff(source_settings, target_settings, verbose_level=2)

        # Extract differences
        diff_items = extract_diff_items(diff)

        env_diffs.append(
            {
                "source_env": source_env,
                "target_env": target_env,
                "diff": diff,
                "diff_items": diff_items,
                "diff_count": len(diff_items),
            }
        )

    # Generate HTML with Mermaid diagram
    html_content = []
    html_content.append(
        """<!DOCTYPE html>
<html>
<head>
    <title>Plan Settings Flow Graph</title>
    <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .added { color: green; }
        .removed { color: red; }
        .changed { color: orange; }
        .unknown { color: blue; }
        .mermaid { margin: 30px 0; }
        .diff-section { margin-bottom: 20px; border: 1px solid #ccc; padding: 10px; border-radius: 5px; }
        .diff-header { cursor: pointer; padding: 10px; background-color: #f0f0f0; margin-bottom: 10px; }
        .diff-header:hover { background-color: #e0e0e0; }
        .diff-content { display: none; padding: 10px; }
        .diff-content.show { display: block; }
        h2 { color: #333; }
        .summary { margin-top: 20px; }
        .env-node { fill: #f9f9f9; stroke: #333; stroke-width: 2px; }
        .diff-count { font-weight: bold; }
    </style>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Initialize Mermaid
            mermaid.initialize({ startOnLoad: true });
            
            // Add click handlers for collapsible sections
            document.querySelectorAll('.diff-header').forEach(header => {
                header.addEventListener('click', function() {
                    const content = this.nextElementSibling;
                    content.classList.toggle('show');
                });
            });
        });
    </script>
</head>
<body>
    <h1>Plan Settings Flow Graph</h1>
"""
    )

    # Generate Mermaid diagram
    html_content.append('<div class="mermaid">')
    html_content.append("graph LR")

    # Add nodes and edges
    for i, diff_data in enumerate(env_diffs):
        source_env = diff_data["source_env"]
        target_env = diff_data["target_env"]
        diff_count = diff_data["diff_count"]

        # Add nodes with styling
        if i == 0:  # First node
            html_content.append(
                f'    {source_env}["{source_env.upper()}"] --> |"{diff_count} differences"| {target_env}["{target_env.upper()}"]'
            )
            html_content.append(
                f"    style {source_env} fill:#f9f,stroke:#333,stroke-width:2px"
            )
        else:  # Middle nodes
            html_content.append(
                f'    {source_env} --> |"{diff_count} differences"| {target_env}["{target_env.upper()}"]'
            )

        # Last node styling
        if i == len(env_diffs) - 1:
            html_content.append(
                f"    style {target_env} fill:#9f9,stroke:#333,stroke-width:2px"
            )

    html_content.append("</div>")

    # Add collapsible sections for each environment transition
    for diff_data in env_diffs:
        source_env = diff_data["source_env"]
        target_env = diff_data["target_env"]
        diff_items = diff_data["diff_items"]
        diff_count = diff_data["diff_count"]

        if diff_count == 0 and only_differences:
            html_content.append(
                f"<p>No differences found between {source_env} and {target_env}</p>"
            )
            continue

        html_content.append(f'<div class="diff-section">')
        html_content.append(f'<div class="diff-header">')
        html_content.append(
            f"<h2>{source_env.upper()} → {target_env.upper()} Differences ({diff_count})</h2>"
        )
        html_content.append("</div>")
        html_content.append(f'<div class="diff-content">')

        # Group differences by type for better organization
        grouped_diffs = defaultdict(list)
        for item in diff_items:
            grouped_diffs[item["type"]].append(item)

        # Display differences by type
        if grouped_diffs["added"]:
            html_content.append("<h3>Added Settings</h3>")
            html_content.append("<ul>")
            for item in grouped_diffs["added"]:
                html_content.append(
                    f'<li><span class="added">{html.escape(item["path"])}: {html.escape(format_value(item["new_val"]))}</span></li>'
                )
            html_content.append("</ul>")

        if grouped_diffs["removed"]:
            html_content.append("<h3>Removed Settings</h3>")
            html_content.append("<ul>")
            for item in grouped_diffs["removed"]:
                html_content.append(
                    f'<li><span class="removed">{html.escape(item["path"])}: {html.escape(format_value(item["old_val"]))}</span></li>'
                )
            html_content.append("</ul>")

        if grouped_diffs["changed"] or grouped_diffs["type_changed"]:
            html_content.append("<h3>Changed Settings</h3>")
            html_content.append("<ul>")
            for item in grouped_diffs["changed"]:
                html_content.append(
                    f'<li><span class="changed">{html.escape(item["path"])}: {html.escape(format_value(item["old_val"]))} → {html.escape(format_value(item["new_val"]))}</span></li>'
                )
            for item in grouped_diffs["type_changed"]:
                html_content.append(
                    f'<li><span class="changed">{html.escape(item["path"])} (type changed): {html.escape(format_value(item["old_val"]))} ({type(item["old_val"]).__name__}) → {html.escape(format_value(item["new_val"]))} ({type(item["new_val"]).__name__})</span></li>'
                )
            html_content.append("</ul>")

        html_content.append("</div>")
        html_content.append("</div>")

    # Add summary
    html_content.append('<div class="summary">')
    html_content.append(f'<p>Environments compared: {", ".join(available_envs)}</p>')
    html_content.append("</div>")

    html_content.append("</body>")
    html_content.append("</html>")

    # Write to file
    html_output = "\n".join(html_content)
    with open(output_file, "w") as f:
        f.write(html_output)
    click.echo(f"Flow graph visualization written to {output_file}")


def compare_environments(
    settings_by_env: Dict[str, Dict[str, Any]],
    env_order: List[str],
    only_differences: bool = True,
    output_format: str = "terminal",
    output_file: Optional[str] = None,
):
    """Compare settings across environments in sequence"""
    # Filter to only include available environments
    available_envs = [env for env in env_order if env in settings_by_env]

    if len(available_envs) < 2:
        click.echo("Need at least two environments to compare")
        return

    # For HTML output, prepare the HTML content
    if output_format == "html":
        html_content = []
        html_content.append(
            """<!DOCTYPE html>
<html>
<head>
    <title>Plan Settings Comparison</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .added { color: green; }
        .removed { color: red; }
        .changed { color: orange; }
        .unknown { color: blue; }
        .diff-section { margin-bottom: 20px; border-bottom: 1px solid #ccc; padding-bottom: 10px; }
        h2 { color: #333; }
        table { border-collapse: collapse; width: 100%; margin-top: 20px; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
        tr:nth-child(even) { background-color: #f9f9f9; }
        .different { background-color: #ffffcc; }
        .null-value { color: red; }
    </style>
</head>
<body>
    <h1>Plan Settings Comparison</h1>
"""
        )

    # Compare each environment with the next one in the sequence
    for i in range(len(available_envs) - 1):
        source_env = available_envs[i]
        target_env = available_envs[i + 1]

        source_settings = settings_by_env[source_env]
        target_settings = settings_by_env[target_env]

        # Use DeepDiff for comparison
        diff = DeepDiff(source_settings, target_settings, verbose_level=2)

        # If only showing differences and there are none, skip this comparison
        if only_differences and not diff:
            if output_format == "terminal":
                click.echo(
                    f"No differences found between {source_env} and {target_env}"
                )
            elif output_format == "html":
                html_content.append(
                    f"<p>No differences found between {source_env} and {target_env}</p>"
                )
            continue

        # Process and display the differences
        if output_format == "terminal":
            process_diff(diff, source_env, target_env)
        elif output_format == "html":
            html_content.append(process_diff_html(diff, source_env, target_env))

    # For HTML output, complete the HTML content and write to file
    if output_format == "html":
        html_content.append("</body></html>")
        html_output = "\n".join(html_content)

        if output_file:
            with open(output_file, "w") as f:
                f.write(html_output)
            click.echo(f"HTML output written to {output_file}")
        else:
            click.echo(html_output)


def get_nested_value(data: Dict[str, Any], path: List[str]) -> Any:
    """Get a value from a nested dictionary using a path list"""
    current = data
    for part in path:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def collect_all_paths(
    data: Dict[str, Any], prefix: List[str] = None
) -> List[List[str]]:
    """Collect all paths in a nested dictionary"""
    if prefix is None:
        prefix = []

    paths = []
    for key, value in data.items():
        current_path = prefix + [key]
        paths.append(current_path)
        if isinstance(value, dict):
            paths.extend(collect_all_paths(value, current_path))

    return paths


def display_matrix_view(
    settings_by_env: Dict[str, Dict[str, Any]],
    env_order: List[str],
    only_differences: bool = True,
    output_format: str = "terminal",
    output_file: Optional[str] = None,
):
    """Display a matrix view of settings across all environments"""
    # Filter to only include available environments
    available_envs = [env for env in env_order if env in settings_by_env]

    if len(available_envs) < 2:
        click.echo("Need at least two environments to compare")
        return

    # Collect all unique paths across all environments
    all_paths = set()
    for env in available_envs:
        env_paths = collect_all_paths(settings_by_env[env])
        all_paths.update(tuple(path) for path in env_paths)

    # Sort paths for consistent display
    sorted_paths = sorted(all_paths)

    # Create table headers
    headers = ["Setting"] + available_envs

    # Create table rows
    rows = []
    different_settings_count = 0
    total_settings_count = len(sorted_paths)

    for path in sorted_paths:
        path_str = ".".join(path)

        # Get values for each environment
        values = []
        for env in available_envs:
            value = get_nested_value(settings_by_env[env], path)
            values.append(value)

        # Check if values differ across environments
        values_differ = len(set(str(v) for v in values)) > 1

        # Skip if only showing differences and all values are the same
        if only_differences and not values_differ:
            continue

        # Count different settings
        if values_differ:
            different_settings_count += 1

        # Create the row
        row = [path_str]

        # Add formatted values to row
        for value in values:
            formatted_value = format_value(value)
            if output_format == "terminal":
                if values_differ:
                    if value is None:
                        row.append(f"{Fore.RED}{formatted_value}{Style.RESET_ALL}")
                    else:
                        row.append(f"{Fore.YELLOW}{formatted_value}{Style.RESET_ALL}")
                else:
                    row.append(formatted_value)
            else:  # For HTML, we'll handle the formatting later
                row.append(formatted_value)

        rows.append((row, values_differ))

    if output_format == "terminal":
        # Display the table in terminal
        terminal_rows = [row for row, _ in rows]
        click.echo("\n" + tabulate(terminal_rows, headers=headers, tablefmt="grid"))

        # Display summary
        if only_differences:
            click.echo(
                f"\nShowing only different settings: {different_settings_count} of {total_settings_count} total"
            )
        else:
            click.echo(f"\nTotal settings: {len(rows)}")
            click.echo(f"Different settings: {different_settings_count}")
        click.echo(f"Environments compared: {', '.join(available_envs)}")

    elif output_format == "html":
        # Generate HTML table
        html_content = []
        html_content.append(
            """<!DOCTYPE html>
<html>
<head>
    <title>Plan Settings Comparison</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        table { border-collapse: collapse; width: 100%; margin-top: 20px; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
        tr:nth-child(even) { background-color: #f9f9f9; }
        .different { background-color: #ffffcc; }
        .null-value { color: red; }
        .summary { margin-top: 20px; }
    </style>
</head>
<body>
    <h1>Plan Settings Comparison</h1>
    <table>
        <tr>
"""
        )
        # Add headers
        for header in headers:
            html_content.append(f"            <th>{html.escape(header)}</th>")
        html_content.append("        </tr>")

        # Add rows
        for row, values_differ in rows:
            if values_differ:
                html_content.append('        <tr class="different">')
            else:
                html_content.append("        <tr>")

            # Add setting name
            html_content.append(f"            <td>{html.escape(row[0])}</td>")

            # Add values
            for i, value in enumerate(row[1:]):
                if value == "null":
                    html_content.append(
                        f'            <td class="null-value">{html.escape(value)}</td>'
                    )
                else:
                    html_content.append(f"            <td>{html.escape(value)}</td>")

            html_content.append("        </tr>")

        html_content.append("    </table>")

        # Add summary
        html_content.append('    <div class="summary">')
        if only_differences:
            html_content.append(
                f"        <p>Showing only different settings: {different_settings_count} of {total_settings_count} total</p>"
            )
        else:
            html_content.append(f"        <p>Total settings: {len(rows)}</p>")
            html_content.append(
                f"        <p>Different settings: {different_settings_count}</p>"
            )
        html_content.append(
            f"        <p>Environments compared: {', '.join(available_envs)}</p>"
        )
        html_content.append("    </div>")
        html_content.append("</body>")
        html_content.append("</html>")

        html_output = "\n".join(html_content)

        if output_file:
            with open(output_file, "w") as f:
                f.write(html_output)
            click.echo(f"HTML output written to {output_file}")
        else:
            click.echo(html_output)


# Default base URLs for each environment
DEFAULT_URLS = {
    "ed1": "https://accsvced1uswest2.serversdev.getgo.com/v2",
    "rc1": "https://accsvcrc1uswest2.serversdev.getgo.com/v2",
    "stage": "https://accsvcstageuswest2.servers.getgo.com/v2",
    "live": "https://accsvcuswest2.servers.getgo.com/v2",
}


@click.command()
@click.option("--plan", required=True, help="Plan name to compare across environments")
@click.option(
    "--environments",
    "-e",
    multiple=True,
    type=click.Choice(["ed1", "rc1", "stage", "live"]),
    default=["ed1", "rc1", "stage", "live"],
    help="Environments to compare (in order)",
)
@click.option("--client-name", required=True, help="Client name for authentication")
@click.option(
    "--client-secret",
    help="Client secret for authentication (can use --dev-client-secret and --prod-client-secret instead)",
)
@click.option(
    "--dev-client-secret", help="Client secret for development environments (ED1, RC1)"
)
@click.option(
    "--prod-client-secret",
    help="Client secret for production environments (Stage, Live)",
)
@click.option(
    "--ed1-url", default=DEFAULT_URLS["ed1"], help="Base URL for ED1 environment"
)
@click.option(
    "--rc1-url", default=DEFAULT_URLS["rc1"], help="Base URL for RC1 environment"
)
@click.option(
    "--stage-url", default=DEFAULT_URLS["stage"], help="Base URL for Stage environment"
)
@click.option(
    "--live-url", default=DEFAULT_URLS["live"], help="Base URL for Live environment"
)
@click.option(
    "--view",
    type=click.Choice(["sequential", "matrix"]),
    default="sequential",
    help="View type: sequential (default) or matrix",
)
@click.option(
    "--only-differences/--show-all",
    default=True,
    help="Show only settings that differ between environments (default: True)",
)
@click.option(
    "--output-format",
    type=click.Choice(["terminal", "html", "flow-graph"]),
    default="terminal",
    help="Output format: terminal (default), html, or flow-graph",
)
@click.option(
    "--output-file",
    help="File to write output to (required for HTML output)",
)
def main(
    plan: str,
    environments: List[str],
    client_name: str,
    client_secret: Optional[str],
    dev_client_secret: Optional[str],
    prod_client_secret: Optional[str],
    ed1_url: str,
    rc1_url: str,
    stage_url: str,
    live_url: str,
    view: str,
    only_differences: bool,
    output_format: str,
    output_file: Optional[str],
):
    """
    Compare plan settings across different environments.

    This tool fetches plan settings from multiple environments and displays
    the differences in a hierarchical, color-coded format.
    """
    # Validate output format and file
    if output_format in ["html", "flow-graph"] and not output_file:
        click.echo(
            f"Error: --output-file is required when using --output-format={output_format}",
            err=True,
        )
        sys.exit(1)

    # Map environment names to their URLs
    env_urls = {"ed1": ed1_url, "rc1": rc1_url, "stage": stage_url, "live": live_url}

    # Validate client secrets
    if not client_secret and not (dev_client_secret and prod_client_secret):
        if not client_secret and not dev_client_secret and not prod_client_secret:
            click.echo(
                "Error: Either --client-secret or both --dev-client-secret and --prod-client-secret must be provided",
                err=True,
            )
            sys.exit(1)
        elif (
            dev_client_secret
            and not prod_client_secret
            and any(env in ["stage", "live"] for env in environments)
        ):
            click.echo(
                "Error: --prod-client-secret is required when comparing Stage or Live environments without --client-secret",
                err=True,
            )
            sys.exit(1)
        elif (
            prod_client_secret
            and not dev_client_secret
            and any(env in ["ed1", "rc1"] for env in environments)
        ):
            click.echo(
                "Error: --dev-client-secret is required when comparing ED1 or RC1 environments without --client-secret",
                err=True,
            )
            sys.exit(1)

    # Determine which client secret to use for each environment
    env_client_secrets = {}
    for env in environments:
        if env in ["ed1", "rc1"]:
            # Use dev client secret for ED1 and RC1
            env_client_secrets[env] = dev_client_secret or client_secret
        else:
            # Use prod client secret for Stage and Live
            env_client_secrets[env] = prod_client_secret or client_secret

    # Fetch settings from each environment
    settings_by_env = {}
    for env in environments:
        click.echo(f"Fetching settings for plan '{plan}' from {env} environment...")
        client = PlanSettingsClient(env_urls[env], client_name, env_client_secrets[env])
        try:
            settings = client.get_plan_settings(plan)
            settings_by_env[env] = settings
            click.echo(f"Successfully fetched settings from {env}")
        except Exception as e:
            click.echo(f"Failed to fetch settings from {env}: {e}", err=True)

    # Compare environments based on selected view and output format
    if output_format == "flow-graph":
        generate_flow_graph(
            settings_by_env,
            list(environments),
            only_differences,
            output_file,
        )
    elif view == "sequential":
        compare_environments(
            settings_by_env,
            list(environments),
            only_differences,
            output_format,
            output_file,
        )
    else:
        display_matrix_view(
            settings_by_env,
            list(environments),
            only_differences,
            output_format,
            output_file,
        )


if __name__ == "__main__":
    main()
