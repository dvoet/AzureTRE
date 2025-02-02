import json
import pytest
import uuid

from azure.servicebus import ServiceBusMessage
from mock import AsyncMock, patch

from models.domain.resource import Deployment, Resource, Status, ResourceType
from service_bus.resource_request_sender import send_resource_request_message, RequestAction


pytestmark = pytest.mark.asyncio


def create_test_resource():
    return Resource(
        id=str(uuid.uuid4()),
        resourceType=ResourceType.Workspace,
        templateName="Test resource template name",
        templateVersion="2.718",
        properties={"testParameter": "testValue"},
        deployment=Deployment(
            status=Status.NotDeployed,
            message="Deployment test message"
        )
    )


@pytest.mark.parametrize('request_action', [RequestAction.Install, RequestAction.UnInstall])
@patch('service_bus.resource_request_sender.ServiceBusClient')
async def test_resource_request_message_generated_correctly(service_bus_client_mock, request_action):
    service_bus_client_mock().get_queue_sender().send_messages = AsyncMock()
    resource = create_test_resource()

    await send_resource_request_message(resource, request_action)

    args = service_bus_client_mock().get_queue_sender().send_messages.call_args.args
    assert len(args) == 1
    assert isinstance(args[0], ServiceBusMessage)

    sent_message = args[0]
    assert sent_message.correlation_id == resource.id
    sent_message_as_json = json.loads(str(sent_message))
    assert sent_message_as_json["id"] == resource.id
    assert sent_message_as_json["action"] == request_action
