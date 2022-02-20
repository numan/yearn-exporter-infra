#!/usr/bin/env python3
import json
import os

import aws_cdk as cdk
from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_applicationautoscaling as app_autoscaling
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_efs as efs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from yearn_apy_exporter_infra.yearn_apy_exporter_infra_stack import \
    YearnApyExporterInfraStack


class YearnExporterInfraApp(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vpc = ec2.Vpc(
            self,
            "VPC",
            max_azs=1,
        )

        apy_log_group = logs.LogGroup(
            self,
            "ApyLogGroup",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        secrets = secretsmanager.Secret(
            self,
            "ApySecrets",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=json.dumps(
                    {
                        "MAINNET_WEB3_PROVIDER": "",
                        "MAINNET_ETHERSCAN_TOKEN": "",
                        "FANTOM_WEB3_PROVIDER": "",
                        "FTMSCAN_TOKEN": "",
                    }
                ),
                generate_string_key="_",  # Needed just to we can provision secrets manager with a template. Not used.
            ),
        )

        repository = ecr.Repository(
            self,
            "ApyExporterRepository",
            removal_policy=RemovalPolicy.DESTROY,
            lifecycle_rules=[
                ecr.LifecycleRule(
                    tag_status=ecr.TagStatus.UNTAGGED,
                    max_image_age=Duration.days(2),
                ),
                ecr.LifecycleRule(
                    max_image_count=20,
                ),
            ],
            repository_name="yearn-exporter",
        )

        bucket = s3.Bucket(
            self,
            "ApyExporterBucket",
            removal_policy=RemovalPolicy.DESTROY,
            bucket_name="api.yearn.finance",
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.GET],
                    allowed_headers=["*"],
                    allowed_origins=["*"],
                )
            ],
        )

        cloudfront.CloudFrontWebDistribution(
            self,
            "ApyExporterDistribution",
            origin_configs=[
                cloudfront.SourceConfiguration(
                    s3_origin_source=cloudfront.S3OriginConfig(s3_bucket_source=bucket),
                    behaviors=[cloudfront.Behavior(is_default_behavior=True)],
                ),
            ],
        )

        iam_user = iam.User(
            self, "ApyExporterUser", user_name="apy-exporter-service-user"
        )

        bucket.grant_read(iam_user)
        repository.grant_pull_push(iam_user)

        YearnApyExporterInfraStack(
            self,
            "YearnMainnetApyExporterInfraStack",
            vpc=vpc,
            log_group=apy_log_group,
            repository=repository,
            bucket=bucket,
            network="mainnet",
            container_secrets={
                "WEB3_PROVIDER": ecs.Secret.from_secrets_manager(
                    secrets, "MAINNET_WEB3_PROVIDER"
                ),
                "ETHERSCAN_TOKEN": ecs.Secret.from_secrets_manager(
                    secrets, "MAINNET_ETHERSCAN_TOKEN"
                ),
            },
            explorer_url="https://api.etherscan.io/api",
            schedule=app_autoscaling.Schedule.cron(
                hour="2",
            ),
            **kwargs
        )

        YearnApyExporterInfraStack(
            self,
            "YearnFantomApyExporterInfraStack",
            vpc=vpc,
            log_group=apy_log_group,
            repository=repository,
            bucket=bucket,
            network="ftm-main",
            container_secrets={
                "WEB3_PROVIDER": ecs.Secret.from_secrets_manager(
                    secrets, "FANTOM_WEB3_PROVIDER"
                ),
                "FTMSCAN_TOKEN": ecs.Secret.from_secrets_manager(
                    secrets, "FTMSCAN_TOKEN"
                ),
            },
            explorer_url="https://api.ftmscan.com/api",
            schedule=app_autoscaling.Schedule.cron(
                hour="2",
            ),
            **kwargs
        )


app = cdk.App()

YearnExporterInfraApp(
    app,
    "YearnExporterInfraApp",
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION"),
    ),
)
app.synth()
