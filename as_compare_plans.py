#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "account-service-python-sdk>=0.8.1",
#     "httpx>=0.28.1",
#     "rich>=14.1.0",
#     "deepdiff>=8.0.0",
# ]
# [[tool.uv.index]]
# url = "https://artifactory.prodwest.citrixsaassbe.net/artifactory/api/pypi/pypi-dev/simple"
# ///
"""
Plan Settings Comparison Tool

Compare plan settings across environments (ed -> rc -> stage -> live) to identify
configuration discrepancies. client-name & client-secret are your AS Client Credentials.

usage: as_compare_plans.py [-h] [--show-consistent] [--tree-view] [--markdown FILE] [--confluence FILE] --client-name CLIENT_NAME --client-secret CLIENT_SECRET plan_name

positional arguments:
  plan_name             Name of the plan to compare

options:
  -h, --help            show this help message and exit
  --show-consistent, -c
                        Show settings that are consistent across all environments
  --tree-view, -t       Show settings in a tree structure
  --markdown, -m FILE   Export detailed report to markdown file (e.g., report.md)
  --confluence, -j FILE
                        Export detailed report to Confluence wiki markup file (e.g., report.confluence)
  --client-name CLIENT_NAME
                        Client name for AccountService authentication
  --client-secret CLIENT_SECRET
                        Client secret for AccountService authentication
"""

import asyncio
import argparse
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass
from datetime import datetime

from account_service import AccountService
from account_service.core.exceptions import ASIncidentException
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.tree import Tree
from rich import print as rprint

ENVIRONMENTS = {
    "ed": "accsvced1uswest2.serversdev.getgo.com",
    "rc": "accsvcrc1uswest2.serversdev.getgo.com",
    "stage": "accsvcstageuswest2.servers.getgo.com",
    "live": "accsvcuswest2.servers.getgo.com",
}

ENV_ORDER = ["ed", "rc", "stage", "live"]

@dataclass
class EnvironmentData:
    name: str
    settings: Dict[str, Any]
    error: str = None

