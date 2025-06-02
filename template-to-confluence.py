# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "click",
# ]
# ///

import click
import json
from html import escape

def generate_sku_attributes_table(sku_data):
    """Generate HTML table for SKU attributes."""
    table = '<h3>SKU Attributes</h3>\n'
    table += '<table class="wrapped relative-table" style="width: 35%;">\n'
    table += '  <colgroup>\n'
    table += '    <col style="width: 38%;"/>\n'
    table += '    <col style="width: 62%;"/>\n'
    table += '  </colgroup>\n'
    table += '  <tbody>\n'
    table += '    <tr>\n'
    table += '      <th scope="col">Name</th>\n'
    table += '      <th scope="col">Value</th>\n'
    table += '    </tr>\n'

    # First set of standard SKU attributes - core attributes
    primary_attributes = [
        "skuName",
        "product",
        "isAccountAttributeSku",
        "isAddonSku",
        "requires"
    ]

    for attr in primary_attributes:
        if attr in sku_data:
            value = sku_data[attr]
            # Format lists as comma-separated strings
            if isinstance(value, list):
                value = ", ".join(value)
            # Convert booleans to string
            elif isinstance(value, bool):
                value = str(value).lower()

            table += f'    <tr>\n'
            table += f'      <td>{attr}</td>\n'
            table += f'      <td>{escape(str(value))}</td>\n'
            table += f'    </tr>\n'

    # Second set of attributes - flags and special attributes
    secondary_attributes = [
        "isUnifiedAdmin",
        "isLegacySku",
        "isUnlimitedSku",
        "isChildSku",
        "isBilledByLicense",
        "childSkus",
        "addonSkus",
        "addonProducts",
        "arhMultiplier",
        "integrations"
    ]

    for attr in secondary_attributes:
        if attr in sku_data:
            value = sku_data[attr]
            # Format lists as comma-separated strings
            if isinstance(value, list):
                value = ", ".join(value)
            # Convert booleans to string
            elif isinstance(value, bool):
                value = str(value).lower()

            table += f'    <tr>\n'
            table += f'      <td>{attr}</td>\n'
            table += f'      <td>{escape(str(value))}</td>\n'
            table += f'    </tr>\n'

    # Third set - constraint modelling attributes
    constraint_attributes = ["provides", "exclusivities"]

    for attr in constraint_attributes:
        if attr in sku_data:
            value = sku_data[attr]
            if isinstance(value, list):
                value = ", ".join(value)

            table += f'    <tr>\n'
            table += f'      <td>{attr}</td>\n'
            table += f'      <td>{escape(str(value))}</td>\n'
            table += f'    </tr>\n'

    # Add any other attributes (except the special sections)
    special_keys = [
        "licenseAttributes",
        "accountEntitlements",
        "licenseEntitlements",
        "persistentAccountEntitlements"
    ] + primary_attributes + secondary_attributes + constraint_attributes

    for attr in sku_data:
        if attr not in special_keys:
            value = sku_data[attr]
            if isinstance(value, list):
                value = ", ".join(value)
            elif isinstance(value, bool):
                value = str(value).lower()

            table += f'    <tr>\n'
            table += f'      <td>{attr}</td>\n'
            table += f'      <td>{escape(str(value))}</td>\n'
            table += f'    </tr>\n'

    table += '  </tbody>\n'
    table += '</table>\n'
    return table

def generate_license_attributes_table(license_data):
    """Generate HTML table for license attributes."""
    if not license_data:
        return ""

    table = '<h3>License Attributes</h3>\n'
    table += '<table class="wrapped relative-table" style="width: 35%;">\n'
    table += '  <colgroup>\n'
    table += '    <col style="width: 38%;"/>\n'
    table += '    <col style="width: 62%;"/>\n'
    table += '  </colgroup>\n'
    table += '  <tbody>\n'
    table += '    <tr>\n'
    table += '      <th scope="col">Name</th>\n'
    table += '      <th scope="col">Value</th>\n'
    table += '    </tr>\n'

    # Order the attributes in a logical way
    primary_attributes = ["description", "type", "roles"]
    secondary_attributes = [
        "arhFlag",
        "devicesOnly",
        "devicesAllowed",
        "externallyManaged",
        "label",
        "lowUsage",
        "tier"
    ]

    # First add the primary attributes
    for attr in primary_attributes:
        if attr in license_data:
            value = license_data[attr]
            if isinstance(value, list):
                value = ", ".join(value)
            elif isinstance(value, bool):
                value = str(value).lower()

            table += f'    <tr>\n'
            table += f'      <td>{attr}</td>\n'
            table += f'      <td>{escape(str(value))}</td>\n'
            table += f'    </tr>\n'

    # Then add the secondary attributes
    for attr in secondary_attributes:
        if attr in license_data:
            value = license_data[attr]
            if isinstance(value, list):
                value = ", ".join(value)
            elif isinstance(value, bool):
                value = str(value).lower()

            table += f'    <tr>\n'
            table += f'      <td>{attr}</td>\n'
            table += f'      <td>{escape(str(value))}</td>\n'
            table += f'    </tr>\n'

    # Add any remaining custom attributes
    special_keys = primary_attributes + secondary_attributes
    for attr in license_data:
        if attr not in special_keys:
            value = license_data[attr]
            if isinstance(value, list):
                value = ", ".join(value)
            elif isinstance(value, bool):
                value = str(value).lower()

            table += f'    <tr>\n'
            table += f'      <td>{attr}</td>\n'
            table += f'      <td>{escape(str(value))}</td>\n'
            table += f'    </tr>\n'

    table += '  </tbody>\n'
    table += '</table>\n'
    return table

