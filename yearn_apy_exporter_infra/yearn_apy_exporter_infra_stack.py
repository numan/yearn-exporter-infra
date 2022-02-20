from tokenize import Number
from typing import Mapping
from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_applicationautoscaling as app_autoscaling
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_efs as efs
from constructs import Construct

class YearnApyExporterInfraStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: ec2.IVpc,
        log_group: logs.LogGroup,
        repository: ecr.IRepository,
        bucket: s3.IBucket,
        container_secrets: Mapping[str, secretsmanager.Secret],
        schedule: app_autoscaling.Schedule,
        explorer_url:str,
        network: str,
        cpu: Number = 4096,
        memory: Number = 10240,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        cluster = ecs.Cluster(self, "ApyExporterCluster", vpc=vpc)


        sg = ec2.SecurityGroup(
            self, "EFSSecurityGroup", vpc=vpc, allow_all_outbound=True
        )
        sg.connections.allow_from(sg, ec2.Port.all_traffic())

        apy_cache_fs = efs.FileSystem(
            self,
            "ApyExporterCacheFileSystem",
            vpc=vpc,
            lifecycle_policy=efs.LifecyclePolicy.AFTER_14_DAYS,
            performance_mode=efs.PerformanceMode.GENERAL_PURPOSE,
            security_group=sg,
            removal_policy=RemovalPolicy.DESTROY,
        )

        task_definition = ecs.FargateTaskDefinition(
            self,
            "ApyExporterTaskDefinition",
            cpu=cpu,
            memory_limit_mib=memory,
            volumes=[
                ecs.Volume(
                    name="brownie",
                    efs_volume_configuration=ecs.EfsVolumeConfiguration(
                        file_system_id=apy_cache_fs.file_system_id,
                    ),
                )
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
            cpu=cpu,
            memory_reservation_mib=memory,
            environment={
                "AWS_BUCKET": bucket.bucket_name,
                "EXPLORER": explorer_url,
                "NETWORK": network,
            },
            secrets=container_secrets,
        )

        container.add_mount_points(
            ecs.MountPoint(
                source_volume="brownie",
                container_path="/root/.brownie",
                read_only=False,
            )
        )

        scheduled_task = ecs_patterns.ScheduledFargateTask(
            self,
            "ApyExporterTask",
            cluster=cluster,
            scheduled_fargate_task_definition_options=ecs_patterns.ScheduledFargateTaskDefinitionOptions(
                task_definition=task_definition,
            ),
            schedule=schedule,

        )



        for task_sg in scheduled_task.task.security_groups:
            task_sg.connections.allow_to(apy_cache_fs.connections, ec2.Port.all_traffic())

        bucket.grant_read_write(scheduled_task.task_definition.task_role)