class PlanComparator:
    def __init__(self):
        self.console = Console()

    def format_value_for_display(self, value: Any) -> str:
        """Format complex values (lists, dicts) for display."""
        if isinstance(value, (list, dict)):
            if isinstance(value, list):
                return f"[{len(value)} items]" if len(value) > 3 else str(value)
            else:  # dict
                return f"{{{len(value)} keys}}" if len(value) > 3 else str(value)
        return str(value)

    async def fetch_plan_settings(self, env_name: str, plan_name: str, client_name: str, client_secret: str) -> EnvironmentData:
        """Fetch plan settings for a specific environment."""
        try:
            env_url = ENVIRONMENTS[env_name]
            async with AccountService(
                base_url=f"https://{env_url}/v2",
                client_name=client_name,
                client_secret=client_secret,
            ) as client:
                settings_model = await client.get_plan_settings(plan_name)
                # Convert Pydantic model to dictionary
                if hasattr(settings_model, 'model_dump'):
                    settings = settings_model.model_dump()
                elif hasattr(settings_model, 'dict'):
                    settings = settings_model.dict()
                else:
                    # Fallback to dict() conversion
                    settings = dict(settings_model) if settings_model else {}
                return EnvironmentData(name=env_name, settings=settings)
        except ASIncidentException as e:
            return EnvironmentData(name=env_name, settings={}, error=f"API Error {e.status_code}: {e}")
        except Exception as e:
            return EnvironmentData(name=env_name, settings={}, error=f"Error: {e}")

    async def fetch_all_environments(self, plan_name: str, client_name: str, client_secret: str) -> List[EnvironmentData]:
        """Fetch plan settings from all environments in parallel."""
        tasks = [
            self.fetch_plan_settings(env_name, plan_name, client_name, client_secret)
            for env_name in ENV_ORDER
        ]
        return await asyncio.gather(*tasks)

    def flatten_dict(self, d: Dict[str, Any], parent_key: str = '', sep: str = '.') -> Dict[str, Any]:
        """Flatten nested dictionary for easier comparison."""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self.flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    def find_differences(self, env_data: List[EnvironmentData]) -> Dict[str, Dict[str, List[Tuple[str, Any]]]]:
        """Find all differences across environments."""
        # Get all unique keys from all environments
        all_keys = set()
        flat_data = {}

        for env in env_data:
            if env.settings:
                flat_settings = self.flatten_dict(env.settings)
                flat_data[env.name] = flat_settings
                all_keys.update(flat_settings.keys())

        differences = {}
        consistent = {}

        for key in all_keys:
            values = []
            for env_name in ENV_ORDER:
                if env_name in flat_data:
                    value = flat_data[env_name].get(key, "⚠ MISSING")
                else:
                    value = "❌ ERROR"
                values.append((env_name, value))

            # Check if all values are the same (handle unhashable types)
            actual_values = [v for _, v in values if v not in ["⚠ MISSING", "❌ ERROR"]]
            non_error_values = [v for _, v in values if v != "❌ ERROR"]

            # Convert values to strings for comparison to handle unhashable types
            def make_comparable(value):
                if isinstance(value, (list, dict)):
                    return str(sorted(value.items()) if isinstance(value, dict) else value)
                return str(value)

            comparable_values = [make_comparable(v) for v in actual_values]

            if len(set(comparable_values)) > 1 or len(actual_values) != len(non_error_values):
                differences[key] = values
            else:
                consistent[key] = values

        return {"differences": differences, "consistent": consistent}

    def display_summary(self, env_data: List[EnvironmentData], analysis: Dict[str, Any]):
        """Display a summary of the comparison."""
        # Environment status panel
        status_table = Table(title="Environment Status", show_header=True, header_style="bold magenta")
        status_table.add_column("Environment", style="cyan", no_wrap=True)
        status_table.add_column("Status", style="white")
        status_table.add_column("Settings Count", justify="right")

        for env in env_data:
            if env.error:
                status_table.add_row(env.name.upper(), f"[red]❌ {env.error}[/red]", "-")
            else:
                count = len(self.flatten_dict(env.settings)) if env.settings else 0
                status_table.add_row(env.name.upper(), "[green]✅ Success[/green]", str(count))

        self.console.print(status_table)
        self.console.print()

        # Summary statistics
        diff_count = len(analysis["differences"])
        consistent_count = len(analysis["consistent"])
        total_settings = diff_count + consistent_count

        if total_settings > 0:
            consistency_pct = (consistent_count / total_settings) * 100
            summary_text = f"""
📊 Comparison Summary:
• Total Settings: {total_settings}
• Consistent: {consistent_count} ({consistency_pct:.1f}%)
• Different: {diff_count} ({100-consistency_pct:.1f}%)
"""
        else:
            summary_text = "❌ No settings found to compare"

        self.console.print(Panel(summary_text, title="Summary", border_style="blue"))
        self.console.print()

    def display_differences(self, differences: Dict[str, List[Tuple[str, Any]]]):
        """Display differences in a detailed table."""
        if not differences:
            self.console.print("[green]🎉 No differences found! All environments are consistent.[/green]")
            return

        # Create table for differences
        diff_table = Table(title="🔍 Setting Differences", show_header=True, header_style="bold red")
        diff_table.add_column("Setting", style="cyan", no_wrap=True, min_width=20)
        diff_table.add_column("ED", style="white", min_width=10)
        diff_table.add_column("RC", style="white", min_width=10)
        diff_table.add_column("Stage", style="white", min_width=10)
        diff_table.add_column("Live", style="white", min_width=10)
        diff_table.add_column("Pipeline Changes", style="yellow", min_width=15)

        for setting, env_values in sorted(differences.items()):
            values_dict = dict(env_values)

            # Track where changes occur in the pipeline
            changes = []
            prev_value = None
            for env_name in ENV_ORDER:
                current_value = values_dict.get(env_name, "⚠ MISSING")
                if prev_value is not None and current_value != prev_value and current_value not in ["⚠ MISSING", "❌ ERROR"]:
                    changes.append(f"{env_name}")
                prev_value = current_value

            change_summary = " → ".join(changes) if changes else "inconsistent"

            # Format values with colors
            formatted_values = []
            for env_name in ENV_ORDER:
                value = values_dict.get(env_name, "⚠ MISSING")
                if value == "⚠ MISSING":
                    formatted_values.append("[yellow]MISSING[/yellow]")
                elif value == "❌ ERROR":
                    formatted_values.append("[red]ERROR[/red]")
                else:
                    display_value = self.format_value_for_display(value)

                    # Highlight if this value is different from the first valid value
                    first_valid = next((v for _, v in env_values if v not in ["⚠ MISSING", "❌ ERROR"]), None)
                    def make_comparable(v):
                        if isinstance(v, (list, dict)):
                            return str(sorted(v.items()) if isinstance(v, dict) else v)
                        return str(v)

                    if make_comparable(value) != make_comparable(first_valid):
                        formatted_values.append(f"[bold yellow]{display_value}[/bold yellow]")
                    else:
                        formatted_values.append(display_value)

            diff_table.add_row(
                setting,
                formatted_values[0],
                formatted_values[1],
                formatted_values[2],
                formatted_values[3],
                change_summary
            )

        self.console.print(diff_table)

    def display_tree_view(self, env_data: List[EnvironmentData]):
        """Display settings in a tree structure."""
        # Find a representative environment with data
        sample_env = next((env for env in env_data if env.settings), None)
        if not sample_env:
            return

        tree = Tree(f"📋 Plan Settings Structure (based on {sample_env.name.upper()})")

        def add_to_tree(node, data, path=""):
            for key, value in data.items():
                current_path = f"{path}.{key}" if path else key
                if isinstance(value, dict):
                    branch = node.add(f"📁 {key}")
                    add_to_tree(branch, value, current_path)
                else:
                    node.add(f"🔧 {key}: {value}")

        add_to_tree(tree, sample_env.settings)
        self.console.print(tree)

    def generate_markdown_report(self, plan_name: str, env_data: List[EnvironmentData], analysis: Dict[str, Any], include_consistent: bool = False) -> str:
        """Generate a detailed markdown report for tickets."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Calculate summary stats
        diff_count = len(analysis["differences"])
        consistent_count = len(analysis["consistent"])
        total_settings = diff_count + consistent_count
        consistency_pct = (consistent_count / total_settings) * 100 if total_settings > 0 else 0

        md = f"""# Plan Comparison Report: {plan_name}

