import aws_cdk as core
import aws_cdk.assertions as assertions

from yearn_apy_exporter_infra.yearn_apy_exporter_infra_stack import YearnApyExporterInfraStack

# example tests. To run these tests, uncomment this file along with the example
# resource in yearn_apy_exporter_infra/yearn_apy_exporter_infra_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = YearnApyExporterInfraStack(app, "yearn-apy-exporter-infra")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
