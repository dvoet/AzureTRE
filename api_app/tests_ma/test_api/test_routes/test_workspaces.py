import pytest
from mock import patch, MagicMock

from fastapi import HTTPException, status

from api.routes.workspaces import save_and_deploy_resource, \
    mark_resource_as_deleting, send_uninstall_message
from db.errors import EntityDoesNotExist
from db.repositories.resources import ResourceRepository
from db.repositories.workspaces import WorkspaceRepository
from db.repositories.workspace_services import WorkspaceServiceRepository
from models.domain.authentication import RoleAssignment
from models.domain.resource import Status, Deployment, RequestAction, ResourceType
from models.domain.user_resource import UserResource
from models.domain.workspace import Workspace, WorkspaceRole
from models.domain.workspace_service import WorkspaceService
from resources import strings
from services.authentication import get_current_admin_user, get_current_tre_user_or_tre_admin, get_current_workspace_owner_user, get_current_workspace_owner_or_researcher_user, get_current_workspace_owner_or_researcher_user_or_tre_admin

pytestmark = pytest.mark.asyncio


WORKSPACE_ID = '933ad738-7265-4b5f-9eae-a1a62928772e'
SERVICE_ID = 'abcad738-7265-4b5f-9eae-a1a62928772e'
USER_RESOURCE_ID = 'a33ad738-7265-4b5f-9eae-a1a62928772a'
APP_ID = 'f0acf127-a672-a672-a672-a15e5bf9f127'


@pytest.fixture
def resource_repo() -> ResourceRepository:
    with patch("azure.cosmos.CosmosClient") as cosmos_client_mock:
        return ResourceRepository(cosmos_client_mock)


@pytest.fixture
def workspace_input():
    return {
        "templateName": "test-workspace",
        "properties": {
            "display_name": "display",
            "app_id": APP_ID
        }
    }


@pytest.fixture
def workspace_service_input():
    return {
        "templateName": "test-workspace-service",
        "properties": {
            "display_name": "display"
        }
    }


@pytest.fixture
def sample_user_resource_input_data():
    return {
        "templateName": "test-user-resource",
        "properties": {
            "display_name": "display",
        }
    }


@pytest.fixture
def disabled_workspace() -> Workspace:
    workspace = sample_workspace(WORKSPACE_ID)
    workspace.properties["enabled"] = False
    return workspace


def sample_workspace(workspace_id=WORKSPACE_ID, auth_info: dict = {}):
    workspace = Workspace(
        id=workspace_id,
        templateName="tre-workspace-base",
        templateVersion="0.1.0",
        properties={
            "app_id": "12345"
        },
        deployment=Deployment(status=Status.NotDeployed, message=""),
    )
    if auth_info:
        workspace.authInformation = auth_info
    return workspace


def sample_deployed_workspace(workspace_id=WORKSPACE_ID, auth_info: dict = {}):
    workspace = Workspace(
        id=workspace_id,
        templateName="tre-workspace-base",
        templateVersion="0.1.0",
        properties={},
        deployment=Deployment(status=Status.Deployed, message=""),
    )
    if auth_info:
        workspace.authInformation = auth_info
    return workspace


def sample_workspace_service(workspace_service_id=SERVICE_ID, workspace_id=WORKSPACE_ID):
    return WorkspaceService(
        id=workspace_service_id,
        workspaceId=workspace_id,
        templateName="tre-workspace-base",
        templateVersion="0.1.0",
        properties={},
        deployment=Deployment(status=Status.NotDeployed, message=""),
    )


def sample_user_resource_object(user_resource_id=USER_RESOURCE_ID, workspace_id=WORKSPACE_ID, parent_workspace_service_id=SERVICE_ID):
    user_resource = UserResource(
        id=user_resource_id,
        workspaceId=workspace_id,
        parentWorkspaceServiceId=parent_workspace_service_id,
        templateName="tre-user-resource",
        templateVersion="0.1.0",
        properties={},
        deployment=Deployment(status=Status.NotDeployed, message=""),
    )

    return user_resource


def disabled_workspace_service():
    return WorkspaceService(id=SERVICE_ID, templateName='template name', templateVersion='1.0', properties={"enabled": False})


def disabled_user_resource():
    return UserResource(id=USER_RESOURCE_ID, templateName='template name', templateVersion='1.0', properties={"enabled": False})


class TestWorkspaceHelpers:
    @patch("api.routes.workspaces.send_resource_request_message")
    async def test_save_and_deploy_resource_saves_item(self, _, resource_repo):
        resource = sample_workspace()
        resource_repo.save_item = MagicMock(return_value=None)

        await save_and_deploy_resource(resource, resource_repo)

        resource_repo.save_item.assert_called_once_with(resource)

    async def test_save_and_deploy_resource_raises_503_if_save_to_db_fails(self, resource_repo):
        resource = sample_workspace()
        resource_repo.save_item = MagicMock(side_effect=Exception)

        with pytest.raises(HTTPException) as ex:
            await save_and_deploy_resource(resource, resource_repo)
        assert ex.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    @patch("api.routes.workspaces.send_resource_request_message", return_value=None)
    async def test_save_and_deploy_resource_sends_resource_request_message(self, send_resource_request_mock, resource_repo):
        resource = sample_workspace()
        resource_repo.save_item = MagicMock(return_value=None)

        await save_and_deploy_resource(resource, resource_repo)

        send_resource_request_mock.assert_called_once_with(resource, RequestAction.Install)

    @patch("api.routes.workspaces.send_resource_request_message", side_effect=Exception)
    async def test_save_and_deploy_resource_raises_503_if_send_request_fails(self, _, resource_repo):
        resource = sample_workspace()
        resource_repo.save_item = MagicMock(return_value=None)
        resource_repo.delete_item = MagicMock(return_value=None)

        with pytest.raises(HTTPException) as ex:
            await save_and_deploy_resource(resource, resource_repo)
        assert ex.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    @patch("api.routes.workspaces.send_resource_request_message", side_effect=Exception)
    async def test_save_and_deploy_resource_deletes_item_from_db_if_send_request_fails(self, _, resource_repo):
        resource = sample_workspace()
        resource_repo.save_item = MagicMock(return_value=None)
        resource_repo.delete_item = MagicMock(return_value=None)

        with pytest.raises(HTTPException):
            await save_and_deploy_resource(resource, resource_repo)

        resource_repo.delete_item.assert_called_once_with(resource.id)

    @patch("api.routes.workspaces.ResourceRepository.mark_resource_as_deleting", return_value=None)
    async def test_mark_resource_as_deleting_marks_resource_as_deleting(self, mark_as_deleting_mock, resource_repo):
        workspace = sample_workspace()

        mark_resource_as_deleting(workspace, resource_repo, ResourceType.Workspace)

        mark_as_deleting_mock.assert_called_once_with(workspace)

    @patch("api.routes.workspaces.ResourceRepository.mark_resource_as_deleting", side_effect=Exception)
    async def test_mark_resource_as_deleting_raises_503_if_db_exception(self, _, resource_repo):
        with pytest.raises(HTTPException) as ex:
            mark_resource_as_deleting(sample_workspace(), resource_repo, ResourceType.Workspace)
        assert ex.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    @patch("api.routes.workspaces.send_resource_request_message", return_value=None)
    async def test_send_uninstall_message_sends_uninstall_message(self, send_request_mock, resource_repo):
        workspace = sample_workspace()
        await send_uninstall_message(workspace, resource_repo, Status.Deployed, ResourceType.Workspace)

        send_request_mock.assert_called_once_with(workspace, RequestAction.UnInstall)

    @patch("api.routes.workspaces.send_resource_request_message", side_effect=Exception)
    async def test_send_uninstall_message_restores_status_on_service_bus_exception(self, _, resource_repo):
        resource_repo.restore_previous_deletion_state = MagicMock(return_value=None)
        workspace = sample_workspace()
        prev_status = Status.Deployed

        with pytest.raises(HTTPException):
            await send_uninstall_message(workspace, resource_repo, prev_status, ResourceType.Workspace)

        resource_repo.restore_previous_deletion_state.assert_called_once_with(workspace, prev_status)

    @patch("api.routes.workspaces.send_resource_request_message", side_effect=Exception)
    async def test_send_uninstall_message_raises_503_on_service_bus_exception(self, _, resource_repo):
        resource_repo.restore_previous_deletion_state = MagicMock(return_value=None)

        with pytest.raises(HTTPException) as ex:
            await send_uninstall_message(sample_workspace(), resource_repo, Status.Deployed, ResourceType.Workspace)
        assert ex.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