def generate_entitlements_table(entitlements, title):
    """Generate HTML table for entitlements (license, account, persistent account)."""
    if not entitlements:
        return ""

    table = f'<h3>{title}</h3>\n'
    table += '<table class="wrapped">\n'
    table += '  <colgroup>\n'
    table += '    <col/>\n'
    table += '    <col/>\n'
    table += '    <col/>\n'
    table += '  </colgroup>\n'
    table += '  <tbody>\n'
    table += '    <tr>\n'
    table += '      <th scope="col">Name</th>\n'
    table += '      <th scope="col">Product</th>\n'
    table += '      <th scope="col">Value</th>\n'
    table += '    </tr>\n'

    for product, attrs in entitlements.items():
        for name, value in attrs.items():
            if isinstance(value, bool):
                value = str(value).lower()

            table += f'    <tr>\n'
            table += f'      <td>{name}</td>\n'
            table += f'      <td>{product}</td>\n'
            table += f'      <td>{escape(str(value))}</td>\n'
            table += f'    </tr>\n'

    table += '  </tbody>\n'
    table += '</table>\n'
    return table

def generate_all_tables_for_sku(sku_data):
    """Generate all tables for a single SKU."""
    result = f'<h2>{sku_data["skuName"]}</h2>\n'
    result += generate_sku_attributes_table(sku_data)

    if "licenseAttributes" in sku_data:
        result += generate_license_attributes_table(sku_data["licenseAttributes"])

    if "licenseEntitlements" in sku_data:
        result += generate_entitlements_table(sku_data["licenseEntitlements"], "License Entitlements")

    if "accountEntitlements" in sku_data:
        result += generate_entitlements_table(sku_data["accountEntitlements"], "Account Entitlements")

    if "persistentAccountEntitlements" in sku_data:
        result += generate_entitlements_table(sku_data["persistentAccountEntitlements"], "Persistent Account Entitlements")

    return result

def validate_sku_data(sku_data):
    """Validate that required SKU fields are present."""
    required_fields = ["skuName", "product", "licenseAttributes"]
    missing_fields = [field for field in required_fields if field not in sku_data]

    if missing_fields:
        return False, f"Missing required fields: {', '.join(missing_fields)}"

    if "licenseAttributes" in sku_data and "description" not in sku_data["licenseAttributes"]:
        return False, "Missing required field in licenseAttributes: description"

    return True, None

@click.command()
@click.argument('json_file', type=click.File('r'))
@click.option('--output', '-o', type=click.File('w'), default='-', help='Output HTML file')
@click.option('--validate/--no-validate', default=True, help='Validate SKU data against schema')
def main(json_file, output, validate):
    """Convert JSON SKU definitions to Confluence HTML tables.

    This tool formats SKU definitions into HTML tables that can be pasted into Confluence.
    It handles all the attributes defined in the SKU schema documentation.
    """
    try:
        data = json.load(json_file)
    except json.JSONDecodeError:
        click.echo("Error: Invalid JSON format", err=True)
        return

    if not isinstance(data, list):
        # Handle a single SKU case
        data = [data]

    output.write('<h1>SKU Definitions</h1>\n')

    skus_processed = 0
    for sku in data:
        if validate:
            is_valid, error_message = validate_sku_data(sku)
            if not is_valid:
                click.echo(f"Warning: SKU {sku.get('skuName', 'unknown')} validation failed: {error_message}", err=True)
                continue

        html_tables = generate_all_tables_for_sku(sku)
        output.write(html_tables)
        output.write('<hr>\n')
        skus_processed += 1

    click.echo(f"Successfully generated HTML tables for {skus_processed} SKUs", err=True)

if __name__ == "__main__":
    main()