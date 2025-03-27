# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx"
# ]
# ///

import json
import httpx
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_fulfillment(file_path):
    """
    Load and parse the fulfillment JSON file.
    """
    try:
        with open(file_path, 'r') as file:
            fulfillment = json.load(file)
        logging.info("Fulfillment JSON loaded successfully.")
        return fulfillment
    except Exception as e:
        logging.error(f"Error loading fulfillment JSON: {e}")
        sys.exit(1)


def fetch_sku_catalog(url):
    """
    Fetch and parse the SKU catalog from the provided webpage URL.
    Assumes the webpage returns JSON data.
    """
    try:
        response = httpx.get(url)
        response.raise_for_status()
        parsed_response = response.text.replace("skus = ", "").replace(";", "")
        logging.info("SKU catalog fetched successfully.")
        return json.loads(parsed_response)
    except Exception as e:
        logging.error(f"Error fetching SKU catalog: {e}")
        sys.exit(1)


def get_enabled_skus(fulfillment):
    """
    Extract enabled SKUs from the fulfillment JSON.
    Assumes enabled SKUs are listed under 'state' -> 'acctLicenses' with 'enabled': true.
    Also includes SKUs that are projected to be enabled under 'enabledProjected': true.
    """
    try:
        acct_licenses = fulfillment.get('state', {}).get('acctLicenses', [])
        enabled_skus = [
            license_entry['sku']
            for license_entry in acct_licenses
            if license_entry.get('enabled', False) or license_entry.get('enabledProjected', False)
        ]
        logging.info(f"Found {len(enabled_skus)} enabled or projected SKUs.")
        return enabled_skus
    except Exception as e:
        logging.error(f"Error extracting enabled SKUs: {e}")
        sys.exit(1)


def build_sku_dict(sku_catalog):
    """
    Build a dictionary mapping skuName to its details for quick lookup.
    """
    sku_dict = {}
    for sku in sku_catalog:
        sku_name = sku.get('skuName')
        if sku_name:
            sku_dict[sku_name] = sku
    logging.info(f"SKU dictionary built with {len(sku_dict)} entries.")
    return sku_dict


def extract_requirements_provides(enabled_skus, sku_dict):
    """
    Extract and aggregate 'requires' and 'provides' from enabled SKUs.
    """
    requires = set()
    provides = set()

    for sku in enabled_skus:
        sku_info = sku_dict.get(sku)
        if not sku_info:
            logging.warning(f"SKU '{sku}' not found in catalog.")
            continue

        # Extract requires
        sku_requires = sku_info.get('requires', [])
        if sku_requires:
            requires.update(sku_requires)
            logging.debug(f"SKU '{sku}' requires: {sku_requires}")

        # Extract provides
        sku_provides = sku_info.get('provides', [])
        if sku_provides:
            provides.update(sku_provides)
            logging.debug(f"SKU '{sku}' provides: {sku_provides}")

    logging.info(f"Aggregated requires: {requires}")
    logging.info(f"Aggregated provides: {provides}")
    return requires, provides


def main(fulfillment_file: str):
    sku_catalog_url = 'https://iamdocs.serversdev.getgo.com/fs/live/skus.js'

    # Load fulfillment JSON
    fulfillment = load_fulfillment(fulfillment_file)

    # Fetch SKU catalog from webpage
    sku_catalog = fetch_sku_catalog(sku_catalog_url)

    # Build SKU dictionary for quick lookup
    sku_dict = build_sku_dict(sku_catalog)

    # Get enabled and projected SKUs from fulfillment
    enabled_skus = get_enabled_skus(fulfillment)

    # Extract and aggregate requires and provides
    requires, provides = extract_requirements_provides(enabled_skus, sku_dict)

    # Determine missing requirements
    missing_requirements = requires - provides

    if missing_requirements:
        logging.error(f"SKU requirement missing: {missing_requirements}")
        print("Verification Failed:")
        print("Missing Requirements:")
        for req in missing_requirements:
            print(f"- {req}")
        sys.exit(1)
    else:
        logging.info("All SKU requirements are satisfied.")
        print("Verification Successful: All SKU requirements are satisfied.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate fulfillment JSON against SKU catalog.")
    parser.add_argument("fulfillment_file", help="Path to the fulfillment JSON file")
    args = parser.parse_args()

    main(args.fulfillment_file)