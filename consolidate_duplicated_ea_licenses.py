import requests
import logging
from collections import defaultdict
from time import sleep
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Dict, Any, Tuple
import functools
import click


ROLE_NAME = "ROLE_EXT_ADMIN"
BATCH_SIZE = 50
SLEEP_BETWEEN_BATCHES = 1

MIN_KEY = 0
MAX_KEY = 2**63 - 1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

def generate_key_ranges(partitions: int) -> List[Tuple[int, int]]:
    key_range = MAX_KEY - MIN_KEY
    partition_size = key_range // partitions
    ranges = []
    for i in range(partitions):
        start = MIN_KEY + (i * partition_size)
        end = MIN_KEY + ((i + 1) * partition_size - 1) if i < partitions - 1 else MAX_KEY
        ranges.append((start, end))
    return ranges

def fetch_licenses_by_role_and_key_range(role, start_key, end_key, api_base_url, headers) -> List[Dict[str, Any]]:
    all_licenses = []
    start = start_key
    while True:
        params = {"role": role, "count": 100, "startKey": start, "endKey": end_key, "startInclusive": True, "endInclusive": False, "attributeNames": "key,userKeys,accountKey,enabled"}
        url = f"{api_base_url}/licenses"
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        licenses = resp.json()
        if not licenses:
            break
        all_licenses.extend(licenses)
        if len(licenses) < 100:
            break
        start = licenses[-1]["key"]
    return all_licenses

async def parallel_fetch_licenses(role, partitions, api_base_url, headers) -> List[Dict[str, Any]]:
    ranges = generate_key_ranges(partitions)
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        tasks = [
            loop.run_in_executor(
                executor,
                functools.partial(fetch_licenses_by_role_and_key_range, role, start, end, api_base_url, headers)
            )
            for start, end in ranges
        ]
        results = await asyncio.gather(*tasks)
    return [item for sublist in results for item in sublist]

def move_user_to_license(user_id, target_license_key, api_base_url, headers):
    url = f"{api_base_url}/licenses/{target_license_key}/users/{user_id}"
    resp = requests.post(url, headers=headers)
    resp.raise_for_status()

def delete_license(license_key, api_base_url, headers):
    url = f"{api_base_url}/licenses/{license_key}"
    resp = requests.delete(url, headers=headers)
    resp.raise_for_status()

def process_account_licenses(account_licenses, api_base_url, headers):
    for accountKey, ea_licenses in account_licenses.items():
        if len(ea_licenses) <= 1:
            continue
        logger.info(f"Processing account {accountKey} with {len(ea_licenses)} ea_licenses")
        primary = max(ea_licenses, key=lambda l: len(l.get("userKeys", [])))
        primary_key = primary["key"]
        primary_users = set(primary.get("userKeys", []))
        for lic in ea_licenses:
            if lic["key"] == primary_key:
                continue
            for user_id in lic.get("userKeys", []):
                if user_id not in primary_users:
                    try:
                        move_user_to_license(user_id, primary_key, api_base_url, headers)
                        logger.info(f"Moved user {user_id} to license {primary_key}")
                        delete_license(lic["key"], api_base_url, headers)
                        logger.info(f"Deleted license {lic['key']}")
                    except Exception as e:
                        logger.error(f"Failed to move user {user_id} or delete license {lic['key']} for account {accountKey}: {e}")

@click.command()
@click.option("--url", default="http://localhost:8080/account/v2", help="Base URL for the account service API")
@click.option("--partitions", default=10, type=int, help="Number of parallel partitions to scan")
@click.option("--client-name", default="test_provisioner", help="Client name for authentication")
@click.option("--client-secret", required=True, help="Client secret for authentication")
def main(
    url: str,
    partitions: int,
    client_name: str,
    client_secret: Optional[str]):

    api_base_url = url
    headers = {"ClientName": client_name, "ClientSecret": client_secret}

    all_licenses = asyncio.run(parallel_fetch_licenses(ROLE_NAME, partitions, api_base_url, headers))
    accounts = defaultdict(list)
    for lic in all_licenses:
        if lic.get("enabled", True):
            accounts[lic["accountKey"]].append(lic)
    account_keys = list(accounts.keys())
    for i in range(0, len(account_keys), BATCH_SIZE):
        batch_keys = account_keys[i:i+BATCH_SIZE]
        batch_accounts = {k: accounts[k] for k in batch_keys}
        process_account_licenses(batch_accounts, api_base_url, headers)

if __name__ == "__main__":
    main()