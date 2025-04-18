# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "httpx", 
#   "rich"
# ]
# ///

import httpx
import datetime
import time
import argparse
import sys
import json
import threading
from rich.live import Live
from rich.table import Table
from rich.console import Console
from rich.text import Text

TIMESTAMP_FORMAT = "%b %d %H:%M:%S"

ALLOWED_EVENTS = [
    "users", "usersettings", "licenses", "licenseentitlements", "licenseusers",
    "accounts", "accountsettings", "accountusers", "accountuserroles", "accountplans",
    "organizationusers", "organizationdomains", "plans", "plansettings", "groups",
    "groupusers", "rolesetusers"
]

ENV_HOSTS = {
    "ed1": "ed1.queue1svc.qai.expertcity.com",
    "rc1": "queue1rc1svc.qai.expertcity.com",
    "stage": "queuestagesvc.las.expertcity.com",
    "live": "queuesvc.las.expertcity.com"
}

def monitor_queue(event, host, consumer, color, event_log, max_events=50):
    queue = f'account.service.events.{event}+'
    url = f'http://{host}/queue/rest2/{queue}{consumer}'
    while True:
        try:
            res = httpx.get(url)
            if res.text:
                try:
                    data = json.loads(res.text)
                    ts = data.get("timestamp")
                    if ts:
                        try:
                            ts_int = int(ts)
                            dt = datetime.datetime.fromtimestamp(ts_int / 1000)
                            timestamp = dt.strftime(TIMESTAMP_FORMAT)
                        except Exception:
                            timestamp = str(ts)
                    else:
                        timestamp = datetime.datetime.now().strftime(TIMESTAMP_FORMAT)
                    event_type = data.get("eventType") or data.get("type") or ""
                    event_details = json.dumps(data, ensure_ascii=False)
                    log_color = color
                except Exception:
                    data = res.text
                    timestamp = datetime.datetime.now().strftime(TIMESTAMP_FORMAT)
                    event_type = ""
                    event_details = str(data)
                    log_color = color
                event_log.append({
                    "queue": event,
                    "color": log_color,
                    "timestamp": timestamp,
                    "event_type": event_type,
                    "event_details": event_details,
                    "raw": data,
                })
                if len(event_log) > max_events:
                    del event_log[0:len(event_log)-max_events]
        except Exception as e:
            err_str = str(e)
            if "timeout" in err_str.lower():
                time.sleep(1)
                continue
            log_color = color
            event_log.append({
                "queue": event,
                "color": log_color,
                "timestamp": datetime.datetime.now().strftime(TIMESTAMP_FORMAT),
                "event_type": "ERROR",
                "event_details": err_str,
                "raw": err_str,
            })
            if len(event_log) > max_events:
                del event_log[0:len(event_log)-max_events]
        time.sleep(1)

def render_table(event_logs, color_map, env_name, event_list):
    title = f"Environment: {env_name.upper()} | Queues: {', '.join(event_list)}"
    table = Table(title=title, expand=True)
    table.add_column("Queue", style="bold", min_width=6, max_width=10, no_wrap=True)
    table.add_column("Timestamp", min_width=25, max_width=19, no_wrap=True)
    table.add_column("Event Type", min_width=10, max_width=16, no_wrap=True)
    table.add_column("Event Details", overflow="fold", no_wrap=False, ratio=1)
    for log in event_logs:
        queue = Text(str(log["queue"]), style=color_map[log["queue"]])
        details = Text(str(log["event_details"]), style=log["color"])
        table.add_row(
            queue,
            str(log["timestamp"]),
            str(log["event_type"]),
            details
        )
    return table

def main():
    parser = argparse.ArgumentParser(description="Read events from one or more account service event queues concurrently.")
    event_list = ", ".join(ALLOWED_EVENTS)
    parser.add_argument(
        "event",
        nargs="+",
        help=f"Event(s) for the queue(s). Valid options: {event_list}"
    )
    parser.add_argument("--client", default=None, help="Client name for the queue (default: jupyter-<timestamp>)")
    parser.add_argument("--env", choices=ENV_HOSTS.keys(), default="ed1", type=str.lower, help="Environment to use (ed1, rc1, stage, live). Default: ed1")
    args = parser.parse_args()

    invalid = [e for e in args.event if e not in ALLOWED_EVENTS]
    if invalid:
        print(f"Error: Invalid event(s): {', '.join(invalid)}.\nValid options are: {event_list}")
        sys.exit(1)

    now = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    host = ENV_HOSTS[args.env]
    consumer = args.client if args.client else f'jupyter-{now}'

    # Use rich color names for table styling
    COLORS = [
        "red", "green", "yellow", "blue", "magenta", "cyan", "white"
    ]
    color_map = {}
    for idx, event in enumerate(args.event):
        color_map[event] = COLORS[idx % len(COLORS)]

    event_logs = []
    threads = []
    for event in args.event:
        color = color_map[event]
        t = threading.Thread(target=monitor_queue, args=(event, host, consumer, color, event_logs), daemon=True)
        t.start()
        threads.append(t)

    console = Console()
    try:
        with Live(render_table(event_logs, color_map, args.env, args.event), console=console, refresh_per_second=2) as live:
            while True:
                live.update(render_table(event_logs, color_map, args.env, args.event))
                time.sleep(0.5)
    except KeyboardInterrupt:
        print("Exiting...")

if __name__ == "__main__":
    main()