class TestWorkspaceRoutesThatDontRequireAdminRights:
    @pytest.fixture(autouse=True, scope='class')
    def log_in_with_non_admin_user(self, app, non_admin_user):
        with patch('services.aad_authentication.AzureADAuthorization._get_user_from_token', return_value=non_admin_user()):
            app.dependency_overrides[get_current_tre_user_or_tre_admin] = non_admin_user
            yield
            app.dependency_overrides = {}

    # [GET] /workspaces
    @patch("api.routes.workspaces.WorkspaceRepository.get_active_workspaces")
    @patch("api.routes.workspaces.get_user_role_assignments", return_value=[])
    async def test_get_workspaces_returns_empty_list_when_no_resources_exist(self, access_service_mock, get_workspaces_mock, app, client) -> None:
        get_workspaces_mock.return_value = []
        access_service_mock.get_workspace_role.return_value = [WorkspaceRole.Owner]

        response = await client.get(app.url_path_for(strings.API_GET_ALL_WORKSPACES))
        assert response.json() == {"workspaces": []}

    # [GET] /workspaces
    @patch("api.routes.workspaces.WorkspaceRepository.get_active_workspaces")
    @patch("api.routes.workspaces.get_user_role_assignments")
    async def test_get_workspaces_returns_correct_data_when_resources_exist(self, access_service_mock, get_workspaces_mock, app, client) -> None:
        auth_info_user_in_workspace_owner_role = {'sp_id': 'ab123', 'roles': {'WorkspaceOwner': 'ab124', 'WorkspaceResearcher': 'ab125'}}
        auth_info_user_in_workspace_researcher_role = {'sp_id': 'ab123', 'roles': {'WorkspaceOwner': 'ab127', 'WorkspaceResearcher': 'ab126'}}
        auth_info_user_not_in_workspace_role = {'sp_id': 'ab127', 'roles': {'WorkspaceOwner': 'ab128', 'WorkspaceResearcher': 'ab129'}}

        valid_ws_1 = sample_workspace(auth_info=auth_info_user_in_workspace_owner_role)
        valid_ws_2 = sample_workspace(auth_info=auth_info_user_in_workspace_researcher_role)
        invalid_ws = sample_workspace(auth_info=auth_info_user_not_in_workspace_role)

        get_workspaces_mock.return_value = [valid_ws_1, valid_ws_2, invalid_ws]
        access_service_mock.return_value = [RoleAssignment('ab123', 'ab124'), RoleAssignment('ab123', 'ab126')]

        response = await client.get(app.url_path_for(strings.API_GET_ALL_WORKSPACES))
        workspaces_from_response = response.json()["workspaces"]

        assert len(workspaces_from_response) == 2
        assert valid_ws_1 in workspaces_from_response
        assert valid_ws_2 in workspaces_from_response


