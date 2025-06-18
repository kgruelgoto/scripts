#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
# "click",
# "boto3",
# "tabulate",
# "treelib"
# ]
# ///
"""
SNS Subscription Permissions Management CLI Tool
This tool manages subscription permissions for SNS topics that follow the pattern:
bdi-identity-platform-{ENV}-account-service-events-{EVENTS}
"""
import re
import sys
import json
import boto3
import click
import logging
from datetime import datetime
from tabulate import tabulate
from treelib import Tree
from botocore.exceptions import ClientError, ProfileNotFound

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Constants
TOPIC_PATTERN = r"bdi-identity-platform-{env}-account-service-events-{events}"
ACTION = "SNS:Subscribe"
EVENT_TYPES = [
    "users",
    "usersettings",
    "licenses",
    "licenseentitlements",
    "licenseusers",
    "accounts",
    "accountsettings",
    "accountusers",
    "accountuserroles",
    "accountplans",
    "organizationusers",
    "organizationdomains",
    "plans",
    "plansettings",
    "groups",
    "groupusers",
    "rolesetusers",
]


def configure_boto_session(profile, region="us-west-2"):
    """Create and configure boto3 session."""
    try:
        session = boto3.Session(profile_name=profile, region_name=region)
        return session
    except ProfileNotFound:
        logger.error(
            f"AWS profile '{profile}' not found. Check your AWS credentials configuration."
        )
        sys.exit(1)


def get_matching_topics(session, env, events=None):
    sns_client = session.client("sns")
    if events:
        if events not in EVENT_TYPES:
            logger.error(
                f"Invalid event type: {events}. Must be one of: {', '.join(EVENT_TYPES)}"
            )
            sys.exit(1)
        topic_name_pattern = TOPIC_PATTERN.format(env=env, events=events)
    else:
        topic_name_pattern = TOPIC_PATTERN.format(env=env, events=".*")
    regex_pattern = f"^{topic_name_pattern}$".replace("*", ".*")
    topics = []
    paginator = sns_client.get_paginator("list_topics")
    for page in paginator.paginate():
        for topic in page["Topics"]:
            topic_arn = topic["TopicArn"]
            topic_name = topic_arn.split(":")[-1]
            if re.match(regex_pattern, topic_name):
                topics.append(topic_arn)
    if not topics:
        logger.warning(f"No topics found matching pattern: {topic_name_pattern}")
    return topics


def validate_account_id(account_id):
    if not re.match(r"^\d{12}$", account_id):
        logger.error(f"Invalid AWS account ID: {account_id}")
        sys.exit(1)
    return account_id


def get_current_policy(sns_client, topic_arn):
    attrs = sns_client.get_topic_attributes(TopicArn=topic_arn)
    policy_str = attrs["Attributes"].get("Policy")
    if not policy_str:
        # safeguard: AWS expects a `Version` field
        return {"Version": "2008-10-17", "Statement": []}
    try:
        policy = json.loads(policy_str)
        if "Statement" not in policy:
            policy["Statement"] = []
        return policy
    except Exception:
        logger.warning(f"Invalid policy JSON found for {topic_arn}, overwriting it.")
        return {"Version": "2008-10-17", "Statement": []}


def add_permission_to_topic_via_policy(sns_client, topic_arn, account_id, sid):
    arn = f"arn:aws:iam::{account_id}:root"
    try:
        # Get and update policy
        policy = get_current_policy(sns_client, topic_arn)
        # Remove any existing statement with this Sid (replace-once semantics)
        policy["Statement"] = [s for s in policy["Statement"] if s.get("Sid") != sid]
        # Add statement
        statement = {
            "Sid": sid,
            "Effect": "Allow",
            "Principal": {"AWS": arn},
            "Action": "SNS:Subscribe",
            "Resource": topic_arn,
        }
        policy["Statement"].append(statement)
        sns_client.set_topic_attributes(
            TopicArn=topic_arn,
            AttributeName="Policy",
            AttributeValue=json.dumps(policy),
        )
        return {"topic_arn": topic_arn, "sid": sid, "status": "success"}
    except ClientError as e:
        return {"topic_arn": topic_arn, "sid": sid, "status": "error", "error": str(e)}


