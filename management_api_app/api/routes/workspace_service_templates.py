import logging

from fastapi import APIRouter, Depends, HTTPException
from starlette import status

from api.dependencies.database import get_repository
from api.dependencies.workspace_service_templates import get_workspace_service_template_by_name_from_path
from db.errors import EntityVersionExist, EntityDoesNotExist
from db.repositories.resource_templates import ResourceTemplateRepository
from models.domain.resource import ResourceType
from models.schemas.user_resource_template import UserResourceTemplateInResponse, UserResourceTemplateInCreate
from models.schemas.resource_template import ResourceTemplateInResponse, ResourceTemplateInformationInList
from models.schemas.workspace_service_template import WorkspaceServiceTemplateInCreate, WorkspaceServiceTemplateInResponse
from resources import strings
from services.authentication import get_current_admin_user, get_current_user


router = APIRouter()


@router.get("/workspace-service-templates", response_model=ResourceTemplateInformationInList, name=strings.API_GET_WORKSPACE_SERVICE_TEMPLATES, dependencies=[Depends(get_current_admin_user)])
async def get_workspace_service_templates(template_repo=Depends(get_repository(ResourceTemplateRepository))) -> ResourceTemplateInformationInList:
    templates_infos = template_repo.get_templates_information(ResourceType.WorkspaceService)
    return ResourceTemplateInformationInList(templates=templates_infos)


@router.get("/workspace-service-templates/{template_name}", response_model=WorkspaceServiceTemplateInResponse, name=strings.API_GET_WORKSPACE_SERVICE_TEMPLATE_BY_NAME, dependencies=[Depends(get_current_admin_user)])
async def get_current_workspace_service_template_by_name(template_name: str, template_repo=Depends(get_repository(ResourceTemplateRepository))) -> WorkspaceServiceTemplateInResponse:
    try:
        template = template_repo.get_current_template(template_name, ResourceType.WorkspaceService)
        return template_repo.enrich_template(template)
    except EntityDoesNotExist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=strings.TEMPLATE_DOES_NOT_EXIST)
    except Exception as e:
        logging.debug(e)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=strings.STATE_STORE_ENDPOINT_NOT_RESPONDING)


@router.post("/workspace-service-templates", status_code=status.HTTP_201_CREATED, response_model=WorkspaceServiceTemplateInResponse, name=strings.API_CREATE_WORKSPACE_SERVICE_TEMPLATES, dependencies=[Depends(get_current_admin_user)])
async def register_workspace_service_template(template_input: WorkspaceServiceTemplateInCreate, template_repo=Depends(get_repository(ResourceTemplateRepository))) -> ResourceTemplateInResponse:
    try:
        return template_repo.create_and_validate_template(template_input, ResourceType.WorkspaceService)
    except EntityVersionExist:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=strings.WORKSPACE_TEMPLATE_VERSION_EXISTS)


@router.get("/workspace-service-templates/{template_name}/user-resource-templates", response_model=ResourceTemplateInformationInList, name=strings.API_GET_USER_RESOURCE_TEMPLATES, dependencies=[Depends(get_current_user)])
async def get_user_resource_templates_for_service_template(template_name: str, template_repo=Depends(get_repository(ResourceTemplateRepository))) -> ResourceTemplateInformationInList:
    template_infos = template_repo.get_templates_information(ResourceType.UserResource, template_name)
    return ResourceTemplateInformationInList(templates=template_infos)


@router.post("/workspace-service-templates/{template_name}/user-resource-templates", status_code=status.HTTP_201_CREATED, response_model=UserResourceTemplateInResponse, name=strings.API_CREATE_USER_RESOURCE_TEMPLATES, dependencies=[Depends(get_current_admin_user)])
async def register_user_resource_template(template_input: UserResourceTemplateInCreate, template_repo=Depends(get_repository(ResourceTemplateRepository)), workspace_service_template=Depends(get_workspace_service_template_by_name_from_path)) -> UserResourceTemplateInResponse:
    try:
        return template_repo.create_and_validate_template(template_input, ResourceType.UserResource, workspace_service_template.name)
    except EntityVersionExist:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=strings.WORKSPACE_TEMPLATE_VERSION_EXISTS)