class TestWorkspaceRoutesThatRequireAdminRights:
    @pytest.fixture(autouse=True, scope='class')
    def _prepare(self, app, admin_user):
        with patch('services.aad_authentication.AzureADAuthorization._get_user_from_token', return_value=admin_user()):
            app.dependency_overrides[get_current_tre_user_or_tre_admin] = admin_user
            app.dependency_overrides[get_current_admin_user] = admin_user
            yield
            app.dependency_overrides = {}

    # [GET] /workspaces
    @ patch("api.routes.workspaces.WorkspaceRepository.get_active_workspaces")
    async def test_get_workspaces_returns_correct_data_when_resources_exist(self, get_workspaces_mock, app, client) -> None:
        auth_info_user_in_workspace_owner_role = {'sp_id': 'ab123', 'roles': {'WorkspaceOwner': 'ab124', 'WorkspaceResearcher': 'ab125'}}
        auth_info_user_in_workspace_researcher_role = {'sp_id': 'ab123', 'roles': {'WorkspaceOwner': 'ab127', 'WorkspaceResearcher': 'ab126'}}
        auth_info_user_not_in_workspace_role = {'sp_id': 'ab127', 'roles': {'WorkspaceOwner': 'ab128', 'WorkspaceResearcher': 'ab129'}}

        valid_ws_1 = sample_workspace(auth_info=auth_info_user_in_workspace_owner_role)
        valid_ws_2 = sample_workspace(auth_info=auth_info_user_in_workspace_researcher_role)
        valid_ws_3 = sample_workspace(auth_info=auth_info_user_not_in_workspace_role)

        get_workspaces_mock.return_value = [valid_ws_1, valid_ws_2, valid_ws_3]

        response = await client.get(app.url_path_for(strings.API_GET_ALL_WORKSPACES))
        workspaces_from_response = response.json()["workspaces"]

        assert len(workspaces_from_response) == 3
        assert valid_ws_1 in workspaces_from_response
        assert valid_ws_2 in workspaces_from_response
        assert valid_ws_3 in workspaces_from_response

    # [GET] /workspaces/{workspace_id}
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    async def test_get_workspace_by_id_get_returns_workspace_if_found(self, get_workspace_mock, app, client):
        workspace = sample_workspace()
        get_workspace_mock.return_value = sample_workspace()

        response = await client.get(app.url_path_for(strings.API_GET_WORKSPACE_BY_ID, workspace_id=WORKSPACE_ID))
        actual_resource = response.json()["workspace"]
        assert actual_resource["id"] == workspace.id

    # [POST] /workspaces/
    @ patch("api.routes.workspaces.send_resource_request_message")
    @ patch("api.routes.workspaces.WorkspaceRepository.save_item")
    @ patch("api.routes.workspaces.WorkspaceRepository.create_workspace_item", return_value=sample_workspace())
    @ patch("api.routes.workspaces.extract_auth_information")
    async def test_post_workspaces_creates_workspace(self, _, __, ___, ____, app, client, workspace_input):
        response = await client.post(app.url_path_for(strings.API_CREATE_WORKSPACE), json=workspace_input)

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json()["workspaceId"] == WORKSPACE_ID

    # [POST] /workspaces/
    @ patch("api.routes.workspaces.send_resource_request_message")
    @ patch("api.routes.workspaces.WorkspaceRepository.save_item")
    @ patch("api.routes.workspaces.WorkspaceRepository.create_workspace_item", return_value=sample_workspace())
    @ patch("api.routes.workspaces.WorkspaceRepository._validate_resource_parameters")
    @ patch("api.routes.workspaces.extract_auth_information")
    async def test_post_workspaces_calls_db_and_service_bus(self, _, __, ___, save_item_mock, send_resource_request_message_mock, app, client, workspace_input):
        await client.post(app.url_path_for(strings.API_CREATE_WORKSPACE), json=workspace_input)

        save_item_mock.assert_called_once()
        send_resource_request_message_mock.assert_called_once()

    # [POST] /workspaces/
    @ patch("api.routes.workspaces.send_resource_request_message")
    @ patch("api.routes.workspaces.WorkspaceRepository.save_item")
    @ patch("api.routes.workspaces.WorkspaceRepository.create_workspace_item", return_value=sample_workspace())
    @ patch("api.routes.workspaces.WorkspaceRepository._validate_resource_parameters")
    @ patch("api.routes.workspaces.extract_auth_information")
    async def test_post_workspaces_returns_202_on_successful_create(self, _, __, ___, ____, _____, app, client, workspace_input):
        response = await client.post(app.url_path_for(strings.API_CREATE_WORKSPACE), json=workspace_input)

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json()["workspaceId"] == WORKSPACE_ID

    # [POST] /workspaces/
    @ patch("api.routes.workspaces.WorkspaceRepository.delete_item")
    @ patch("api.routes.workspaces.send_resource_request_message", side_effect=Exception)
    @ patch("api.routes.workspaces.WorkspaceRepository.save_item")
    @ patch("api.routes.workspaces.WorkspaceRepository.create_workspace_item", return_value=sample_workspace())
    @ patch("api.routes.workspaces.WorkspaceRepository._validate_resource_parameters")
    @ patch("api.routes.workspaces.extract_auth_information")
    async def test_post_workspaces_returns_503_if_service_bus_call_fails(self, _, __, ___, ____, _____, delete_item_mock, app, client, workspace_input):
        response = await client.post(app.url_path_for(strings.API_CREATE_WORKSPACE), json=workspace_input)

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        delete_item_mock.assert_called_once_with(WORKSPACE_ID)

    # [POST] /workspaces/
    @ patch("api.routes.workspaces.WorkspaceRepository.validate_input_against_template", side_effect=ValueError)
    async def test_post_workspaces_returns_400_if_template_does_not_exist(self, _, app, client, workspace_input):
        response = await client.post(app.url_path_for(strings.API_CREATE_WORKSPACE), json=workspace_input)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # [PATCH] /workspaces/{workspace_id}
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id", side_effect=EntityDoesNotExist)
    async def test_patch_workspaces_returns_404_if_workspace_does_not_exist(self, _, app, client):
        response = await client.patch(app.url_path_for(strings.API_UPDATE_WORKSPACE, workspace_id=WORKSPACE_ID), json='{"enabled": true}')
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # [PATCH] /workspaces/{workspace_id}
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @ patch("api.routes.workspaces.WorkspaceRepository.patch_workspace", return_value=None)
    async def test_patch_workspaces_patches_workspace(self, patch_workspace_mock, get_workspace_mock, app, client):
        workspace_to_patch = sample_workspace()
        get_workspace_mock.return_value = workspace_to_patch
        workspace_patch = {"enabled": True}

        response = await client.patch(app.url_path_for(strings.API_UPDATE_WORKSPACE, workspace_id=workspace_to_patch.id), json=workspace_patch)

        patch_workspace_mock.assert_called_once_with(workspace_to_patch, workspace_patch)
        assert response.status_code == status.HTTP_200_OK

    # [DELETE] /workspaces/{workspace_id}
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    async def test_delete_workspace_returns_400_if_workspace_is_enabled(self, get_workspace_mock, app, client):
        workspace = sample_workspace()
        workspace.properties["enabled"] = True
        get_workspace_mock.return_value = workspace

        response = await client.delete(app.url_path_for(strings.API_DELETE_WORKSPACE, workspace_id=WORKSPACE_ID))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # [DELETE] /workspaces/{workspace_id}
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @ patch("api.routes.workspaces.WorkspaceServiceRepository.get_active_workspace_services_for_workspace")
    async def test_delete_workspace_returns_400_if_associated_workspace_services_are_not_deleted(self, get_active_workspace_services_for_workspace_mock, get_workspace_mock, disabled_workspace, app, client):
        get_workspace_mock.return_value = disabled_workspace
        get_active_workspace_services_for_workspace_mock.return_value = ["some workspace service that is not deleted"]

        response = await client.delete(app.url_path_for(strings.API_DELETE_WORKSPACE, workspace_id=WORKSPACE_ID))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # [DELETE] /workspaces/{workspace_id}
    @ patch("api.dependencies.workspaces.get_repository")
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @ patch("api.routes.workspaces.WorkspaceServiceRepository.get_active_workspace_services_for_workspace", return_value=[])
    @ patch('azure.cosmos.CosmosClient')
    @ patch('api.routes.workspaces.WorkspaceRepository.mark_resource_as_deleting')
    @ patch('api.routes.workspaces.send_resource_request_message')
    async def test_delete_workspace_deletes_workspace(self, _, delete_workspace_mock, cosmos_client_mock, __, get_workspace_mock, get_repository_mock, disabled_workspace, app, client):
        get_workspace_mock.return_value = disabled_workspace
        get_repository_mock.side_effects = [WorkspaceRepository(cosmos_client_mock), WorkspaceServiceRepository(cosmos_client_mock)]

        await client.delete(app.url_path_for(strings.API_DELETE_WORKSPACE, workspace_id=WORKSPACE_ID))

        delete_workspace_mock.assert_called_once()

    # [DELETE] /workspaces/{workspace_id}
    @ patch("api.dependencies.workspaces.get_repository")
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @ patch("api.routes.workspaces.WorkspaceServiceRepository.get_active_workspace_services_for_workspace", return_value=[])
    @ patch('azure.cosmos.CosmosClient')
    @ patch('api.routes.workspaces.WorkspaceRepository.mark_resource_as_deleting')
    @ patch('api.routes.workspaces.send_resource_request_message')
    async def test_delete_workspace_sends_a_request_message_to_uninstall_the_workspace(self, send_request_message_mock, _, cosmos_client_mock, __, get_workspace_mock, get_repository_mock, disabled_workspace, app, client):
        get_workspace_mock.return_value = disabled_workspace
        get_repository_mock.side_effects = [WorkspaceRepository(cosmos_client_mock), WorkspaceServiceRepository(cosmos_client_mock)]

        await client.delete(app.url_path_for(strings.API_DELETE_WORKSPACE, workspace_id=WORKSPACE_ID))

        send_request_message_mock.assert_called_once()

    # [DELETE] /workspaces/{workspace_id}
    @ patch("api.dependencies.workspaces.get_repository")
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @ patch("api.routes.workspaces.WorkspaceServiceRepository.get_active_workspace_services_for_workspace", return_value=[])
    @ patch('azure.cosmos.CosmosClient')
    @ patch('api.routes.workspaces.WorkspaceRepository.mark_resource_as_deleting')
    @ patch('api.routes.workspaces.send_resource_request_message', side_effect=Exception)
    @ patch('api.routes.workspaces.WorkspaceRepository.restore_previous_deletion_state')
    async def test_delete_workspace_reverts_the_workspace_if_service_bus_call_fails(self, restore_previous_deletion_state_mock, _, __, cosmos_client_mock, ___, get_workspace_mock, get_repository_mock, disabled_workspace, app, client):
        get_workspace_mock.return_value = disabled_workspace
        get_repository_mock.side_effects = [WorkspaceRepository(cosmos_client_mock), WorkspaceServiceRepository(cosmos_client_mock)]

        await client.delete(app.url_path_for(strings.API_DELETE_WORKSPACE, workspace_id=WORKSPACE_ID))

        # assert we revert the workspace
        restore_previous_deletion_state_mock.assert_called_once()

    # [DELETE] /workspaces/{workspace_id}
    @ patch("api.dependencies.workspaces.get_repository")
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @ patch("api.routes.workspaces.WorkspaceServiceRepository.get_active_workspace_services_for_workspace")
    @ patch('azure.cosmos.CosmosClient')
    @ patch('api.routes.workspaces.WorkspaceRepository.mark_resource_as_deleting', side_effect=Exception)
    async def test_delete_workspace_raises_503_if_marking_the_resource_as_deleted_in_the_db_fails(self, _, __, ___, get_workspace_mock, _____, client, app, disabled_workspace):
        get_workspace_mock.return_value = disabled_workspace

        response = await client.delete(app.url_path_for(strings.API_DELETE_WORKSPACE, workspace_id=WORKSPACE_ID))

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


