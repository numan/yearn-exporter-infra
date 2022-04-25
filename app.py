#!/usr/bin/env python3
import json
import os

import aws_cdk as cdk
from aws_cdk import Duration, RemovalPolicy, Size
from aws_cdk import aws_applicationautoscaling as app_autoscaling
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
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
        domain_name = "staging.apy.exporter.yearn.finance"

        hosted_zone = route53.HostedZone.from_hosted_zone_attributes(
            self,
            "HostedZone",
            hosted_zone_id=os.getenv("HOSTED_ZONE_ID"),
            zone_name="exporter.yearn.finance",
        )

        cert = acm.DnsValidatedCertificate(
            self,
            "ApyExporter",
            hosted_zone=hosted_zone,
            domain_name=domain_name,
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

        cloudfront_distribution = cloudfront.CloudFrontWebDistribution(
            self,
            "ApyExporterDistribution",
            viewer_certificate=cloudfront.ViewerCertificate.from_acm_certificate(
                certificate=cert, aliases=[domain_name]
            ),
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

        route53.ARecord(
            self,
            "ApyExporterARecord",
            zone=hosted_zone,
            record_name=domain_name,
            target=route53.RecordTarget.from_alias(
                targets.CloudFrontTarget(cloudfront_distribution)
            ),
        )

        route53.AaaaRecord(
            self,
            "ApyExporterAliasRecord",
            zone=hosted_zone,
            record_name=domain_name,
            target=route53.RecordTarget.from_alias(
                targets.CloudFrontTarget(cloudfront_distribution)
            ),
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
                block_devices=[
                    autoscaling.BlockDevice(
                        device_name="/dev/xvda",
                        volume=autoscaling.BlockDeviceVolume.ebs(100),
                    )
                ],
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

        task_definition = ecs.Ec2TaskDefinition(
            self, "NodeExporterMetricsTaskDefinition"
        )

        task_definition.add_container(
            "NodeMetricsExporter",
            container_name="node-exporter",
            image=ecs.ContainerImage.from_asset("docker/grafana"),
            memory_reservation_mib=512,
            logging=ecs.AwsLogDriver(
                stream_prefix="node-exporter",
                log_group=apy_log_group,
                mode=ecs.AwsLogDriverMode.NON_BLOCKING,
            ),
            secrets={
                "REMOTE_WRITE": ecs.Secret.from_secrets_manager(
                    secrets, "REMOTE_WRITE"
                ),
                "REMOTE_WRITE_USERNAME": ecs.Secret.from_secrets_manager(
                    secrets, "REMOTE_WRITE_USERNAME"
                ),
                "REMOTE_WRITE_PASSWORD": ecs.Secret.from_secrets_manager(
                    secrets, "REMOTE_WRITE_PASSWORD"
                ),
            },
        )

        ecs.Ec2Service(
            self,
            "NodeExporterMetricsService",
            cluster=cluster,
            task_definition=task_definition,
            daemon=True,
        )

        YearnApyExporterInfraStack(
            self,
            "YearnMainnetEndorsedApyExporterInfraStack",
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
                "SENTRY_DSN": ecs.Secret.from_secrets_manager(secrets, "SENTRY_DSN"),
                "GRAFANA_URL": ecs.Secret.from_secrets_manager(secrets, "GRAFANA_URL"),
                "GRAFANA_API_KEY": ecs.Secret.from_secrets_manager(
                    secrets, "GRAFANA_API_KEY"
                ),
            },
            explorer_url="https://api.etherscan.io/api",
            schedule=app_autoscaling.Schedule.cron(
                minute="0,20,40",
            ),
            export_endorsed=True,
            **kwargs
        )

        YearnApyExporterInfraStack(
            self,
            "YearnMainnetExperimentalApyExporterInfraStack",
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
                "SENTRY_DSN": ecs.Secret.from_secrets_manager(secrets, "SENTRY_DSN"),
                "GRAFANA_URL": ecs.Secret.from_secrets_manager(secrets, "GRAFANA_URL"),
                "GRAFANA_API_KEY": ecs.Secret.from_secrets_manager(
                    secrets, "GRAFANA_API_KEY"
                ),
            },
            explorer_url="https://api.etherscan.io/api",
            schedule=app_autoscaling.Schedule.cron(
                minute="10,30,50",
            ),
            export_endorsed=False,
            **kwargs
        )

        YearnApyExporterInfraStack(
            self,
            "YearnFantomEndorsedApyExporterInfraStack",
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
                "SENTRY_DSN": ecs.Secret.from_secrets_manager(secrets, "SENTRY_DSN"),
                "GRAFANA_URL": ecs.Secret.from_secrets_manager(secrets, "GRAFANA_URL"),
                "GRAFANA_API_KEY": ecs.Secret.from_secrets_manager(
                    secrets, "GRAFANA_API_KEY"
                ),
            },
            explorer_url="https://api.ftmscan.com/api",
            schedule=app_autoscaling.Schedule.cron(
                minute="5,25,45",
            ),
            export_endorsed=True,
            **kwargs
        )

        YearnApyExporterInfraStack(
            self,
            "YearnFantomExperimentalApyExporterInfraStack",
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
                "SENTRY_DSN": ecs.Secret.from_secrets_manager(secrets, "SENTRY_DSN"),
                "GRAFANA_URL": ecs.Secret.from_secrets_manager(secrets, "GRAFANA_URL"),
                "GRAFANA_API_KEY": ecs.Secret.from_secrets_manager(
                    secrets, "GRAFANA_API_KEY"
                ),
            },
            explorer_url="https://api.ftmscan.com/api",
            schedule=app_autoscaling.Schedule.cron(
                minute="7,27,47",
            ),
            export_endorsed=False,
            **kwargs
        )

        YearnApyExporterInfraStack(
            self,
            "YearnArbitrumEndorsedApyExporterInfraStack",
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
                "SENTRY_DSN": ecs.Secret.from_secrets_manager(secrets, "SENTRY_DSN"),
                "GRAFANA_URL": ecs.Secret.from_secrets_manager(secrets, "GRAFANA_URL"),
                "GRAFANA_API_KEY": ecs.Secret.from_secrets_manager(
                    secrets, "GRAFANA_API_KEY"
                ),
            },
            explorer_url="https://api.arbiscan.io/api",
            schedule=app_autoscaling.Schedule.cron(
                minute="12,32,52",
            ),
            export_endorsed=True,
            **kwargs
        )

        # YearnApyExporterInfraStack(
        #     self,
        #     "YearnArbitrumExperimentalApyExporterInfraStack",
        #     log_group=apy_log_group,
        #     repository=repository,
        #     bucket=bucket,
        #     network="arbitrum-main",
        #     cluster=cluster,
        #     container_secrets={
        #         "WEB3_PROVIDER": ecs.Secret.from_secrets_manager(
        #             secrets, "ARBITRUM_WEB3_PROVIDER"
        #         ),
        #         "ARBISCAN_TOKEN": ecs.Secret.from_secrets_manager(
        #             secrets, "ARBISCAN_TOKEN"
        #         ),
        #         "SENTRY_DSN": ecs.Secret.from_secrets_manager(secrets, "SENTRY_DSN"),
        #         "GRAFANA_URL": ecs.Secret.from_secrets_manager(secrets, "GRAFANA_URL"),
        #         "GRAFANA_API_KEY": ecs.Secret.from_secrets_manager(
        #             secrets, "GRAFANA_API_KEY"
        #         ),
        #     },
        #     explorer_url="https://api.arbiscan.io/api",
        #     schedule=app_autoscaling.Schedule.cron(
        #         minute="15,35,55",
        #     ),
        #     export_endorsed=False,
        #     **kwargs
        # )


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