**Generated:** {timestamp}
**Total Settings:** {total_settings}
**Consistent:** {consistent_count} ({consistency_pct:.1f}%)
**Different:** {diff_count} ({100-consistency_pct:.1f}%)

## Environment Status

| Environment | Status | Settings Count |
|-------------|--------|----------------|
"""

        # Add environment status
        for env in env_data:
            if env.error:
                status = f"❌ {env.error}"
                count = "-"
            else:
                status = "✅ Success"
                count = len(self.flatten_dict(env.settings)) if env.settings else 0
            md += f"| {env.name.upper()} | {status} | {count} |\n"

        # Add differences section
        if analysis["differences"]:
            md += f"\n## Setting Differences ({diff_count} items)\n\n"
            md += "| Setting | ED | RC | Stage | Live | Pipeline Changes |\n"
            md += "|---------|----|----|-------|------|-----------------|\n"

            for setting, env_values in sorted(analysis["differences"].items()):
                values_dict = dict(env_values)

                # Track pipeline changes
                changes = []
                prev_value = None
                for env_name in ENV_ORDER:
                    current_value = values_dict.get(env_name, "⚠ MISSING")
                    if prev_value is not None and current_value != prev_value and current_value not in ["⚠ MISSING", "❌ ERROR"]:
                        changes.append(env_name)
                    prev_value = current_value

                change_summary = " → ".join(changes) if changes else "inconsistent"

                # Format values for markdown (escape pipes)
                formatted_values = []
                for env_name in ENV_ORDER:
                    value = values_dict.get(env_name, "⚠ MISSING")
                    if value in ["⚠ MISSING", "❌ ERROR"]:
                        display_value = "MISSING" if value == "⚠ MISSING" else "ERROR"
                    else:
                        display_value = self.format_value_for_display(value)
                        # Escape markdown special characters
                        display_value = display_value.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")
                    formatted_values.append(display_value)

                # Escape setting name
                safe_setting = setting.replace("|", "\\|")

                md += f"| `{safe_setting}` | {formatted_values[0]} | {formatted_values[1]} | {formatted_values[2]} | {formatted_values[3]} | {change_summary} |\n"
        else:
            md += "\n## 🎉 No Differences Found\n\nAll environments are consistent!\n"

        # Add consistent settings if requested
        if include_consistent and analysis["consistent"]:
            md += f"\n## Consistent Settings ({consistent_count} items)\n\n"
            md += "| Setting | Value |\n"
            md += "|---------|-------|\n"

            for setting in sorted(analysis["consistent"].keys()):
                value = analysis["consistent"][setting][0][1]  # Get first env's value
                display_value = self.format_value_for_display(value)
                # Escape markdown special characters
                display_value = display_value.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")
                safe_setting = setting.replace("|", "\\|")
                md += f"| `{safe_setting}` | {display_value} |\n"

        # Add metadata
        md += f"\n---\n*Report generated by as_compare_plans.py*\n"

        return md

    def generate_confluence_report(self, plan_name: str, env_data: List[EnvironmentData], analysis: Dict[str, Any], include_consistent: bool = False) -> str:
        """Generate a detailed Confluence wiki markup report for Jira tickets."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Calculate summary stats
        diff_count = len(analysis["differences"])
        consistent_count = len(analysis["consistent"])
        total_settings = diff_count + consistent_count
        consistency_pct = (consistent_count / total_settings) * 100 if total_settings > 0 else 0

        confluence = f"""h1. Plan Comparison Report: {plan_name}

*Generated:* {timestamp}
*Total Settings:* {total_settings}
*Consistent:* {consistent_count} ({consistency_pct:.1f}%)
*Different:* {diff_count} ({100-consistency_pct:.1f}%)

h2. Environment Status

||Environment||Status||Settings Count||
"""

        # Add environment status
        for env in env_data:
            if env.error:
                status = f"(!) {env.error}"
                count = "-"
            else:
                status = "(/) Success"
                count = len(self.flatten_dict(env.settings)) if env.settings else 0
            confluence += f"|{env.name.upper()}|{status}|{count}|\n"

        # Add differences section
        if analysis["differences"]:
            confluence += f"\nh2. Setting Differences ({diff_count} items)\n\n"
            confluence += "||Setting||ED||RC||Stage||Live||Pipeline Changes||\n"

            for setting, env_values in sorted(analysis["differences"].items()):
                values_dict = dict(env_values)

                # Track pipeline changes
                changes = []
                prev_value = None
                for env_name in ENV_ORDER:
                    current_value = values_dict.get(env_name, "⚠ MISSING")
                    if prev_value is not None and current_value != prev_value and current_value not in ["⚠ MISSING", "❌ ERROR"]:
                        changes.append(env_name)
                    prev_value = current_value

                change_summary = " → ".join(changes) if changes else "inconsistent"

                # Format values for Confluence
                formatted_values = []
                for env_name in ENV_ORDER:
                    value = values_dict.get(env_name, "⚠ MISSING")
                    if value in ["⚠ MISSING", "❌ ERROR"]:
                        display_value = "*MISSING*" if value == "⚠ MISSING" else "*ERROR*"
                    else:
                        display_value = self.format_value_for_display(value)
                        # Escape Confluence special characters
                        display_value = display_value.replace("|", "\\|")
                    formatted_values.append(display_value)

                # Format setting name with code markup
                code_setting = f"{{{{{setting}}}}}"

                confluence += f"|{code_setting}|{formatted_values[0]}|{formatted_values[1]}|{formatted_values[2]}|{formatted_values[3]}|{change_summary}|\n"
        else:
            confluence += "\nh2. (/) No Differences Found\n\nAll environments are consistent!\n"

        # Add consistent settings if requested
        if include_consistent and analysis["consistent"]:
            confluence += f"\nh2. Consistent Settings ({consistent_count} items)\n\n"
            confluence += "||Setting||Value||\n"

            for setting in sorted(analysis["consistent"].keys()):
                value = analysis["consistent"][setting][0][1]  # Get first env's value
                display_value = self.format_value_for_display(value)
                # Escape Confluence special characters
                display_value = display_value.replace("|", "\\|")
                code_setting = f"{{{{{setting}}}}}"
                confluence += f"|{code_setting}|{display_value}|\n"

        # Add metadata
        confluence += f"\n----\n_Report generated by as_compare_plans.py_\n"

        return confluence

