#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
# "click",
# "boto3",
# "tabulate"
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


def generate_sid(account_id, label=None):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    if label:
        return f"{label}-{account_id}-{timestamp}"
    return f"SubscriptionPermission-{account_id}-{timestamp}"


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


def add_permission_to_topic_via_policy(sns_client, topic_arn, account_id, sid=None):
    arn = f"arn:aws:iam::{account_id}:root"
    if not sid:
        sid = generate_sid(account_id)
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
            if "SNS:Subscribe" not in actions:
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
@click.option("--label", help="Custom label for the permission")
@click.pass_context
def add_permission(ctx, account, events, label):
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
    sid = generate_sid(account_id, label)
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
    type=click.Choice(["table", "json"]),
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


if __name__ == "__main__":
    cli(obj={})
