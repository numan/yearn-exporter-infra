#!/usr/bin/env python3
import json
import os

import aws_cdk as cdk
from aws_cdk import Duration, RemovalPolicy, Size
from aws_cdk import aws_applicationautoscaling as app_autoscaling
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from yearn_apy_exporter_infra.yearn_apy_exporter_infra_stack import (
    YearnApyExporterInfraStack,
)


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
                        "ARBITRUM_WEB3_PROVIDER": "",
                        "ARBISCAN_TOKEN": "",
                        "SENTRY_DSN": "",
                        "GRAFANA_URL": "",
                        "GRAFANA_API_KEY": "",
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
            public_read_access=True,
        )

        cloudfront.CloudFrontWebDistribution(
            self,
            "ApyExporterDistribution",
            origin_configs=[
                cloudfront.SourceConfiguration(
                    s3_origin_source=cloudfront.S3OriginConfig(s3_bucket_source=bucket),
                    behaviors=[
                        cloudfront.Behavior(
                            is_default_behavior=True,
                            default_ttl=Duration.minutes(0),
                            max_ttl=Duration.minutes(0),
                            min_ttl=Duration.minutes(0),
                        )
                    ],
                ),
            ],
        )

        iam_user = iam.User(
            self, "ApyExporterUser", user_name="apy-exporter-service-user"
        )

        bucket.grant_read(iam_user)
        repository.grant_pull_push(iam_user)

        cluster = ecs.Cluster(self, "ApyExporterCluster", vpc=vpc)

        asg_provider = ecs.AsgCapacityProvider(
            self,
            "ApyExporterAsgCapacityProvider",
            auto_scaling_group=autoscaling.AutoScalingGroup(
                self,
                "ApyExporterAsg",
                instance_type=ec2.InstanceType("m6a.2xlarge"),
                vpc=vpc,
                machine_image=ecs.EcsOptimizedImage.amazon_linux2(),
            ),
        )

        cluster.add_asg_capacity_provider(asg_provider)

        asg_provider.auto_scaling_group.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonSSMManagedInstanceCore"
            )
        )

        YearnApyExporterInfraStack(
            self,
            "YearnMainnetApyExporterInfraStack",
            log_group=apy_log_group,
            repository=repository,
            bucket=bucket,
            network="mainnet",
            cluster=cluster,
            container_secrets={
                "WEB3_PROVIDER": ecs.Secret.from_secrets_manager(
                    secrets, "MAINNET_WEB3_PROVIDER"
                ),
                "ETHERSCAN_TOKEN": ecs.Secret.from_secrets_manager(
                    secrets, "MAINNET_ETHERSCAN_TOKEN"
                ),
                "SENTRY_DSN": ecs.Secret.from_secrets_manager(
                    secrets, "SENTRY_DSN"
                ),
                "GRAFANA_URL": ecs.Secret.from_secrets_manager(secrets, "GRAFANA_URL"),
                "GRAFANA_API_KEY": ecs.Secret.from_secrets_manager(
                    secrets, "GRAFANA_API_KEY"
                ),
            },
            explorer_url="https://api.etherscan.io/api",
            schedule=app_autoscaling.Schedule.cron(
                minute="0,20,40",
            ),
            **kwargs
        )

        YearnApyExporterInfraStack(
            self,
            "YearnFantomApyExporterInfraStack",
            log_group=apy_log_group,
            repository=repository,
            bucket=bucket,
            network="ftm-main",
            cluster=cluster,
            container_secrets={
                "WEB3_PROVIDER": ecs.Secret.from_secrets_manager(
                    secrets, "FANTOM_WEB3_PROVIDER"
                ),
                "FTMSCAN_TOKEN": ecs.Secret.from_secrets_manager(
                    secrets, "FTMSCAN_TOKEN"
                ),
                "SENTRY_DSN": ecs.Secret.from_secrets_manager(
                    secrets, "SENTRY_DSN"
                ),
                "GRAFANA_URL": ecs.Secret.from_secrets_manager(secrets, "GRAFANA_URL"),
                "GRAFANA_API_KEY": ecs.Secret.from_secrets_manager(
                    secrets, "GRAFANA_API_KEY"
                ),
            },
            explorer_url="https://api.ftmscan.com/api",
            schedule=app_autoscaling.Schedule.cron(
                minute="5,25,45",
            ),
            **kwargs
        )

        YearnApyExporterInfraStack(
            self,
            "YearnArbitrumApyExporterInfraStack",
            log_group=apy_log_group,
            repository=repository,
            bucket=bucket,
            network="arbitrum-main",
            cluster=cluster,
            container_secrets={
                "WEB3_PROVIDER": ecs.Secret.from_secrets_manager(
                    secrets, "ARBITRUM_WEB3_PROVIDER"
                ),
                "ARBISCAN_TOKEN": ecs.Secret.from_secrets_manager(
                    secrets, "ARBISCAN_TOKEN"
                ),
                "SENTRY_DSN": ecs.Secret.from_secrets_manager(
                    secrets, "SENTRY_DSN"
                ),
                "GRAFANA_URL": ecs.Secret.from_secrets_manager(secrets, "GRAFANA_URL"),
                "GRAFANA_API_KEY": ecs.Secret.from_secrets_manager(
                    secrets, "GRAFANA_API_KEY"
                ),
            },
            explorer_url="https://api.arbiscan.io/api",
            schedule=app_autoscaling.Schedule.cron(
                minute="7,27,47",
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
