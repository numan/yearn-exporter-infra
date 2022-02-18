#!/usr/bin/env python3
import os

import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
)
from constructs import Construct

from yearn_apy_exporter_infra.yearn_apy_exporter_infra_stack import (
    YearnApyExporterInfraStack,
)


class YarnApyExporterInfraApp(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vpc = ec2.Vpc(
            self,
            "VPC",
            max_azs=1,
        )

        YearnApyExporterInfraStack(
            self, "YearnApyExporterInfraStack", vpc=vpc, **kwargs
        )


app = cdk.App()

YarnApyExporterInfraApp(
    app,
    "YarnApyExporterInfraApp",
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION"),
    ),
)
app.synth()
