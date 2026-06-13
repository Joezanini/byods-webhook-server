#!/usr/bin/env python3
"""CDK application entrypoint for BYODS webhook + BYOVA gRPC on ECS Fargate."""

from __future__ import annotations

import os

import aws_cdk as cdk

from stack import ByodsWebhookStack

app = cdk.App()

domain_name = app.node.try_get_context("domain") or "atozbuildingcrm.com"
hooks_subdomain = app.node.try_get_context("hooksSubdomain") or "hooks"
media_subdomain = app.node.try_get_context("mediaSubdomain") or "media"

ByodsWebhookStack(
    app,
    "ByodsWebhookStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
    domain_name=domain_name,
    hooks_hostname=f"{hooks_subdomain}.{domain_name}",
    media_hostname=f"{media_subdomain}.{domain_name}",
)

app.synth()