def remove_permission_from_topic_via_policy(sns_client, topic_arn, sid):
    try:
        policy = get_current_policy(sns_client, topic_arn)
        orig_count = len(policy["Statement"])
        policy["Statement"] = [s for s in policy["Statement"] if s.get("Sid") != sid]
        if len(policy["Statement"]) == orig_count:
            return {"topic_arn": topic_arn, "sid": sid, "status": "not_found"}
        sns_client.set_topic_attributes(
            TopicArn=topic_arn,
            AttributeName="Policy",
            AttributeValue=json.dumps(policy),
        )
        return {"topic_arn": topic_arn, "sid": sid, "status": "success"}
    except ClientError as e:
        return {"topic_arn": topic_arn, "sid": sid, "status": "error", "error": str(e)}


def get_topic_permissions(sns_client, topic_arn, account_filter=None):
    # Read policy and enumerate subscribe permission statements
    permissions = []
    try:
        policy = get_current_policy(sns_client, topic_arn)
        for statement in policy.get("Statement", []):
            # Only interested in SNS:Subscribe grants
            actions = statement.get("Action", [])
            if isinstance(actions, str):
                actions = [actions]
            # Case-insensitive check for SNS:Subscribe
            if not any(a.lower() == "sns:subscribe" for a in actions):
                continue
            principal = statement.get("Principal", {})
            account_id = None
            if isinstance(principal, dict) and "AWS" in principal:
                aws_elems = principal["AWS"]
                accounts = [aws_elems] if isinstance(aws_elems, str) else aws_elems
                for account_arn in accounts:
                    m = re.match(r"arn:aws:iam::(\d{12}):root", account_arn)
                    if m:
                        account_id = m.group(1)
            if account_id and (not account_filter or account_id == account_filter):
                permissions.append(
                    {
                        "topic_arn": topic_arn,
                        "topic_name": topic_arn.split(":")[-1],
                        "sid": statement.get("Sid", "Unknown"),
                        "account_id": account_id,
                        "principal": principal,
                        "action": "SNS:Subscribe",
                    }
                )
        return permissions
    except ClientError as e:
        logger.error(f"Error getting permissions for topic {topic_arn}: {e}")
        return []


def get_topic_subscriptions(sns_client, topic_arn):
    """Get all subscriptions for a given topic."""
    subscriptions = []
    try:
        paginator = sns_client.get_paginator("list_subscriptions_by_topic")
        for page in paginator.paginate(TopicArn=topic_arn):
            for subscription in page["Subscriptions"]:
                sub_info = {
                    "topic_arn": topic_arn,
                    "topic_name": topic_arn.split(":")[-1],
                    "subscription_arn": subscription["SubscriptionArn"],
                    "protocol": subscription["Protocol"],
                    "endpoint": subscription["Endpoint"],
                }
                subscriptions.append(sub_info)
        return subscriptions
    except ClientError as e:
        logger.error(f"Error getting subscriptions for topic {topic_arn}: {e}")
        return []


def format_permissions_as_tree(permissions):
    """Format permissions as a tree."""
    tree = Tree()
    tree.create_node("Permissions", "root")

    # Group permissions by topic
    by_topic = {}
    for p in permissions:
        topic_name = p.get("topic_name")
        if topic_name not in by_topic:
            by_topic[topic_name] = []
        by_topic[topic_name].append(p)

    # Add topics to tree
    for topic_name, topic_permissions in by_topic.items():
        topic_id = f"topic_{topic_name}"
        tree.create_node(f"Topic: {topic_name}", topic_id, parent="root")

        # Add permissions to topic
        for i, p in enumerate(topic_permissions):
            sid = p.get("sid")
            perm_id = f"{topic_id}_perm_{i}"
            tree.create_node(f"SID: {sid}", perm_id, parent=topic_id)

            # Add details to permission
            account_id = p.get("account_id")
            action = p.get("action")
            tree.create_node(
                f"Account: {account_id}", f"{perm_id}_account", parent=perm_id
            )
            tree.create_node(f"Action: {action}", f"{perm_id}_action", parent=perm_id)

    return tree


