# IAM Tools Suite

This directory contains command lines tools created in response to questions. 

**Each python tool can be run using [`uv`](https://github.com/astral-sh/uv):**
`uv` will manage the environment and dependency installation. This is the recommended approach.
> `uv run <script>.py [options]`
> `uv run <link to raw github py> [options]`

**Install `uv` if not present:**

```bash
brew install uv
```
or 
```bash
curl -Ls https://astral.sh/uv/install.sh | sh
```

**See [Raw Github](https://raw.githubusercontent.com/your-org/your-repo/main/path/to/script.py) for direct script links.**

## 🛠️ Tool List (with quick descriptions)

- **aws_download_s3_access_logs.sh** – Download and extract ALB access logs from S3; scan for HTTP 50x errors.
- **awsencrypt.sh** – Encrypt a value using AWS KMS CLI.
- **awslogin.sh** – Simplify AWS SSO login and export env vars.
- **read_queue_events.py** – Live-tail and filter events from account service event queues (rich output).
- **scan-for-account-attributes.py** – Parallel attribute-based scan of ALL accounts; outputs CSV/JSON.
- **scan-for-license-attributes.py** – Parallel attribute-based scan of LAL licenses; outputs CSV/JSON.
- **stage-to-live-licenseUser-assignment.py** – Copy missing license->user assignments from Stage to Live for an account.
- **template-to-confluence.py** – Convert SKU Template JSON definitions to Confluence HTML tables.
- **update-oauth-client.py** – Safely PATCH and diff OAuth portal client config; outputs changes.
- **validate_fulfillment.py** – Check if fulfillment JSON covers all required/provided SKU dependency constraints.

---

## Script Details & Help Output

---

### 📝 aws_download_s3_access_logs.sh

> Download and extract ALB access logs from S3; scan for HTTP 50x errors.

**Usage (executable):**

```bash
uv run aws_download_s3_access_logs.sh <region> <YYYY/MM/DD> <S3 prefix path>
```

**Help:**
```text
Usage: ./aws_download_s3_access_logs.sh <region> <YYYY/MM/DD> <S3 prefix path>
Example: ./aws_download_s3_access_logs.sh us-east-1 2023/02/25 iam-live-alb-access-logs/AWSLogs/663917429408/elasticloadbalancing
```

---

### 🔑 awsencrypt.sh

> Encrypt a value using AWS KMS CLI.

**Usage:**
```bash
uv run awsencrypt.sh <PLAINTEXT> [aws-profile] [output-format]
```

---

### 🔐 awslogin.sh

> Simplify AWS SSO login and export env vars. Default profile is 'default'. 
> Creates ~/.aws/credentials and writes AWS_* env vars

**Usage:**
```bash
uv run awslogin.sh [profile]
```

---

### 📡 read_queue_events.py

> Live-tail and filter events from account service event queues (with colors and filtering).

**Usage:**
```bash
uv run read_queue_events.py EVENT1 [EVENT2 ...] [--env ed1|rc1|stage|live] [--client NAME] [--filter field=value]
```

**Help Output:**
```text
usage: read_queue_events.py [-h] [--client CLIENT] [--env {ed1,rc1,stage,live}] [--filter FILTER] event [event ...]

Read events from one or more account service event queues concurrently.

positional arguments:
  event                  Event(s) for the queue(s). Valid options: users, usersettings, licenses, licenseentitlements, licenseusers, accounts, accountsettings, accountusers, accountuserroles, accountplans, organizationusers, organizationdomains, plans, plansettings, groups, groupusers, rolesetusers

options:
  -h, --help             show this help message and exit
  --client CLIENT        Client name for the queue (default: jupyter-<timestamp>)
  --env {ed1,rc1,stage,live}
                        Environment to use (ed1, rc1, stage, live). Default: ed1
  --filter FILTER        Highlight events where field=value (can be specified multiple times)
```

---

### 🕵️ scan-for-account-attributes.py

> Parallel attribute-based scan of ALL accounts; outputs CSV/JSON.

**Usage:**
```bash
uv run scan-for-account-attributes.py --name ATTR --value JSON_VALUE [other options]
```

**Help Output:**
```text
Usage: scan-for-account-attributes.py [OPTIONS]

  Scan accounts by attribute in parallel across the entire key space.

  Example:
  $ python scan_accounts.py --name "country" --value '"US"' --output results.csv

Options:
  --url TEXT                Base URL for the account service API [default: https://accsvced1uswest2.serversdev.getgo.com/v2]
  --name TEXT               Attribute name to search for [required]
  --value TEXT              JSON value to search for (in quotes for strings) [required]
  --product TEXT            Optional product context for the scan
  --client-name TEXT        Client name for authentication [default: test_provisioner]
  --client-secret TEXT      Client secret for authentication
  --partitions INTEGER      Number of parallel partitions to scan [default: 10]
  --count INTEGER           Maximum number of results per request (1-100) [default: 100]
  --attribute-names TEXT    Optional comma-separated list of attribute names to return
  --output, -o TEXT         Output file path (CSV format)
  --help                    Show this message and exit.
```

---

### 🕵️‍♂️ scan-for-license-attributes.py

> Parallel scan of all licenses by attribute (nearly identical workflow as account scan).

**Usage:**
```bash
uv run scan-for-license-attributes.py --name ATTR --value JSON_VALUE [other options]
```

**Help Output:**
```text
Usage: scan-for-license-attributes.py [OPTIONS]

  Scan licenses by attribute in parallel across the entire key space.

  Example:
  $ python scan_licenses.py --name "sku" --value '"G2CStandardU"' --output results.csv

Options:
  --url TEXT                Base URL for the account service API [default: https://accsvced1uswest2.serversdev.getgo.com/v2]
  --name TEXT               Attribute name to search for [required]
  --value TEXT              JSON value to search for (in quotes for strings) [required]
  --product TEXT            Optional product context for the scan
  --client-name TEXT        Client name for authentication [default: test_provisioner]
  --client-secret TEXT      Client secret for authentication
  --partitions INTEGER      Number of parallel partitions to scan [default: 10]
  --count INTEGER           Maximum number of results per request (1-100) [default: 100]
  --attribute-names TEXT    Optional comma-separated list of attribute names to return
  --output, -o TEXT         Output file path (CSV format)
  --help                    Show this message and exit.
```

---

### 🔁 stage-to-live-licenseUser-assignment.py

> Copy missing license->user assignments from Stage to Live for an account.

**Usage:**
```bash
uv run stage-to-live-licenseUser-assignment.py --account-key <key> --stage-client-name ... --live-client-name ... [other options]
```

**Help Output (partial, see --help):**
```text
Usage: stage-to-live-licenseUser-assignment.py [OPTIONS]

  Compares licenses between Stage and Live environments, finds missing userkeys,
  validates users exist in Live account, and assigns those users to the corresponding
  licenses in Live.

Options:
  --account-key TEXT           Account key to process. [required]
  --stage-client-name TEXT     Stage environment Client Name for authentication. [required]
  --stage-client-secret TEXT   Stage environment Client Secret for authentication. [required]
  --live-client-name TEXT      Live environment Client Name for authentication. [required]
  --live-client-secret TEXT    Live environment Client Secret for authentication. [required]
  --stage-base-url TEXT        Stage environment base URL. [default: ...]
  --live-base-url TEXT         Live environment base URL. [default: ...]
  --timeout FLOAT              HTTP request timeout in seconds. [default: 30.0]
  --delay FLOAT                Delay in seconds between API calls. [default: 0.1]
  -v, --verbose                Print success messages.
  --dry-run                    Only show what would be done without changes.
  --help                       Show this message and exit.
```

---

### 🗂️ template-to-confluence.py

> Convert SKU JSON definitions to Confluence HTML tables.

**Usage:**
```bash
uv run template-to-confluence.py skus.json --output skus.html
```

**Help Output:**
```text
Usage: template-to-confluence.py [OPTIONS] JSON_FILE

  Convert JSON SKU definitions to Confluence HTML tables.

Options:
  --output, -o FILE         Output HTML file [default: -]
  --validate / --no-validate
                            Validate SKU data against schema [default: validate]
  --help                    Show this message and exit.
```

---

### 🧬 update-oauth-client.py

> Safely PATCH and diff OAuth portal client config; outputs a clear diff of changes.

**Usage:**
```bash
uv run update-oauth-client.py --username USER --password PASS --env ... --client_id ID --client_secret ... --update_client_id CID [OPTIONS]
```

**Help Output:**
```text
Usage: update-oauth-client.py [OPTIONS]

  Authenticate and update an existing client.

Options:
  --username TEXT             Your OAuth username. [required]
  --password TEXT             Your OAuth password. [required]
  --env [ed1|rc1|stage|live]  Deployment environment. [required]
  --client_id TEXT            The client ID to authenticate with. [required]
  --client_secret TEXT        The client secret to authenticate with. [required]
  --scopes TEXT               Comma-separated list of scopes.
  --grant_types TEXT          Comma-separated list of grant types.
  --roles TEXT                Comma-separated list of roles.
  --implicit_scopes TEXT      Comma-separated list of implicit scopes.
  --update_client_id TEXT     The client ID to update. [required]
  --update_data FILENAME      File with JSON of update values.
  --show-full-json            Show full JSON of before/after client state
  --help                      Show this message and exit.
```

---

### 🧾 validate_fulfillment.py

> Validates an OFS Request log entry from Splunk/SumoLogic to determine why an error occurred.

**Usage:**
```bash
uv run validate_fulfillment.py fulfillment.json
```

**Help Output:**
```text
usage: validate_fulfillment.py [-h] fulfillment_file

Validate fulfillment request log JSON to determine why an error occurred.

positional arguments:
  fulfillment_file   Path to the fulfillment JSON file

options:
  -h, --help         show this help message and exit
