import json

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_applicationautoscaling as app_autoscaling
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct


class YearnApyExporterInfraStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, vpc: ec2.IVpc, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        log_group = logs.LogGroup(
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
                    {"WEB3_PROVIDER": "", "ETHERSCAN_TOKEN": ""}
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

        cluster = ecs.Cluster(self, "ApyExporterCluster", vpc=vpc)

        asg_provider = ecs.AsgCapacityProvider(
            self,
            "ApyExporterAsgCapacityProvider",
            auto_scaling_group=autoscaling.AutoScalingGroup(
                self,
                "ApyExporterAsg",
                instance_type=ec2.InstanceType("m5a.large"),
                vpc=vpc,
                machine_image=ecs.EcsOptimizedImage.amazon_linux2(),
            ),
        )
        asg_provider.auto_scaling_group.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonSSMManagedInstanceCore"
            )
        )

        cluster.add_asg_capacity_provider(asg_provider)

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

        cloudfront_distribution = cloudfront.CloudFrontWebDistribution(
            self,
            "ApyExporterDistribution",
            origin_configs=[
                cloudfront.SourceConfiguration(
                    s3_origin_source=cloudfront.S3OriginConfig(s3_bucket_source=bucket),
                    behaviors=[cloudfront.Behavior(is_default_behavior=True)],
                ),
            ],
        )

        task_definition = ecs.Ec2TaskDefinition(
            self,
            "ApyExporterTaskDefinition",
            volumes=[
                ecs.Volume(name="brownie", host=ecs.Host(source_path="/data/brownie"))
            ],
        )

        container = task_definition.add_container(
            "s3-apy",
            image=ecs.ContainerImage.from_ecr_repository(
                repository,
                tag="apy-latest",
            ),
            command=["s3"],
            logging=ecs.AwsLogDriver(
                log_group=log_group,
                stream_prefix="apy",
                mode=ecs.AwsLogDriverMode.NON_BLOCKING,
            ),
            memory_reservation_mib=512,
            environment={
                "AWS_BUCKET": bucket.bucket_name,
            },
            secrets={
                "WEB3_PROVIDER": ecs.Secret.from_secrets_manager(
                    secrets, "WEB3_PROVIDER"
                ),
                "ETHERSCAN_TOKEN": ecs.Secret.from_secrets_manager(
                    secrets, "ETHERSCAN_TOKEN"
                ),
            },
        )

        container.add_mount_points(
            ecs.MountPoint(
                source_volume="brownie",
                container_path="/root/.brownie",
                read_only=False,
            )
        )

        scheduled_task = ecs_patterns.ScheduledEc2Task(
            self,
            "ApyExporterTask",
            cluster=cluster,
            scheduled_ec2_task_definition_options=ecs_patterns.ScheduledEc2TaskDefinitionOptions(
                task_definition=task_definition,
            ),
            schedule=app_autoscaling.Schedule.cron(
                minute="0/60",
            ),
        )

        iam_user = iam.User(
            self, "ApyExporterUser", user_name="apy-exporter-service-user"
        )

        bucket.grant_read_write(scheduled_task.task_definition.task_role)
        bucket.grant_read(iam_user)
        repository.grant_pull_push(iam_user)