def format_subscriptions_as_tree(subscriptions):
    """Format subscriptions as a tree."""
    tree = Tree()
    tree.create_node("Subscriptions", "root")

    # Group subscriptions by topic
    by_topic = {}
    for s in subscriptions:
        topic_name = s.get("topic_name")
        if topic_name not in by_topic:
            by_topic[topic_name] = {}

        protocol = s.get("protocol")
        if protocol not in by_topic[topic_name]:
            by_topic[topic_name][protocol] = []

        by_topic[topic_name][protocol].append(s)

    # Add topics to tree
    for topic_name, protocols in by_topic.items():
        topic_id = f"topic_{topic_name}"
        tree.create_node(f"Topic: {topic_name}", topic_id, parent="root")

        # Add protocols to topic
        for protocol, protocol_subscriptions in protocols.items():
            protocol_id = f"{topic_id}_protocol_{protocol}"
            tree.create_node(f"Protocol: {protocol}", protocol_id, parent=topic_id)

            # Add subscriptions to protocol
            for i, s in enumerate(protocol_subscriptions):
                endpoint = s.get("endpoint")
                # Truncate long endpoints for display
                if len(endpoint) > 60:
                    endpoint = endpoint[:57] + "..."
                sub_id = f"{protocol_id}_sub_{i}"
                tree.create_node(f"Endpoint: {endpoint}", sub_id, parent=protocol_id)

                # Add details to subscription
                arn = s.get("subscription_arn")
                tree.create_node(f"ARN: {arn}", f"{sub_id}_arn", parent=sub_id)

    return tree


@click.group()
@click.option("--profile", required=True, default="default", help="AWS profile to use")
@click.option(
    "--env", required=True, default="ed1", help="Environment (ed1, rc1, stage, live)"
)
@click.option("--region", default="us-west-2", help="AWS region")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
@click.pass_context
def cli(ctx, profile, env, region, verbose):
    """Manage SNS topic subscription permissions (cross-account safe)."""
    if verbose:
        logger.setLevel(logging.DEBUG)
    ctx.ensure_object(dict)
    ctx.obj["SESSION"] = configure_boto_session(profile, region)
    ctx.obj["ENV"] = env


@cli.command("add")
@click.option(
    "--account",
    required=True,
    help="AWS **account ID** (12 digits) to grant permission",
)
@click.option(
    "--events",
    type=click.Choice(EVENT_TYPES),
    help="Specific event type. Choices: " + ", ".join(EVENT_TYPES),
)
@click.option("--sid", required=True, help="Statement ID for the permission")
@click.pass_context
def add_permission(ctx, account, events, sid):
    """Add subscription permission to SNS topics (resource policy)."""
    account_id = validate_account_id(account)
    session = ctx.obj["SESSION"]
    env = ctx.obj["ENV"]
    topics = get_matching_topics(session, env, events)
    if not topics:
        logger.error(
            f"No matching topics found for env={env}"
            + (f", events={events}" if events else "")
        )
        sys.exit(1)
    sns_client = session.client("sns")
    results = []
    logger.info(f"Adding permission for {account_id} to {len(topics)} topics...")
    for topic_arn in topics:
        result = add_permission_to_topic_via_policy(
            sns_client, topic_arn, account_id, sid
        )
        results.append(result)
        if result["status"] == "success":
            logger.info(f"✅ Added permission to {topic_arn} with SID: {sid}")
        else:
            logger.error(
                f"❌ Failed to add permission to {topic_arn}: {result.get('error')}"
            )
    successful = sum(1 for r in results if r["status"] == "success")
    logger.info(f"Added permissions to {successful} of {len(topics)} topics.")


@cli.command("remove")
@click.option("--sid", required=True, help="Statement ID to remove")
@click.option(
    "--events",
    type=click.Choice(EVENT_TYPES),
    help="Specific event type. Choices: " + ", ".join(EVENT_TYPES),
)
@click.pass_context
def remove_permission(ctx, sid, events):
    """Remove subscription permission from SNS topics."""
    session = ctx.obj["SESSION"]
    env = ctx.obj["ENV"]
    topics = get_matching_topics(session, env, events)
    if not topics:
        logger.error(
            f"No matching topics found for env={env}"
            + (f", events={events}" if events else "")
        )
        sys.exit(1)
    sns_client = session.client("sns")
    results = []
    logger.info(f"Removing permission with SID {sid} from {len(topics)} topics...")
    for topic_arn in topics:
        result = remove_permission_from_topic_via_policy(sns_client, topic_arn, sid)
        results.append(result)
        if result["status"] == "success":
            logger.info(f"✅ Removed permission from {topic_arn}")
        elif result["status"] == "not_found":
            logger.info(f"ℹ️ SID {sid} not found in topic {topic_arn}")
        else:
            logger.error(
                f"❌ Failed to remove permission from {topic_arn}: {result.get('error')}"
            )
    successful = sum(1 for r in results if r["status"] == "success")
    logger.info(f"Removed permissions from {successful} of {len(topics)} topics.")


