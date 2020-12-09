from typing import List, Any, Dict

from pydantic.schema import schema

from .helper import clean_schemas
from .inheritance import get_schemas_inheritance


"""base open api dictionary for all schemas."""
_base_open_api = {
    "openapi": "3.0.2",
    "servers": [],
    "info": {},
    "externalDocs": {},
    "tags": [],
    "x-tagGroups": [
        {
            "name": "Models",
            "tags": []
        }
    ],
    "paths": {},
    "components": {"schemas": {}}
}


def get_openapi(
    base_object: List[Any],
    title: str = None,
    version: str = None,
    openapi_version: str = "3.0.2",
    description: str = None,
    info: dict = None,
    external_docs: dict = None,
    inheritance: bool = False,
    add_discriminator: bool = True
        ) -> Dict:
    """Get openapi compatible dictionary from a list of Pydantic objects.

    Args:
        base_objects: A list of Pydantic model objects to be included in the OpenAPI
            schema.
        title: An optional title for OpenAPI title in info field.
        version: Schema version to set the version in info.
        openapi_version: Version for OpenAPI schema. Default is 3.0.2.
        description: A short description for schema info.
        info: Schema info as a dictionary. You can use this input to provide title,
            version and description together.
        external_docs: Link to external docs for schema.
        inheritance: A boolean to wheather the OpenAPI specification should be modified
            to use polymorphism. We use Pydantic to generate the initial version and then
            post-process the output dictionary to generate the new schema.

    Returns:
        Dict -- OpenAPI schema as a dictionary.
    """

    open_api = dict(_base_open_api)

    open_api['openapi'] = openapi_version

    if info:
        open_api['info'] = info

    if title:
        open_api['info']['title'] = title

    if not version:
        raise ValueError(
            'Schema version must be specified as argument or from distribution metadata'
        )

    if version:
        open_api['info']['version'] = version

    if description:
        open_api['info']['description'] = description

    if external_docs:
        open_api['externalDocs'] = external_docs

    if not inheritance:
        schemas = schema(base_object, ref_prefix='#/components/schemas/')['definitions']
    else:
        schemas = get_schemas_inheritance(base_object)

    schemas, tags, tag_names = clean_schemas(
        schemas, add_tags=True, add_discriminator=inheritance and add_discriminator,
        add_type=True
    )

    open_api['tags'] = tags
    open_api['x-tagGroups'][0]['tags'] = tag_names

    open_api['components']['schemas'] = schemas

    return open_api
