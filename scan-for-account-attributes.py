#!/usr/bin/env python
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "click",
#     "requests",
#     "tqdm",
# ]
# ///

import asyncio
import csv
import json
import sys
import time
from typing import Optional, List, Dict, Any, Tuple

import click
import requests
from tqdm import tqdm


# Define the key range (for 64-bit integers)
MIN_KEY = 0
MAX_KEY = 2**63 - 1


class Backoff:
    """Implements exponential backoff strategy similar to Java implementation"""

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

        delay = min(
            self.initial_delay_ms * (2 ** (self.tries - 1)),
            self.max_delay_ms
        )
        # Add jitter (±10%)
        jitter = delay * 0.1
        actual_delay = delay + (jitter * (2 * (0.5 - (time.time() % 1))))

        time.sleep(actual_delay / 1000)  # Convert ms to seconds


async def scan_page(
    base_url: str,
    name: str,
    value: str,
    product: Optional[str],
    start_key: int,
    start_inclusive: bool,
    end_key: int,
    end_inclusive: bool,
    auth_headers: Dict[str, str],
    count: int = 100,
    attribute_names: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Scan a single page of accounts with backoff retry logic
    """
    params = {
        "name": name,
        "value": value,
        "startKey": start_key,
        "endKey": end_key,
        "startInclusive": start_inclusive,
        "endInclusive": end_inclusive,
        "count": count
    }

    if product:
        params["product"] = product

    if attribute_names:
        params["attributeNames"] = attribute_names

    backoff = Backoff()

    while True:
        try:
            response = requests.get(f"{base_url}/accounts", headers=auth_headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            # Client errors (4xx) should not be retried
            if 400 <= e.response.status_code < 500:
                raise

            # Server errors (5xx) get retried with backoff
            click.echo(f"Error scanning page, try={backoff.tries}, name={name}, value={value}, startKey={start_key}: {e}", err=True)
            backoff.backoff()
        except requests.exceptions.RequestException as e:
            click.echo(f"Error scanning page, try={backoff.tries}, name={name}, value={value}, startKey={start_key}: {e}", err=True)
            backoff.backoff()


async def scan_key_range(
    base_url: str,
    name: str,
    value: str,
    product: Optional[str],
    start_key: int,
    end_key: int,
    auth_headers: Dict[str, str],
    count: int = 100,
    attribute_names: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Scan accounts within a specific key range
    """
    results = []
    current_start_key = start_key
    start_inclusive = True

    with tqdm(desc=f"Scanning {start_key} to {end_key}", leave=False) as pbar:
        while True:
            batch = await scan_page(
                base_url=base_url,
                name=name,
                value=value,
                product=product,
                start_key=current_start_key,
                start_inclusive=start_inclusive,
                end_key=end_key,
                end_inclusive=False,
                auth_headers=auth_headers,
                count=count,
                attribute_names=attribute_names
            )

            if not batch:
                break

            results.extend(batch)
            pbar.update(len(batch))

            # Update pagination based on the last item's key
            current_start_key = batch[-1]["key"]
            start_inclusive = False

    return results


def generate_key_ranges(partitions: int) -> List[Tuple[int, int]]:
    """Generate key ranges for partitions"""
    key_range = MAX_KEY - MIN_KEY
    partition_size = key_range // partitions

    ranges = []
    for i in range(partitions):
        start = MIN_KEY + (i * partition_size)
        end = MIN_KEY + ((i + 1) * partition_size - 1) if i < partitions - 1 else MAX_KEY
        ranges.append((start, end))

    return ranges


async def parallel_scan(
    base_url: str,
    name: str,
    value: str,
    product: Optional[str],
    auth_headers: Dict[str, str],
    partitions: int = 10,
    count: int = 100,
    attribute_names: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Perform parallel scanning by dividing the key space into multiple partitions
    """
    ranges = generate_key_ranges(partitions)

    tasks = []
    for start, end in ranges:
        tasks.append(
            scan_key_range(
                base_url=base_url,
                name=name,
                value=value,
                product=product,
                start_key=start,
                end_key=end,
                auth_headers=auth_headers,
                count=count,
                attribute_names=attribute_names
            )
        )

    results = await asyncio.gather(*tasks)
    # Flatten the list of lists
    return [item for sublist in results for item in sublist]


@click.command()
@click.option("--url", default="https://accsvced1uswest2.serversdev.getgo.com/v2", help="Base URL for the account service API")
@click.option("--name", required=True, help="Attribute name to search for")
@click.option("--value", required=True, help="JSON value to search for (in quotes for strings)")
@click.option("--product", help="Optional product context for the scan")
@click.option("--client-name", default="test_provisioner", help="Client name for authentication")
@click.option("--client-secret", help="Client secret for authentication")
@click.option("--partitions", default=10, type=int, help="Number of parallel partitions to scan")
@click.option("--count", default=100, type=int, help="Maximum number of results per request (1-100)")
@click.option("--attribute-names", help="Optional comma-separated list of attribute names to return")
@click.option("--output", "-o", help="Output file path (CSV format)")
def main(
    url: str,
    name: str,
    value: str,
    product: Optional[str],
    client_name: str,
    client_secret: Optional[str],
    partitions: int,
    count: int,
    attribute_names: Optional[str],
    output: Optional[str]
):
    """
    Scan accounts by attribute in parallel across the entire key space.

    Example:
    $ python scan_accounts.py --name "country" --value "\"US\"" --output results.csv
    """
    # Validate count is within allowed range
    if count < 1 or count > 100:
        click.echo("Count must be between 1 and 100", err=True)
        sys.exit(1)

    # Prepare auth headers matching Java implementation
    auth_headers = {"ClientName": client_name}
    if client_secret:
        auth_headers["ClientSecret"] = client_secret

    click.echo(f"Starting parallel scan with {partitions} partitions")

    # For string values, ensure they're properly quoted JSON strings
    # This handles the special case from the Java implementation where strings were formatted as "\"%s\"".formatted(value)
    try:
        # Try parsing the value to ensure it's valid JSON
        json_value = value
        parsed = json.loads(json_value)

        # If it's a plain string that's not already quoted, apply the double-quote formatting like Java
        if isinstance(parsed, str):
            click.echo(f"Value is a JSON string: {json_value}")
        else:
            click.echo(f"Value is JSON: {json_value}")
    except json.JSONDecodeError:
        click.echo(f"Error: The value '{value}' is not valid JSON. For strings, use quotes like: '\"example\"'", err=True)
        sys.exit(1)

    # Run the parallel scan
    loop = asyncio.get_event_loop()
    results = loop.run_until_complete(
        parallel_scan(
            base_url=url,
            name=name,
            value=value,
            product=product,
            auth_headers=auth_headers,
            partitions=partitions,
            count=count,
            attribute_names=attribute_names
        )
    )

    # Output results
    if output:
        try:
            # Write results to CSV without pandas
            with open(output, 'w', newline='') as csvfile:
                if not results:
                    click.echo("No results to save")
                    return

                # Get all possible field names from all results
                fieldnames = set()
                for result in results:
                    fieldnames.update(result.keys())

                writer = csv.DictWriter(csvfile, fieldnames=sorted(fieldnames))
                writer.writeheader()
                writer.writerows(results)

            click.echo(f"Results saved to {output}")
        except Exception as e:
            click.echo(f"Error saving results: {e}", err=True)
    else:
        # Pretty print the results to console
        click.echo(json.dumps(results, indent=2))

    # Display summary
    click.echo(f"\nFound {len(results)} matching accounts")


if __name__ == "__main__":
    main()