async def main(plan_name: str = None, show_consistent: bool = False, tree_view: bool = False, markdown: str = None, confluence: str = None, client_name: str = None, client_secret: str = None):
    """Main function to compare plan settings across environments."""
    if not plan_name:
        print("❌ Plan name is required")
        return

    if not client_name or not client_secret:
        print("❌ Client name and client secret are required")
        return

    comparator = PlanComparator()

    with comparator.console.status(f"[bold green]Fetching plan settings for '{plan_name}' from all environments..."):
        env_data = await comparator.fetch_all_environments(plan_name, client_name, client_secret)

    # Analyze differences
    analysis = comparator.find_differences(env_data)

    # Handle export options
    if markdown:
        md_report = comparator.generate_markdown_report(plan_name, env_data, analysis, include_consistent=show_consistent)
        with open(markdown, 'w') as f:
            f.write(md_report)
        rprint(f"[green]✅ Markdown report saved to: {markdown}[/green]")
        return

    if confluence:
        confluence_report = comparator.generate_confluence_report(plan_name, env_data, analysis, include_consistent=show_consistent)
        with open(confluence, 'w') as f:
            f.write(confluence_report)
        rprint(f"[green]✅ Confluence report saved to: {confluence}[/green]")
        return

    # Display results (terminal output)
    rprint(f"\n[bold blue]🔍 Plan Comparison Report: {plan_name}[/bold blue]")
    rprint("=" * 60)

    comparator.display_summary(env_data, analysis)
    if "differences" in analysis:
        comparator.display_differences(analysis["differences"])

    if show_consistent and analysis["consistent"]:
        rprint(f"\n[green]✅ Consistent Settings ({len(analysis['consistent'])} items):[/green]")
        for setting in sorted(analysis["consistent"].keys()):
            value = analysis["consistent"][setting][0][1]  # Get first env's value
            display_value = comparator.format_value_for_display(value)
            rprint(f"  • {setting}: {display_value}")

    if tree_view:
        rprint("\n")
        comparator.display_tree_view(env_data)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Compare plan settings across environments")
    parser.add_argument("plan_name", help="Name of the plan to compare")
    parser.add_argument("--show-consistent", "-c", action="store_true",
                       help="Show settings that are consistent across all environments")
    parser.add_argument("--tree-view", "-t", action="store_true",
                       help="Show settings in a tree structure")
    parser.add_argument("--markdown", "-m", metavar="FILE",
                       help="Export detailed report to markdown file (e.g., report.md)")
    parser.add_argument("--confluence", "-j", metavar="FILE",
                       help="Export detailed report to Confluence wiki markup file (e.g., report.confluence)")
    parser.add_argument("--client-name", required=True,
                       help="Client name for AccountService authentication")
    parser.add_argument("--client-secret", required=True,
                       help="Client secret for AccountService authentication")

    args = parser.parse_args()

    asyncio.run(main(
        plan_name=args.plan_name,
        show_consistent=args.show_consistent,
        tree_view=args.tree_view,
        markdown=args.markdown,
        confluence=args.confluence,
        client_name=args.client_name,
        client_secret=args.client_secret
    ))