#!/usr/bin/env python3
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
from collections import deque
from typing import List, Tuple, Dict, Any, Optional
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

def parse_filters(filter_args: Optional[List[str]]) -> List[Tuple[str, str]]:
    filters = []
    for f in filter_args or []:
        if "=" in f:
            key, value = f.split("=", 1)
            filters.append((key.strip(), value.strip()))
    return filters

def event_matches_filters(event_data: Dict[str, Any], filters: List[Tuple[str, str]]) -> bool:
    for key, value in filters:
        if str(event_data.get(key, "")) != value:
            return False
    return True

def monitor_queue(event: str, host: str, consumer: str, color: str, event_log: deque, max_events: int = 50, polling_interval: float = 1.0, request_timeout: float = 10.0, log_file_path: Optional[str] = None, filters: Optional[List[Tuple[str, str]]] = None) -> None:
    queue = f'account.service.events.{event}+'
    url = f'http://{host}/queue/rest2/{queue}{consumer}'
    while True:
        try:
            res = httpx.get(url, timeout=request_timeout)
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
                
                # Log to file if specified and event matches filters (if any)
                if log_file_path:
                    should_log = True
                    if filters and isinstance(data, dict):
                        should_log = event_matches_filters(data, filters)
                    
                    if should_log:
                        log_entry = f"[{timestamp}] {event} | {event_type} | {event_details}\n"
                        try:
                            with open(log_file_path, 'a', encoding='utf-8') as f:
                                f.write(log_entry)
                        except Exception as log_err:
                            pass  # Don't let logging errors break monitoring
                
                while len(event_log) > max_events:
                    event_log.popleft()
        except (httpx.TimeoutException, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            time.sleep(polling_interval)
            continue
        except httpx.RequestError as e:
            err_str = str(e)
            log_color = color
            event_log.append({
                "queue": event,
                "color": log_color,
                "timestamp": datetime.datetime.now().strftime(TIMESTAMP_FORMAT),
                "event_type": "REQUEST_ERROR",
                "event_details": err_str,
                "raw": err_str,
            })
            
            # Log error to file if specified
            if log_file_path:
                log_entry = f"[{datetime.datetime.now().strftime(TIMESTAMP_FORMAT)}] {event} | REQUEST_ERROR | {err_str}\n"
                try:
                    with open(log_file_path, 'a', encoding='utf-8') as f:
                        f.write(log_entry)
                except Exception:
                    pass
            
            while len(event_log) > max_events:
                event_log.popleft()
            time.sleep(polling_interval)
            continue
        except Exception as e:
            err_str = str(e)
            log_color = color
            event_log.append({
                "queue": event,
                "color": log_color,
                "timestamp": datetime.datetime.now().strftime(TIMESTAMP_FORMAT),
                "event_type": "ERROR",
                "event_details": err_str,
                "raw": err_str,
            })
            
            # Log general error to file if specified  
            if log_file_path:
                log_entry = f"[{datetime.datetime.now().strftime(TIMESTAMP_FORMAT)}] {event} | ERROR | {err_str}\n"
                try:
                    with open(log_file_path, 'a', encoding='utf-8') as f:
                        f.write(log_entry)
                except Exception:
                    pass
            
            while len(event_log) > max_events:
                event_log.popleft()
        time.sleep(polling_interval)

def render_table(event_logs: deque, color_map: Dict[str, str], env_name: str, event_list: List[str], filters: Optional[List[Tuple[str, str]]] = None) -> Table:
    title = f"Environment: {env_name.upper()} | Queues: {', '.join(event_list)}"
    if filters:
        filter_desc = ", ".join([f"{k}={v}" for k, v in filters])
        title += f" | Filters: {filter_desc}"
    table = Table(title=title, expand=True)
    table.add_column("Queue", style="bold", min_width=10, max_width=20, no_wrap=True)
    table.add_column("Timestamp", min_width=15, max_width=25, no_wrap=True)
    table.add_column("Event Type", min_width=10, max_width=20, no_wrap=True)
    table.add_column("Event Details", overflow="fold", no_wrap=False, ratio=1)
    
    for log in event_logs:
        # If filters are specified, only show events that match
        if filters:
            if not (log.get("raw") and isinstance(log["raw"], dict) and event_matches_filters(log["raw"], filters)):
                continue
        
        queue = Text(str(log["queue"]), style=color_map[log["queue"]])
        timestamp = Text(str(log["timestamp"]))
        event_type = Text(str(log["event_type"]))
        details = Text(str(log["event_details"]), style=log["color"])
        table.add_row(
            queue,
            timestamp,
            event_type,
            details
        )
    return table

def main() -> None:
    parser = argparse.ArgumentParser(description="Read events from one or more account service event queues concurrently.")
    event_list = ", ".join(ALLOWED_EVENTS)
    parser.add_argument(
        "event",
        nargs="+",
        help=f"Event(s) for the queue(s). Valid options: {event_list}"
    )
    parser.add_argument("--client", default=None, help="Client name for the queue (default: jupyter-<timestamp>)")
    parser.add_argument("--env", choices=ENV_HOSTS.keys(), default="ed1", type=str.lower, help="Environment to use (ed1, rc1, stage, live). Default: ed1")
    parser.add_argument("--filter", action="append", help="Only show events where field=value (can be specified multiple times)")
    parser.add_argument("--max-events", type=int, default=50, help="Maximum number of events to keep in memory (default: 50)")
    parser.add_argument("--polling-interval", type=float, default=1.0, help="Polling interval in seconds (default: 1.0)")
    parser.add_argument("--request-timeout", type=float, default=10.0, help="HTTP request timeout in seconds (default: 10.0)")
    parser.add_argument("--refresh-rate", type=int, default=2, help="Table refresh rate per second (default: 2)")
    parser.add_argument("--log-file", type=str, help="Path to log file for plain text output")
    parser.add_argument("--no-display", action="store_true", help="Disable table display, only log to file (requires --log-file)")
    args = parser.parse_args()

    filters = parse_filters(args.filter)
    
    if args.no_display and not args.log_file:
        print("Error: --no-display requires --log-file to be specified")
        sys.exit(1)

    if filters:
        filter_desc = f"Filtering events where: {', '.join([f'{k}={v}' for k, v in filters])}"
        print(filter_desc)
        if not args.no_display:
            print("Only matching events will be displayed.")
        print()

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

    event_logs: deque = deque()
    threads = []
    for event in args.event:
        color = color_map[event]
        t = threading.Thread(target=monitor_queue, args=(event, host, consumer, color, event_logs, args.max_events, args.polling_interval, args.request_timeout, args.log_file, filters), daemon=True)
        t.start()
        threads.append(t)

    if args.log_file:
        print(f"Logging events to: {args.log_file}")
        
    if args.no_display:
        print("Running in file-only mode. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nExiting...")
    else:
        console = Console()
        try:
            with Live(render_table(event_logs, color_map, args.env, args.event, filters), console=console, refresh_per_second=args.refresh_rate) as live:
                while True:
                    live.update(render_table(event_logs, color_map, args.env, args.event, filters))
                    time.sleep(0.5 / args.refresh_rate)
        except KeyboardInterrupt:
            print("Exiting...")

if __name__ == "__main__":
    main()