class TestWorkspaceServiceRoutesThatRequireOwnerRights:
    @pytest.fixture(autouse=True, scope='class')
    def log_in_with_owner_user(self, app, owner_user):
        # The following ws services requires the WS app registration
        app.dependency_overrides[get_current_workspace_owner_user] = owner_user
        app.dependency_overrides[get_current_workspace_owner_or_researcher_user] = owner_user
        yield
        app.dependency_overrides = {}

    # [POST] /workspaces/{workspace_id}/workspace-services
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @ patch("api.routes.workspaces.send_resource_request_message")
    @ patch("api.routes.workspaces.WorkspaceServiceRepository.save_item")
    @ patch("api.routes.workspaces.WorkspaceServiceRepository.create_workspace_service_item", return_value=sample_workspace_service())
    async def test_post_workspace_services_creates_workspace_service(self, _, __, ___, get_workspace_mock, app, client, workspace_service_input):
        auth_info_user_in_workspace_owner_role = {'sp_id': 'ab123', 'roles': {'WorkspaceOwner': 'ab124', 'WorkspaceResearcher': 'ab125'}}
        workspace = sample_workspace(auth_info=auth_info_user_in_workspace_owner_role)
        workspace.deployment.status = Status.Deployed
        get_workspace_mock.return_value = workspace

        response = await client.post(app.url_path_for(strings.API_CREATE_WORKSPACE_SERVICE, workspace_id=WORKSPACE_ID), json=workspace_service_input)

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json()["workspaceServiceId"] == SERVICE_ID

    # [POST] /workspaces/{workspace_id}/workspace-services
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @ patch("api.routes.workspaces.WorkspaceServiceRepository.create_workspace_service_item", side_effect=ValueError)
    async def test_post_workspace_services_raises_400_bad_request_if_input_is_bad(self, _, get_workspace_mock, app, client, workspace_service_input):
        auth_info_user_in_workspace_owner_role = {'sp_id': 'ab123', 'roles': {'WorkspaceOwner': 'ab124', 'WorkspaceResearcher': 'ab125'}}
        workspace = sample_workspace(auth_info=auth_info_user_in_workspace_owner_role)
        workspace.deployment.status = Status.Deployed
        get_workspace_mock.return_value = workspace

        response = await client.post(app.url_path_for(strings.API_CREATE_WORKSPACE_SERVICE, workspace_id=WORKSPACE_ID), json=workspace_service_input)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # [DELETE] /workspaces/{workspace_id}/services/{service_id}
    @patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id")
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    async def test_delete_workspace_service_raises_400_if_workspace_service_is_enabled(self, _,
                                                                                       get_workspace_service_mock,
                                                                                       app, client):
        workspace_service = sample_workspace_service()
        workspace_service.properties["enabled"] = True
        get_workspace_service_mock.return_value = workspace_service

        response = await client.delete(
            app.url_path_for(strings.API_DELETE_WORKSPACE_SERVICE, workspace_id=WORKSPACE_ID,
                             service_id=SERVICE_ID))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # [DELETE] /workspaces/{workspace_id}/services/{service_id}
    @patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id",
           return_value=disabled_workspace_service())
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @patch("api.routes.workspaces.UserResourceRepository.get_user_resources_for_workspace_service")
    async def test_delete_workspace_service_raises_404_if_workspace_service_has_active_resources(self,
                                                                                                 get_user_resources_mock,
                                                                                                 __, ___, app,
                                                                                                 client):
        get_user_resources_mock.return_value = [sample_user_resource_object()]

        response = await client.delete(
            app.url_path_for(strings.API_DELETE_WORKSPACE_SERVICE, workspace_id=WORKSPACE_ID,
                             service_id=SERVICE_ID))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # [DELETE] /workspaces/{workspace_id}/services/{service_id}
    @patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id",
           return_value=disabled_workspace_service())
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @patch("api.routes.workspaces.UserResourceRepository.get_user_resources_for_workspace_service", return_value=[])
    @patch("api.routes.workspaces.mark_resource_as_deleting", return_value=None)
    @patch("api.routes.workspaces.send_uninstall_message")
    async def test_delete_workspace_service_marks_the_resource_as_deleting(self, _, mark_resource_mock, __, ___,
                                                                           ____, app, client):
        await client.delete(app.url_path_for(strings.API_DELETE_WORKSPACE_SERVICE, workspace_id=WORKSPACE_ID,
                                             service_id=SERVICE_ID))
        mark_resource_mock.assert_called_once()

    @patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id",
           return_value=disabled_workspace_service())
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @patch("api.routes.workspaces.UserResourceRepository.get_user_resources_for_workspace_service", return_value=[])
    @patch("api.routes.workspaces.mark_resource_as_deleting")
    @patch("api.routes.workspaces.send_uninstall_message")
    async def test_delete_workspace_service_sends_uninstall_message(self, send_uninstall_mock, _, __, ___, ____,
                                                                    app, client):
        await client.delete(app.url_path_for(strings.API_DELETE_WORKSPACE_SERVICE, workspace_id=WORKSPACE_ID,
                                             service_id=SERVICE_ID))
        send_uninstall_mock.assert_called_once()

    @patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id")
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @patch("api.routes.workspaces.UserResourceRepository.get_user_resources_for_workspace_service", return_value=[])
    @patch("api.routes.workspaces.mark_resource_as_deleting")
    @patch("api.routes.workspaces.send_uninstall_message")
    async def test_delete_workspace_service_returns_the_deleted_workspace_service_id(self, _, __, ___, ____,
                                                                                     workspace_service_mock, app,
                                                                                     client):
        workspace_service = disabled_workspace_service()
        workspace_service_mock.return_value = workspace_service
        response = await client.delete(
            app.url_path_for(strings.API_DELETE_WORKSPACE_SERVICE, workspace_id=WORKSPACE_ID,
                             service_id=SERVICE_ID))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["workspaceServiceId"] == workspace_service.id

    # GET /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @ patch("api.routes.workspaces.UserResourceRepository.get_user_resources_for_workspace_service")
    async def test_get_user_resources_returns_all_user_resources_for_workspace_service_if_owner(self, get_user_resources_mock, _, app, client):
        user_resources = [
            sample_user_resource_object(user_resource_id="a33ad738-7265-4b5f-9eae-a1a62928772a"),
            sample_user_resource_object(user_resource_id="b33ad738-7265-4b5f-9eae-a1a62928772a"),
        ]
        get_user_resources_mock.return_value = user_resources

        response = await client.get(app.url_path_for(strings.API_GET_MY_USER_RESOURCES, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["userResources"] == user_resources

    # GET /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources/{resource_id}
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @ patch("api.dependencies.workspaces.UserResourceRepository.get_user_resource_by_id")
    async def test_get_user_resource_returns_a_user_resource_if_found(self, get_user_resource_mock, _, app, client):
        user_resource = sample_user_resource_object()
        get_user_resource_mock.return_value = user_resource

        response = await client.get(app.url_path_for(strings.API_GET_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID, resource_id=USER_RESOURCE_ID))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["userResource"] == user_resource

    # [PATCH] /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources/{resource_id}
    @ patch("api.dependencies.workspaces.UserResourceRepository.get_user_resource_by_id", side_effect=EntityDoesNotExist)
    @ patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id", return_value=sample_workspace_service())
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id", return_value=sample_workspace())
    async def test_patch_user_resource_returns_404_if_user_resource_does_not_exist(self, _, __, ___, app, client):
        response = await client.patch(app.url_path_for(strings.API_UPDATE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID, resource_id=USER_RESOURCE_ID), json={"enabled": True})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # [PATCH] /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources/{resource_id}
    @ patch("api.dependencies.workspaces.UserResourceRepository.get_user_resource_by_id", return_value=sample_user_resource_object())
    @ patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id", return_value=sample_workspace_service())
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id", side_effect=EntityDoesNotExist)
    async def test_patch_user_resource_returns_404_if_ws_does_not_exist(self, _, __, ___, app, client):
        response = await client.patch(app.url_path_for(strings.API_UPDATE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID, resource_id=USER_RESOURCE_ID), json={"enabled": True})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # [PATCH] /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources/{resource_id}
    @pytest.mark.parametrize('workspace_id, workspace_service_id, resource_id', [("IAmNotEvenAGUID!", SERVICE_ID, USER_RESOURCE_ID), (WORKSPACE_ID, "IAmNotEvenAGUID!", USER_RESOURCE_ID), (WORKSPACE_ID, SERVICE_ID, "IAmNotEvenAGUID")])
    @ patch("api.dependencies.workspaces.UserResourceRepository.get_user_resource_by_id", return_value=sample_user_resource_object())
    @ patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id")
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    async def test_patch_user_resource_returns_422_if_invalid_id(self, get_workspace_mock, get_workspace_service_mock, get_user_resource_mock, app, client, workspace_id, workspace_service_id, resource_id):
        user_resource_to_patch = sample_user_resource_object(resource_id, workspace_id, workspace_service_id)
        get_user_resource_mock.return_value = user_resource_to_patch
        get_workspace_mock.return_value = sample_deployed_workspace(workspace_id)
        get_workspace_service_mock.return_value = sample_workspace_service(workspace_service_id, workspace_id)

        response = await client.patch(app.url_path_for(strings.API_UPDATE_USER_RESOURCE, workspace_id=workspace_id, service_id=workspace_service_id, resource_id=resource_id), json={"enabled": True})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # [PATCH] /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources/{resource_id}
    @ patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id", return_value=sample_workspace_service())
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id", return_value=sample_workspace())
    @ patch("api.dependencies.workspaces.UserResourceRepository.get_user_resource_by_id")
    @ patch("api.routes.workspaces.UserResourceRepository.patch_user_resource", return_value=None)
    async def test_patch_user_resources_patches_user_resource(self, patch_user_resource_mock, get_user_resource_mock, _, __, app, client):
        user_resource_to_patch = sample_user_resource_object()
        get_user_resource_mock.return_value = user_resource_to_patch
        user_resource_service_patch = {"enabled": True}

        response = await client.patch(app.url_path_for(strings.API_UPDATE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID, resource_id=USER_RESOURCE_ID), json=user_resource_service_patch)

        patch_user_resource_mock.assert_called_once_with(user_resource_to_patch, user_resource_service_patch)
        assert response.status_code == status.HTTP_200_OK


class TestWorkspaceServiceRoutesThatRequireOwnerOrResearcherRights:
    @pytest.fixture(autouse=True, scope='class')
    def log_in_with_researcher_user(self, app, researcher_user):
        # The following ws services requires the WS app registration
        app.dependency_overrides[get_current_workspace_owner_or_researcher_user_or_tre_admin] = researcher_user
        app.dependency_overrides[get_current_workspace_owner_or_researcher_user] = researcher_user
        yield
        app.dependency_overrides = {}

    # [GET] /workspaces/{workspace_id}
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id", side_effect=EntityDoesNotExist)
    async def test_get_workspace_by_id_get_returns_404_if_resource_is_not_found(self, _, app, client):
        response = await client.get(app.url_path_for(strings.API_GET_WORKSPACE_BY_ID, workspace_id=WORKSPACE_ID))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # [GET] /workspaces/{workspace_id}
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    async def test_get_workspace_by_id_get_returns_422_if_workspace_id_is_not_a_uuid(self, _, app, client):
        response = await client.get(app.url_path_for(strings.API_GET_WORKSPACE_BY_ID, workspace_id="not_valid"))
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # [GET] /workspaces/{workspace_id}
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    async def test_get_workspace_by_id_get_returns_workspace_if_found(self, get_workspace_mock, app, client):
        workspace = sample_workspace()
        get_workspace_mock.return_value = sample_workspace()

        response = await client.get(app.url_path_for(strings.API_GET_WORKSPACE_BY_ID, workspace_id=WORKSPACE_ID))
        actual_resource = response.json()["workspace"]
        assert actual_resource["id"] == workspace.id

    # [GET] /workspaces/{workspace_id}/workspace-services
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id", return_value=sample_workspace())
    @patch("api.routes.workspaces.WorkspaceServiceRepository.get_active_workspace_services_for_workspace",
           return_value=None)
    async def test_get_workspace_services_returns_workspace_services_for_workspace(self,
                                                                                   get_active_workspace_services_mock,
                                                                                   _, app, client):
        workspace_services = [sample_workspace_service()]
        get_active_workspace_services_mock.return_value = workspace_services

        response = await client.get(
            app.url_path_for(strings.API_GET_ALL_WORKSPACE_SERVICES, workspace_id=WORKSPACE_ID))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["workspaceServices"] == workspace_services

    # [GET] /workspaces/{workspace_id}/workspace-services/{service_id}
    @patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id")
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id", side_effect=EntityDoesNotExist)
    async def test_get_workspace_service_raises_404_if_associated_workspace_is_not_found(self, _,
                                                                                         get_workspace_service_mock,
                                                                                         app, client):
        get_workspace_service_mock.return_value = sample_workspace_service(SERVICE_ID, WORKSPACE_ID)

        response = await client.get(
            app.url_path_for(strings.API_GET_WORKSPACE_SERVICE_BY_ID, workspace_id=WORKSPACE_ID,
                             service_id=SERVICE_ID))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    # [GET] /workspaces/{workspace_id}/workspace-services/{service_id}
    @patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id")
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id", return_value=sample_workspace())
    async def test_get_workspace_service_returns_workspace_service_result(self, _, get_workspace_service_mock,
                                                                          app, client):
        workspace_service = sample_workspace_service()
        get_workspace_service_mock.return_value = workspace_service

        response = await client.get(
            app.url_path_for(strings.API_GET_WORKSPACE_SERVICE_BY_ID, workspace_id=WORKSPACE_ID,
                             service_id=SERVICE_ID))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["workspaceService"] == workspace_service

    # [GET] /workspaces/{workspace_id}/workspace-services/{service_id}
    @patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id",
           side_effect=EntityDoesNotExist)
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id", return_value=None)
    async def test_get_workspace_service_raises_404_if_workspace_service_is_not_found(self, _, __, app, client):
        response = await client.get(
            app.url_path_for(strings.API_GET_WORKSPACE_SERVICE_BY_ID, workspace_id=WORKSPACE_ID,
                             service_id=SERVICE_ID))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # [PATCH] /workspaces/{workspace_id}/services/{service_id}
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id", return_value=sample_workspace())
    @ patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id", side_effect=EntityDoesNotExist)
    async def test_patch_workspace_service_returns_404_if_workspace_service_does_not_exist(self, _, __, app, client):
        response = await client.patch(app.url_path_for(strings.API_UPDATE_WORKSPACE_SERVICE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID), json='{"enabled": true}')
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # [PATCH] /workspaces/{workspace_id}/services/{service_id}
    @ patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id", return_value=sample_workspace_service())
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id", side_effect=EntityDoesNotExist)
    async def test_patch_workspace_service_returns_404_if_workspace_does_not_exist(self, _, __, app, client):
        response = await client.patch(app.url_path_for(strings.API_UPDATE_WORKSPACE_SERVICE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID), json='{"enabled": true}')
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # [PATCH] /workspaces/{workspace_id}/services/{service_id}
    @pytest.mark.parametrize('workspace_id, workspace_service_id', [("933ad738-7265-4b5f-9eae-a1a62928772e", "IAmNotEvenAGUID!"), ("IAmNotEvenAGUID!", "933ad738-7265-4b5f-9eae-a1a62928772e")])
    @ patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id")
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    async def test_patch_workspace_service_returns_422_if_invalid_id(self, get_workspace_mock, get_workspace_service_mock, app, client, workspace_id, workspace_service_id):
        workspace_service_to_patch = sample_workspace_service(workspace_service_id, workspace_id)
        get_workspace_service_mock.return_value = workspace_service_to_patch
        get_workspace_mock.return_value = sample_deployed_workspace(workspace_id)

        response = await client.patch(app.url_path_for(strings.API_UPDATE_WORKSPACE_SERVICE, workspace_id=workspace_id, service_id=workspace_service_id), json={"enabled": True})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # [PATCH] /workspaces/{workspace_id}/services/{service_id}
    @ patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id")
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @ patch("api.routes.workspaces.WorkspaceServiceRepository.patch_workspace_service", return_value=None)
    async def test_patch_workspace_service_patches_workspace_service(self, patch_workspace_service_mock, get_workspace_mock, get_workspace_service_mock, app, client):
        auth_info_user_in_workspace_owner_role = {'sp_id': 'ab123', 'roles': {'WorkspaceOwner': 'ab124', 'WorkspaceResearcher': 'ab125'}}

        workspace_service_to_patch = sample_workspace_service()
        get_workspace_service_mock.return_value = workspace_service_to_patch
        get_workspace_mock.return_value = sample_deployed_workspace(WORKSPACE_ID, auth_info_user_in_workspace_owner_role)

        workspace_service_patch = {"enabled": True}

        response = await client.patch(app.url_path_for(strings.API_UPDATE_WORKSPACE_SERVICE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID), json=workspace_service_patch)
        patch_workspace_service_mock.assert_called_once_with(workspace_service_to_patch, workspace_service_patch)

        assert response.status_code == status.HTTP_200_OK

    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @ patch("api.routes.workspaces.UserResourceRepository.get_user_resources_for_workspace_service")
    async def test_get_user_resources_returns_own_user_resources_for_researcher(self, get_user_resources_mock, _, app, client, non_admin_user):
        not_my_user_id = "def"
        my_user_id = non_admin_user().id

        my_user_resource1 = sample_user_resource_object(user_resource_id="a33ad738-7265-4b5f-9eae-a1a62928772a")
        my_user_resource1.ownerId = my_user_id
        my_user_resource2 = sample_user_resource_object(user_resource_id="b33ad738-7265-4b5f-9eae-a1a62928772a")
        my_user_resource2.ownerId = my_user_id
        not_my_user_resource = sample_user_resource_object(user_resource_id="c33ad738-7265-4b5f-9eae-a1a62928772a")
        not_my_user_resource.ownerId = not_my_user_id

        get_user_resources_mock.return_value = [my_user_resource1, my_user_resource2, not_my_user_resource]

        response = await client.get(app.url_path_for(strings.API_GET_MY_USER_RESOURCES, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID))
        assert response.status_code == status.HTTP_200_OK
        actual_returned_resources = response.json()["userResources"]
        assert my_user_resource1 in actual_returned_resources
        assert my_user_resource2 in actual_returned_resources
        assert not_my_user_resource not in actual_returned_resources

    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @ patch("api.dependencies.workspaces.UserResourceRepository.get_user_resource_by_id", side_effect=EntityDoesNotExist)
    async def test_get_user_resource_raises_404_if_resource_not_found(self, _, __, app, client):
        response = await client.get(app.url_path_for(strings.API_GET_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID, resource_id=USER_RESOURCE_ID))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # [POST] /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_deployed_workspace_by_id")
    @patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_deployed_workspace_service_by_id")
    @patch("api.routes.workspaces.UserResourceRepository.create_user_resource_item", side_effect=ValueError)
    async def test_post_user_resources_raises_400_bad_request_if_input_is_bad(self, _, __, get_workspace_mock, app, client, sample_user_resource_input_data):
        auth_info_user_in_workspace_owner_role = {'sp_id': 'ab123', 'roles': {'WorkspaceOwner': 'ab124', 'WorkspaceResearcher': 'ab125'}}
        get_workspace_mock.return_value = sample_workspace(auth_info=auth_info_user_in_workspace_owner_role)

        response = await client.post(app.url_path_for(strings.API_CREATE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID), json=sample_user_resource_input_data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # [POST] /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_deployed_workspace_by_id")
    @patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_deployed_workspace_service_by_id")
    @patch("api.routes.workspaces.send_resource_request_message")
    @patch("api.routes.workspaces.UserResourceRepository.save_item")
    @patch("api.routes.workspaces.UserResourceRepository.create_user_resource_item")
    async def test_post_user_resources_creates_user_resource(self, create_user_resource_item_mock, _, __, ___, get_workspace_mock, app, client, sample_user_resource_input_data):
        auth_info_user_in_workspace_owner_role = {'sp_id': 'ab123', 'roles': {'WorkspaceOwner': 'ab124', 'WorkspaceResearcher': 'ab125'}}
        get_workspace_mock.return_value = sample_workspace(auth_info=auth_info_user_in_workspace_owner_role)

        create_user_resource_item_mock.return_value = sample_user_resource_object()

        response = await client.post(app.url_path_for(strings.API_CREATE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID), json=sample_user_resource_input_data)

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json()["resourceId"] == USER_RESOURCE_ID

    # [POST] /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_deployed_workspace_by_id", side_effect=EntityDoesNotExist)
    async def test_post_user_resources_with_non_existing_workspace_id_returns_404(self, _, app, client, sample_user_resource_input_data):
        response = await client.post(app.url_path_for(strings.API_CREATE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID), json=sample_user_resource_input_data)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # [POST] /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_deployed_workspace_by_id")
    @patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_deployed_workspace_service_by_id", side_effect=EntityDoesNotExist)
    async def test_post_user_resources_with_non_existing_service_id_returns_404(self, _, __, app, client, sample_user_resource_input_data):
        response = await client.post(app.url_path_for(strings.API_CREATE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID), json=sample_user_resource_input_data)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # [POST] /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    async def test_post_user_resources_with_non_deployed_workspace_id_returns_404(self, get_deployed_workspace_by_workspace_id_mock, app, client, sample_user_resource_input_data):
        workspace = sample_workspace()
        workspace.deployment.status = Status.Failed
        get_deployed_workspace_by_workspace_id_mock.return_value = workspace

        response = await client.post(app.url_path_for(strings.API_CREATE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID), json=sample_user_resource_input_data)

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.text == strings.WORKSPACE_IS_NOT_DEPLOYED

    # [POST] /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id")
    async def test_post_user_resources_with_non_deployed_service_id_returns_404(self, get_workspace_service_mock, get_workspace_mock, app, client, sample_user_resource_input_data):
        workspace = sample_workspace()
        workspace.deployment.status = Status.Deployed
        get_workspace_mock.return_value = workspace

        workspace_service = sample_workspace_service()
        workspace_service.deployment.status = Status.Failed
        get_workspace_service_mock.return_value = workspace_service

        response = await client.post(app.url_path_for(strings.API_CREATE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID), json=sample_user_resource_input_data)

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.text == strings.WORKSPACE_SERVICE_IS_NOT_DEPLOYED

    # [PATCH] /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources/{resource_id}
    @ patch("api.dependencies.workspaces.UserResourceRepository.get_user_resource_by_id", side_effect=EntityDoesNotExist)
    @ patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id", return_value=sample_workspace_service())
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id", return_value=sample_workspace())
    async def test_patch_user_resource_returns_404_if_user_resource_does_not_exist(self, _, __, ___, app, client):
        response = await client.patch(app.url_path_for(strings.API_UPDATE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID, resource_id=USER_RESOURCE_ID), json={"enabled": True})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # [PATCH] /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources/{resource_id}
    @ patch("api.dependencies.workspaces.UserResourceRepository.get_user_resource_by_id", return_value=sample_user_resource_object())
    @ patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id", return_value=sample_workspace_service())
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id", side_effect=EntityDoesNotExist)
    async def test_patch_user_resource_returns_404_if_ws_does_not_exist(self, _, __, ___, app, client):
        response = await client.patch(app.url_path_for(strings.API_UPDATE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID, resource_id=USER_RESOURCE_ID), json={"enabled": True})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    # [PATCH] /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources/{resource_id}
    @pytest.mark.parametrize('workspace_id, workspace_service_id, resource_id', [("IAmNotEvenAGUID!", SERVICE_ID, USER_RESOURCE_ID), (WORKSPACE_ID, "IAmNotEvenAGUID!", USER_RESOURCE_ID), (WORKSPACE_ID, SERVICE_ID, "IAmNotEvenAGUID")])
    @ patch("api.dependencies.workspaces.UserResourceRepository.get_user_resource_by_id", return_value=sample_user_resource_object())
    @ patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id")
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    async def test_patch_user_resource_returns_422_if_invalid_id(self, get_workspace_mock, get_workspace_service_mock, get_user_resource_mock, app, client, workspace_id, workspace_service_id, resource_id):
        user_resource_to_patch = sample_user_resource_object(resource_id, workspace_id, workspace_service_id)
        get_user_resource_mock.return_value = user_resource_to_patch
        get_workspace_mock.return_value = sample_deployed_workspace(workspace_id)
        get_workspace_service_mock.return_value = sample_workspace_service(workspace_service_id, workspace_id)

        response = await client.patch(app.url_path_for(strings.API_UPDATE_USER_RESOURCE, workspace_id=workspace_id, service_id=workspace_service_id, resource_id=resource_id), json={"enabled": True})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # [PATCH] /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources/{resource_id}
    @ patch("api.routes.workspaces.validate_user_is_workspace_owner_or_resource_owner")
    @ patch("api.dependencies.workspaces.WorkspaceServiceRepository.get_workspace_service_by_id", return_value=sample_workspace_service())
    @ patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id", return_value=sample_workspace())
    @ patch("api.dependencies.workspaces.UserResourceRepository.get_user_resource_by_id")
    @ patch("api.routes.workspaces.UserResourceRepository.patch_user_resource", return_value=None)
    async def test_patch_user_resources_patches_user_resource(self, patch_user_resource_mock, get_user_resource_mock, _, __, ___, app, client):
        user_resource_to_patch = sample_user_resource_object()
        get_user_resource_mock.return_value = user_resource_to_patch
        user_resource_service_patch = {"enabled": True}

        response = await client.patch(app.url_path_for(strings.API_UPDATE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID, resource_id=USER_RESOURCE_ID), json=user_resource_service_patch)

        patch_user_resource_mock.assert_called_once_with(user_resource_to_patch, user_resource_service_patch)
        assert response.status_code == status.HTTP_200_OK

    # [DELETE] /workspaces/{workspace_id}/workspace-services/{service_id}/user-resources
    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @patch("api.dependencies.workspaces.UserResourceRepository.get_user_resource_by_id")
    @patch("api.routes.workspaces.validate_user_is_workspace_owner_or_resource_owner")
    async def test_delete_user_resource_raises_400_if_user_resource_is_enabled(self, _, get_user_resource_mock, ___, app, client):
        user_resource = sample_user_resource_object()
        user_resource.properties["enabled"] = True
        get_user_resource_mock.return_value = user_resource

        response = await client.delete(app.url_path_for(strings.API_DELETE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID, resource_id=USER_RESOURCE_ID))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @patch("api.dependencies.workspaces.UserResourceRepository.get_user_resource_by_id", return_value=disabled_user_resource())
    @patch("api.routes.workspaces.validate_user_is_workspace_owner_or_resource_owner")
    @patch("api.routes.workspaces.mark_resource_as_deleting", return_value=None)
    @patch("api.routes.workspaces.send_uninstall_message")
    async def test_delete_user_resource_marks_resource_as_deleting(self, _, mark_resource_mock, __, ___, ____, app, client):
        await client.delete(app.url_path_for(strings.API_DELETE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID, resource_id=USER_RESOURCE_ID))
        mark_resource_mock.assert_called_once()

    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @patch("api.dependencies.workspaces.UserResourceRepository.get_user_resource_by_id", return_value=disabled_user_resource())
    @patch("api.routes.workspaces.validate_user_is_workspace_owner_or_resource_owner")
    @patch("api.routes.workspaces.mark_resource_as_deleting")
    @patch("api.routes.workspaces.send_uninstall_message", return_value=None)
    async def test_delete_user_resource_sends_uninstall_message(self, send_uninstall_mock, _, __, ___, ____, app, client):
        await client.delete(app.url_path_for(strings.API_DELETE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID, resource_id=USER_RESOURCE_ID))
        send_uninstall_mock.assert_called_once()

    @patch("api.dependencies.workspaces.WorkspaceRepository.get_workspace_by_id")
    @patch("api.dependencies.workspaces.UserResourceRepository.get_user_resource_by_id")
    @patch("api.routes.workspaces.validate_user_is_workspace_owner_or_resource_owner")
    @patch("api.routes.workspaces.mark_resource_as_deleting")
    @patch("api.routes.workspaces.send_uninstall_message")
    async def test_delete_user_resource_returns_resource_id(self, _, __, ___, get_user_resource_mock, ____, app, client):
        user_resource = disabled_user_resource()
        get_user_resource_mock.return_value = user_resource

        response = await client.delete(app.url_path_for(strings.API_DELETE_USER_RESOURCE, workspace_id=WORKSPACE_ID, service_id=SERVICE_ID, resource_id=USER_RESOURCE_ID))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["resourceId"] == user_resource.id
