"""AWS CDK stack: CodePipeline + CodeBuild CI/CD for BYODS webhook server."""

from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_codepipeline as codepipeline
from aws_cdk import aws_codepipeline_actions as cpactions
from aws_cdk import aws_codestarconnections as connections
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from constructs import Construct


class ByodsPipelineStack(Stack):
    """CodePipeline V2 release + PR validation pipelines."""

    RELEASE_PIPELINE = "byods-webhook-release"
    PR_PIPELINE = "byods-webhook-pr-validation"
    APP_STACK_NAME = "ByodsWebhookStack"
    ECR_REPO = "byods-webhook-server"

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        github_owner = self.node.try_get_context("githubOwner") or "Joezanini"
        github_repo = self.node.try_get_context("githubRepo") or "byods-webhook-server"
        github_branch = self.node.try_get_context("githubBranch") or "main"
        connection_arn = self.node.try_get_context("githubConnectionArn") or ""

        if connection_arn:
            connection_arn_value = connection_arn
        else:
            connection = connections.CfnConnection(
                self,
                "GitHubConnection",
                connection_name="byods-webhook-github",
                provider_type="GitHub",
            )
            connection_arn_value = connection.attr_connection_arn

        artifact_bucket = s3.Bucket(
            self,
            "ArtifactBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(30))],
        )

        repository_uri = (
            f"{self.account}.dkr.ecr.{self.region}.amazonaws.com/{self.ECR_REPO}"
        )
        common_env = {
            "AWS_DEFAULT_REGION": codebuild.BuildEnvironmentVariable(value=self.region),
            "AWS_ACCOUNT_ID": codebuild.BuildEnvironmentVariable(value=self.account),
            "STACK_NAME": codebuild.BuildEnvironmentVariable(value=self.APP_STACK_NAME),
            "ECR_REPO": codebuild.BuildEnvironmentVariable(value=self.ECR_REPO),
            "REPOSITORY_URI": codebuild.BuildEnvironmentVariable(value=repository_uri),
        }

        build_image = codebuild.LinuxBuildImage.AMAZON_LINUX_2_5
        build_environment = codebuild.BuildEnvironment(
            build_image=build_image,
            compute_type=codebuild.ComputeType.SMALL,
            privileged=True,
        )

        def create_log_group(name: str) -> logs.LogGroup:
            return logs.LogGroup(
                self,
                f"{name}LogGroup",
                log_group_name=f"/codebuild/{name}",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=RemovalPolicy.DESTROY,
            )

        # --- CodeBuild projects ---
        build_role = self._create_build_role(artifact_bucket)
        build_project = codebuild.PipelineProject(
            self,
            "BuildProject",
            project_name="byods-webhook-build",
            role=build_role,
            environment=build_environment,
            environment_variables={
                **common_env,
                "IMAGE_TAG": codebuild.BuildEnvironmentVariable(
                    value="#{CODEBUILD_RESOLVED_SOURCE_VERSION}"
                ),
            },
            build_spec=codebuild.BuildSpec.from_source_filename("infra/buildspec.yml"),
            logging=codebuild.LoggingOptions(
                cloud_watch=codebuild.CloudWatchLoggingOptions(
                    log_group=create_log_group("byods-webhook-build"),
                ),
            ),
        )

        deploy_role = self._create_deploy_role(artifact_bucket)
        deploy_project = codebuild.PipelineProject(
            self,
            "DeployProject",
            project_name="byods-webhook-deploy",
            role=deploy_role,
            environment=codebuild.BuildEnvironment(
                build_image=build_image,
                compute_type=codebuild.ComputeType.SMALL,
            ),
            environment_variables=common_env,
            build_spec=codebuild.BuildSpec.from_source_filename(
                "infra/buildspec-deploy.yml"
            ),
            logging=codebuild.LoggingOptions(
                cloud_watch=codebuild.CloudWatchLoggingOptions(
                    log_group=create_log_group("byods-webhook-deploy"),
                ),
            ),
        )

        verify_role = self._create_verify_role(artifact_bucket)
        verify_project = codebuild.PipelineProject(
            self,
            "VerifyProject",
            project_name="byods-webhook-verify",
            role=verify_role,
            environment=codebuild.BuildEnvironment(
                build_image=build_image,
                compute_type=codebuild.ComputeType.SMALL,
            ),
            environment_variables=common_env,
            build_spec=codebuild.BuildSpec.from_source_filename(
                "infra/buildspec-verify.yml"
            ),
            logging=codebuild.LoggingOptions(
                cloud_watch=codebuild.CloudWatchLoggingOptions(
                    log_group=create_log_group("byods-webhook-verify"),
                ),
            ),
        )

        infra_role = self._create_infra_role(artifact_bucket)
        infra_project = codebuild.PipelineProject(
            self,
            "InfraProject",
            project_name="byods-webhook-infra",
            role=infra_role,
            environment=codebuild.BuildEnvironment(
                build_image=build_image,
                compute_type=codebuild.ComputeType.SMALL,
            ),
            environment_variables={
                **common_env,
                "FORCE_INFRA": codebuild.BuildEnvironmentVariable(value="false"),
            },
            build_spec=codebuild.BuildSpec.from_source_filename(
                "infra/buildspec-infra.yml"
            ),
            logging=codebuild.LoggingOptions(
                cloud_watch=codebuild.CloudWatchLoggingOptions(
                    log_group=create_log_group("byods-webhook-infra"),
                ),
            ),
        )

        test_role = self._create_test_role(artifact_bucket)
        test_project = codebuild.PipelineProject(
            self,
            "TestProject",
            project_name="byods-webhook-test",
            role=test_role,
            environment=build_environment,
            environment_variables=common_env,
            build_spec=codebuild.BuildSpec.from_source_filename(
                "infra/buildspec-test.yml"
            ),
            logging=codebuild.LoggingOptions(
                cloud_watch=codebuild.CloudWatchLoggingOptions(
                    log_group=create_log_group("byods-webhook-test"),
                ),
            ),
        )

        pipeline_role = iam.Role(
            self,
            "PipelineRole",
            assumed_by=iam.ServicePrincipal("codepipeline.amazonaws.com"),
        )
        artifact_bucket.grant_read_write(pipeline_role)
        project_arns = [
            build_project.project_arn,
            deploy_project.project_arn,
            verify_project.project_arn,
            infra_project.project_arn,
            test_project.project_arn,
        ]
        pipeline_role.add_to_policy(
            iam.PolicyStatement(
                actions=["codebuild:BatchGetBuilds", "codebuild:StartBuild"],
                resources=project_arns,
            )
        )

        pipeline_role.add_to_policy(
            iam.PolicyStatement(
                actions=["codestar-connections:UseConnection"],
                resources=[connection_arn_value],
            )
        )

        # --- Release pipeline ---
        source_output = codepipeline.Artifact("SourceOutput")
        deploy_meta_output = codepipeline.Artifact("DeployMeta")

        source_action = cpactions.CodeStarConnectionsSourceAction(
            action_name="Source",
            owner=github_owner,
            repo=github_repo,
            branch=github_branch,
            connection_arn=connection_arn_value,
            output=source_output,
        )

        release_pipeline = codepipeline.Pipeline(
            self,
            "ReleasePipeline",
            pipeline_name=self.RELEASE_PIPELINE,
            pipeline_type=codepipeline.PipelineType.V2,
            execution_mode=codepipeline.ExecutionMode.SUPERSEDED,
            role=pipeline_role,
            artifact_bucket=artifact_bucket,
            variables=[
                codepipeline.Variable(
                    variable_name="FORCE_INFRA",
                    default_value="false",
                    description="Set to true on manual re-run to force CDK deploy without infra/** changes",
                ),
            ],
            triggers=[
                codepipeline.TriggerProps(
                    provider_type=codepipeline.ProviderType.CODE_STAR_SOURCE_CONNECTION,
                    git_configuration=codepipeline.GitConfiguration(
                        source_action=source_action,
                        push_filter=[
                            codepipeline.GitPushFilter(
                                branches_includes=[github_branch],
                            ),
                        ],
                    ),
                ),
            ],
            stages=[
                codepipeline.StageProps(stage_name="Source", actions=[source_action]),
                codepipeline.StageProps(
                    stage_name="Infra",
                    actions=[
                        cpactions.CodeBuildAction(
                            action_name="InfraDeploy",
                            project=infra_project,
                            input=source_output,
                            environment_variables={
                                "FORCE_INFRA": codebuild.BuildEnvironmentVariable(
                                    value="#{variables.FORCE_INFRA}",
                                    type=codebuild.BuildEnvironmentVariableType
                                    .PLAINTEXT,
                                ),
                            },
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="Build",
                    actions=[
                        cpactions.CodeBuildAction(
                            action_name="BuildAndPush",
                            project=build_project,
                            input=source_output,
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="Deploy",
                    actions=[
                        cpactions.CodeBuildAction(
                            action_name="EcsDeploy",
                            project=deploy_project,
                            input=source_output,
                            outputs=[deploy_meta_output],
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="Verify",
                    actions=[
                        cpactions.CodeBuildAction(
                            action_name="SmokeTest",
                            project=verify_project,
                            input=source_output,
                            extra_inputs=[deploy_meta_output],
                        ),
                    ],
                ),
            ],
        )

        # --- PR validation pipeline ---
        pr_source_output = codepipeline.Artifact("PrSourceOutput")
        pr_source_action = cpactions.CodeStarConnectionsSourceAction(
            action_name="Source",
            owner=github_owner,
            repo=github_repo,
            branch=github_branch,
            connection_arn=connection_arn_value,
            output=pr_source_output,
            trigger_on_push=False,
        )

        pr_pipeline = codepipeline.Pipeline(
            self,
            "PrPipeline",
            pipeline_name=self.PR_PIPELINE,
            pipeline_type=codepipeline.PipelineType.V2,
            role=pipeline_role,
            artifact_bucket=artifact_bucket,
            triggers=[
                codepipeline.TriggerProps(
                    provider_type=codepipeline.ProviderType.CODE_STAR_SOURCE_CONNECTION,
                    git_configuration=codepipeline.GitConfiguration(
                        source_action=pr_source_action,
                        pull_request_filter=[
                            codepipeline.GitPullRequestFilter(
                                branches_includes=["*"],
                                events=[
                                    codepipeline.GitPullRequestEvent.OPEN,
                                    codepipeline.GitPullRequestEvent.UPDATED,
                                ],
                            ),
                        ],
                    ),
                ),
            ],
            stages=[
                codepipeline.StageProps(
                    stage_name="Source",
                    actions=[pr_source_action],
                ),
                codepipeline.StageProps(
                    stage_name="Test",
                    actions=[
                        cpactions.CodeBuildAction(
                            action_name="TestAndBuild",
                            project=test_project,
                            input=pr_source_output,
                        ),
                    ],
                ),
            ],
        )

        CfnOutput(self, "ReleasePipelineName", value=self.RELEASE_PIPELINE)
        CfnOutput(self, "PrPipelineName", value=self.PR_PIPELINE)
        CfnOutput(self, "ArtifactBucketName", value=artifact_bucket.bucket_name)
        CfnOutput(self, "EcrBuildProjectName", value=build_project.project_name)
        CfnOutput(self, "GitHubConnectionArn", value=connection_arn_value)

    def _deny_webex_secrets(self, role: iam.Role) -> None:
        role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.DENY,
                actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:byods-webhook-server/webex*",
                ],
            )
        )

    def _create_build_role(self, bucket: s3.Bucket) -> iam.Role:
        role = iam.Role(
            self,
            "BuildRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
        )
        role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonEC2ContainerRegistryPowerUser"
            )
        )
        bucket.grant_read(role)
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                resources=["*"],
            )
        )
        self._deny_webex_secrets(role)
        return role

    def _create_deploy_role(self, bucket: s3.IBucket) -> iam.Role:
        role = iam.Role(
            self,
            "DeployRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
        )
        bucket.grant_read_write(role)
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecs:UpdateService",
                    "ecs:DescribeServices",
                    "ecs:DescribeTasks",
                    "ecs:ListTasks",
                ],
                resources=["*"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudformation:DescribeStacks"],
                resources=[
                    f"arn:aws:cloudformation:{self.region}:{self.account}:stack/{self.APP_STACK_NAME}/*",
                ],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                resources=["*"],
            )
        )
        self._deny_webex_secrets(role)
        return role

    def _create_verify_role(self, bucket: s3.IBucket) -> iam.Role:
        role = iam.Role(
            self,
            "VerifyRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
        )
        bucket.grant_read(role)
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecs:UpdateService",
                    "ecs:DescribeServices",
                    "ecs:DescribeTasks",
                ],
                resources=["*"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudformation:DescribeStacks"],
                resources=[
                    f"arn:aws:cloudformation:{self.region}:{self.account}:stack/{self.APP_STACK_NAME}/*",
                ],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                resources=["*"],
            )
        )
        self._deny_webex_secrets(role)
        return role

    def _create_infra_role(self, bucket: s3.IBucket) -> iam.Role:
        role = iam.Role(
            self,
            "InfraRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
        )
        bucket.grant_read(role)
        role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("PowerUserAccess")
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole", "sts:AssumeRole"],
                resources=["*"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                resources=["*"],
            )
        )
        self._deny_webex_secrets(role)
        return role

    def _create_test_role(self, bucket: s3.IBucket) -> iam.Role:
        role = iam.Role(
            self,
            "TestRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
        )
        bucket.grant_read(role)
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                resources=["*"],
            )
        )
        self._deny_webex_secrets(role)
        return role