@cli.command("list")
@click.option(
    "--events",
    type=click.Choice(EVENT_TYPES),
    help="Specific event type. Choices: " + ", ".join(EVENT_TYPES),
)
@click.option("--account", help="Filter by specific account ID")
@click.option(
    "--output",
    type=click.Choice(["table", "json", "tree"]),
    default="table",
    help="Output format",
)
@click.pass_context
def list_permissions(ctx, events, account, output):
    """List subscription permissions for SNS topics."""
    session = ctx.obj["SESSION"]
    env = ctx.obj["ENV"]
    event_types = [events] if events else EVENT_TYPES
    all_permissions = []
    for event_type in event_types:
        topics = get_matching_topics(session, env, event_type)
        if not topics:
            logger.warning(
                f"No matching topics found for env={env}, events={event_type}"
            )
            continue
        sns_client = session.client("sns")
        for topic_arn in topics:
            permissions = get_topic_permissions(sns_client, topic_arn, account)
            all_permissions.extend(permissions)
    if not all_permissions:
        logger.info("No subscription permissions found matching your criteria.")
        return
    if output == "json":
        click.echo(json.dumps(all_permissions, indent=2, default=str))
    elif output == "tree":
        tree = format_permissions_as_tree(all_permissions)
        tree.show()
    else:  # table output
        table_data = []
        for p in all_permissions:
            table_data.append(
                [
                    p.get("topic_name"),
                    p.get("sid"),
                    p.get("account_id"),
                    p.get("action"),
                ]
            )
        headers = ["Topic Name", "SID", "Account ID", "Action"]
        click.echo(tabulate(table_data, headers=headers, tablefmt="grid"))
    logger.info(f"Found {len(all_permissions)} subscription permissions.")


@cli.command("subscriptions")
@click.option(
    "--events",
    type=click.Choice(EVENT_TYPES),
    help="Specific event type. Choices: " + ", ".join(EVENT_TYPES),
)
@click.option(
    "--protocol",
    help="Filter by subscription protocol (e.g., sqs, lambda, email)",
)
@click.option(
    "--output",
    type=click.Choice(["table", "json", "tree"]),
    default="table",
    help="Output format",
)
@click.pass_context
def list_subscriptions(ctx, events, protocol, output):
    """List subscriptions for SNS topics."""
    session = ctx.obj["SESSION"]
    env = ctx.obj["ENV"]
    event_types = [events] if events else EVENT_TYPES
    all_subscriptions = []

    for event_type in event_types:
        topics = get_matching_topics(session, env, event_type)
        if not topics:
            logger.warning(
                f"No matching topics found for env={env}, events={event_type}"
            )
            continue

        sns_client = session.client("sns")
        for topic_arn in topics:
            subscriptions = get_topic_subscriptions(sns_client, topic_arn)
            # Filter by protocol if specified
            if protocol:
                subscriptions = [
                    s
                    for s in subscriptions
                    if s["protocol"].lower() == protocol.lower()
                ]
            all_subscriptions.extend(subscriptions)

    if not all_subscriptions:
        logger.info("No subscriptions found matching your criteria.")
        return

    if output == "json":
        click.echo(json.dumps(all_subscriptions, indent=2, default=str))
    elif output == "tree":
        tree = format_subscriptions_as_tree(all_subscriptions)
        tree.show()
    else:  # table output
        table_data = []
        for s in all_subscriptions:
            table_data.append(
                [
                    s.get("topic_name"),
                    s.get("protocol"),
                    s.get("endpoint"),
                    s.get("subscription_arn"),
                ]
            )
        headers = ["Topic Name", "Protocol", "Endpoint", "Subscription ARN"]
        click.echo(tabulate(table_data, headers=headers, tablefmt="grid"))

    logger.info(f"Found {len(all_subscriptions)} subscriptions.")


if __name__ == "__main__":
    cli(obj={})
