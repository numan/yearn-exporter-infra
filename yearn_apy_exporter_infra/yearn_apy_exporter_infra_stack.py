from typing import Mapping

from aws_cdk import Stack
from aws_cdk import aws_applicationautoscaling as app_autoscaling
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct


class YearnApyExporterInfraStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        log_group: logs.LogGroup,
        repository: ecr.IRepository,
        bucket: s3.IBucket,
        container_secrets: Mapping[str, secretsmanager.Secret],
        schedule: app_autoscaling.Schedule,
        cluster: ecs.ICluster,
        explorer_url: str,
        network: str,
        export_endorsed: bool = True,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        export_mode = None
        if export_endorsed:
            export_mode = "endorsed"
        else:
            export_mode = "experimental"


        task_definition = ecs.Ec2TaskDefinition(
            self,
            "ApyExporterTaskDefinition",
            volumes=[
                ecs.Volume(
                    name="brownie",
                    host=ecs.Host(source_path=f"/data/{network.lower()}"),
                ),
                ecs.Volume(
                    name="solc",
                    host=ecs.Host(source_path=f"/solc/{network.lower()}"),
                ),
                ecs.Volume(
                    name="vyper",
                    host=ecs.Host(source_path=f"/vyper_compilers/{network.lower()}"),
                ),
                ecs.Volume(
                    name="cache",
                    host=ecs.Host(source_path=f"/cache/{network.lower()}"),
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
                stream_prefix=f"apy/{network.lower()}/{export_mode}",
                mode=ecs.AwsLogDriverMode.NON_BLOCKING,
            ),
            memory_reservation_mib=1024,
            environment={
                "AWS_BUCKET": bucket.bucket_name,
                "EXPLORER": explorer_url,
                "NETWORK": network,
                "EXPORT_MODE": export_mode,
                "SENTRY_ENVIRONMENT": "aws-production",
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

        container.add_mount_points(
            ecs.MountPoint(
                source_volume="solc",
                container_path="/root/.solcx",
                read_only=False,
            )
        )

        container.add_mount_points(
            ecs.MountPoint(
                source_volume="vyper",
                container_path="/root/.vvm",
                read_only=False,
            )
        )

        container.add_mount_points(
            ecs.MountPoint(
                source_volume="cache",
                container_path="/app/yearn-exporter/cache",
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
            schedule=schedule,
        )

        bucket.grant_read_write(scheduled_task.task_definition.task_role)
