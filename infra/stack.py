"""AWS CDK stack: ECS Fargate + ALB (HTTP + gRPC) for BYODS webhook server."""

from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as route53_targets
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct


class ByodsWebhookStack(Stack):
    """Deploy BYODS webhook HTTP and BYOVA gRPC media behind a shared ALB."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        domain_name: str,
        hooks_hostname: str,
        media_hostname: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        hosted_zone = route53.HostedZone.from_lookup(
            self,
            "HostedZone",
            domain_name=domain_name,
        )

        certificate = acm.Certificate(
            self,
            "Certificate",
            domain_name=domain_name,
            subject_alternative_names=[f"*.{domain_name}"],
            validation=acm.CertificateValidation.from_dns(hosted_zone),
        )

        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
            ],
        )

        repository = ecr.Repository(
            self,
            "Repository",
            repository_name="byods-webhook-server",
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
            lifecycle_rules=[
                ecr.LifecycleRule(
                    description="Keep last 5 images",
                    max_image_count=5,
                ),
            ],
        )

        webex_secret = secretsmanager.Secret(
            self,
            "WebexSecret",
            secret_name="byods-webhook-server/webex",
            description="Webex Integration and Service App credentials for BYODS webhook server",
        )

        app_state_table_name = "byods-app-state"
        if self.node.try_get_context("importAppStateTable"):
            app_state_table = dynamodb.Table.from_table_name(
                self,
                "AppStateTable",
                app_state_table_name,
            )
        else:
            app_state_table = dynamodb.Table(
                self,
                "AppStateTable",
                table_name=app_state_table_name,
                partition_key=dynamodb.Attribute(
                    name="PK",
                    type=dynamodb.AttributeType.STRING,
                ),
                sort_key=dynamodb.Attribute(
                    name="SK",
                    type=dynamodb.AttributeType.STRING,
                ),
                billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
                encryption=dynamodb.TableEncryption.AWS_MANAGED,
                removal_policy=RemovalPolicy.RETAIN,
                time_to_live_attribute="expires_at",
            )

        alb_security_group = ec2.SecurityGroup(
            self,
            "AlbSecurityGroup",
            vpc=vpc,
            description="Internet-facing ALB for hooks and media hostnames",
            allow_all_outbound=True,
        )
        alb_security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(443),
            "HTTPS from internet",
        )

        service_security_group = ec2.SecurityGroup(
            self,
            "ServiceSecurityGroup",
            vpc=vpc,
            description="ECS tasks for BYODS webhook server",
            allow_all_outbound=True,
        )
        service_security_group.add_ingress_rule(
            alb_security_group,
            ec2.Port.tcp(8000),
            "HTTP from ALB",
        )
        service_security_group.add_ingress_rule(
            alb_security_group,
            ec2.Port.tcp(50051),
            "gRPC from ALB",
        )

        alb = elbv2.ApplicationLoadBalancer(
            self,
            "Alb",
            vpc=vpc,
            internet_facing=True,
            security_group=alb_security_group,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )

        http_target_group = elbv2.ApplicationTargetGroup(
            self,
            "HttpTargetGroup",
            vpc=vpc,
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            protocol_version=elbv2.ApplicationProtocolVersion.HTTP1,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                enabled=True,
                path="/health",
                protocol=elbv2.Protocol.HTTP,
                healthy_http_codes="200",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
            ),
            deregistration_delay=Duration.seconds(30),
        )

        grpc_target_group = elbv2.ApplicationTargetGroup(
            self,
            "GrpcTargetGroup",
            vpc=vpc,
            port=50051,
            protocol=elbv2.ApplicationProtocol.HTTP,
            protocol_version=elbv2.ApplicationProtocolVersion.GRPC,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                enabled=True,
                path="/com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent/ListVirtualAgents",
                protocol=elbv2.Protocol.HTTP,
                healthy_grpc_codes="0",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
            ),
            deregistration_delay=Duration.seconds(30),
        )

        https_listener = alb.add_listener(
            "HttpsListener",
            port=443,
            protocol=elbv2.ApplicationProtocol.HTTPS,
            certificates=[certificate],
            ssl_policy=elbv2.SslPolicy.RECOMMENDED_TLS,
            default_action=elbv2.ListenerAction.fixed_response(
                status_code=404,
                content_type="text/plain",
                message_body="Not found",
            ),
        )

        https_listener.add_action(
            "HooksRule",
            priority=10,
            conditions=[elbv2.ListenerCondition.host_headers([hooks_hostname])],
            action=elbv2.ListenerAction.forward([http_target_group]),
        )

        https_listener.add_action(
            "MediaRule",
            priority=20,
            conditions=[elbv2.ListenerCondition.host_headers([media_hostname])],
            action=elbv2.ListenerAction.forward([grpc_target_group]),
        )

        cluster = ecs.Cluster(
            self,
            "Cluster",
            vpc=vpc,
            container_insights=False,
        )

        log_group = logs.LogGroup(
            self,
            "LogGroup",
            log_group_name="/ecs/byods-webhook-server",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        task_execution_role = iam.Role(
            self,
            "TaskExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                ),
            ],
        )
        webex_secret.grant_read(task_execution_role)

        task_role = iam.Role(
            self,
            "TaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        app_state_table.grant_read_write_data(task_role)

        task_definition = ecs.FargateTaskDefinition(
            self,
            "TaskDefinition",
            cpu=256,
            memory_limit_mib=512,
            execution_role=task_execution_role,
            task_role=task_role,
        )

        container = task_definition.add_container(
            "App",
            image=ecs.ContainerImage.from_ecr_repository(repository, tag="latest"),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="app",
                log_group=log_group,
            ),
            environment={
                "PORT": "8000",
                "LOG_JSON": "true",
                "WEBEX_WEBHOOK_TARGET_URL": f"https://{hooks_hostname}/webhooks/webex",
                "WEBEX_DATASOURCE_PUBLIC_URL": f"https://{media_hostname}",
                "WEBEX_AUTO_REGISTER_DATASOURCE": "true",
                "WEBEX_MEDIA_ENABLED": "true",
                "WEBEX_MEDIA_HOST": "0.0.0.0",
                "WEBEX_MEDIA_PORT": "50051",
                "WEBEX_MEDIA_VERIFY_TOKENS": "true",
                "WEBEX_VIRTUAL_AGENTS_CONFIG": "config/virtual_agents.json",
                "PERSISTENCE_BACKEND": "dynamodb",
                "DYNAMODB_TABLE_NAME": app_state_table.table_name,
            },
            secrets={
                "WEBEX_INTEGRATION_CLIENT_ID": ecs.Secret.from_secrets_manager(
                    webex_secret, field="WEBEX_INTEGRATION_CLIENT_ID"
                ),
                "WEBEX_INTEGRATION_CLIENT_SECRET": ecs.Secret.from_secrets_manager(
                    webex_secret, field="WEBEX_INTEGRATION_CLIENT_SECRET"
                ),
                "WEBEX_SA_CLIENT_ID": ecs.Secret.from_secrets_manager(
                    webex_secret, field="WEBEX_SA_CLIENT_ID"
                ),
                "WEBEX_SA_CLIENT_SECRET": ecs.Secret.from_secrets_manager(
                    webex_secret, field="WEBEX_SA_CLIENT_SECRET"
                ),
                "WEBEX_INTEGRATION_REFRESH_TOKEN": ecs.Secret.from_secrets_manager(
                    webex_secret, field="WEBEX_INTEGRATION_REFRESH_TOKEN"
                ),
                "PERSISTENCE_ENCRYPTION_KEY": ecs.Secret.from_secrets_manager(
                    webex_secret, field="PERSISTENCE_ENCRYPTION_KEY"
                ),
            },
            health_check=ecs.HealthCheck(
                command=[
                    "CMD-SHELL",
                    "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\"",
                ],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(60),
            ),
        )
        container.add_port_mappings(
            ecs.PortMapping(container_port=8000, protocol=ecs.Protocol.TCP),
            ecs.PortMapping(container_port=50051, protocol=ecs.Protocol.TCP),
        )

        desired_count = int(self.node.try_get_context("desiredCount") or 1)

        service = ecs.FargateService(
            self,
            "Service",
            cluster=cluster,
            task_definition=task_definition,
            desired_count=desired_count,
            assign_public_ip=True,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_groups=[service_security_group],
            health_check_grace_period=Duration.seconds(180),
            circuit_breaker=ecs.DeploymentCircuitBreaker(enable=False),
        )

        http_target_group.add_target(
            service.load_balancer_target(container_name="App", container_port=8000)
        )
        grpc_target_group.add_target(
            service.load_balancer_target(container_name="App", container_port=50051)
        )

        hooks_record = route53.ARecord(
            self,
            "HooksRecord",
            zone=hosted_zone,
            record_name=hooks_hostname.replace(f".{domain_name}", ""),
            target=route53.RecordTarget.from_alias(
                route53_targets.LoadBalancerTarget(alb)
            ),
        )
        hooks_record.node.add_dependency(certificate)

        media_record = route53.ARecord(
            self,
            "MediaRecord",
            zone=hosted_zone,
            record_name=media_hostname.replace(f".{domain_name}", ""),
            target=route53.RecordTarget.from_alias(
                route53_targets.LoadBalancerTarget(alb)
            ),
        )
        media_record.node.add_dependency(certificate)

        CfnOutput(self, "EcrRepositoryUri", value=repository.repository_uri)
        CfnOutput(self, "AlbDnsName", value=alb.load_balancer_dns_name)
        CfnOutput(self, "HooksUrl", value=f"https://{hooks_hostname}/webhooks/webex")
        CfnOutput(self, "MediaGrpcUrl", value=f"https://{media_hostname}/grpc")
        CfnOutput(self, "HealthUrl", value=f"https://{hooks_hostname}/health")
        CfnOutput(self, "WebexSecretArn", value=webex_secret.secret_arn)
        CfnOutput(self, "EcsClusterName", value=cluster.cluster_name)
        CfnOutput(self, "EcsServiceName", value=service.service_name)
        CfnOutput(self, "AppStateTableName", value=app_state_table.table_name)
        CfnOutput(self, "AppStateTableArn", value=app_state_table.table_arn)
