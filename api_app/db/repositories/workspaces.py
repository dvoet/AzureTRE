import uuid
from typing import List

from azure.cosmos import CosmosClient
from pydantic import parse_obj_as

from core import config
from db.errors import ResourceIsNotDeployed, EntityDoesNotExist
from db.repositories.resources import ResourceRepository
from models.domain.resource import Deployment, Status, ResourceType
from models.domain.workspace import Workspace
from models.schemas.workspace import WorkspaceInCreate, WorkspacePatchEnabled
from resources import strings
from services.cidr_service import generate_new_cidr


class WorkspaceRepository(ResourceRepository):
    def __init__(self, client: CosmosClient):
        super().__init__(client)

    @staticmethod
    def active_workspaces_query_string():
        return f'SELECT * FROM c WHERE c.resourceType = "{ResourceType.Workspace}" AND c.deployment.status != "{Status.Deleted}"'

    def get_active_workspaces(self) -> List[Workspace]:
        query = WorkspaceRepository.active_workspaces_query_string()
        workspaces = self.query(query=query)
        return parse_obj_as(List[Workspace], workspaces)

    def get_deployed_workspace_by_id(self, workspace_id: str) -> Workspace:
        workspace = self.get_workspace_by_id(workspace_id)

        if workspace.deployment.status != Status.Deployed:
            raise ResourceIsNotDeployed

        return workspace

    def get_workspace_by_id(self, workspace_id: str) -> Workspace:
        query = self.active_workspaces_query_string() + f' AND c.id = "{workspace_id}"'
        workspaces = self.query(query=query)
        if not workspaces:
            raise EntityDoesNotExist
        return parse_obj_as(Workspace, workspaces[0])

    def create_workspace_item(self, workspace_input: WorkspaceInCreate, auth_info: dict) -> Workspace:
        full_workspace_id = str(uuid.uuid4())

        template_version = self.validate_input_against_template(workspace_input.templateName, workspace_input, ResourceType.Workspace)

        # if address_space isn't provided in the input, generate a new one.
        # TODO: #772 check that the provided address_space is available in the network.
        # TODO: #773 allow custom sized networks to be requested
        address_space_param = {"address_space": workspace_input.properties.get("address_space") or self.get_new_address_space()}

        # we don't want something in the input to overwrite the system parameters, so dict.update can't work. Priorities from right to left.
        resource_spec_parameters = {**workspace_input.properties, **address_space_param, **self.get_workspace_spec_params(full_workspace_id)}

        workspace = Workspace(
            id=full_workspace_id,
            templateName=workspace_input.templateName,
            templateVersion=template_version,
            properties=resource_spec_parameters,
            deployment=Deployment(status=Status.NotDeployed, message=strings.RESOURCE_STATUS_NOT_DEPLOYED_MESSAGE),
            authInformation=auth_info
        )

        return workspace

    def get_new_address_space(self, cidr_netmask: int = 24):
        networks = [x.properties["address_space"] for x in self.get_active_workspaces()]

        new_address_space = generate_new_cidr(networks, cidr_netmask)
        return new_address_space

    def patch_workspace(self, workspace: Workspace, workspace_patch: WorkspacePatchEnabled):
        workspace.properties["enabled"] = workspace_patch.enabled
        self.update_item(workspace)

    def get_workspace_spec_params(self, full_workspace_id: str):
        params = self.get_resource_base_spec_params()
        params.update({
            "azure_location": config.RESOURCE_LOCATION,
            "workspace_id": full_workspace_id[-4:],  # TODO: remove with #729
        })
        return params
