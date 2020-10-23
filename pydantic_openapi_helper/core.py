from typing import List, Any, Dict

from pydantic.schema import schema

from .helper import create_tag, set_format
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
    inheritance: bool = False
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

    # goes to tags
    tags = []
    # goes to x-tagGroups['tags']
    tag_names = []

    schema_names = list(schemas.keys())
    schema_names.sort()

    for name in schema_names:
        model_name, tag = create_tag(name)
        tag_names.append(model_name)
        tags.append(tag)

        # sort properties order: put required parameters at begining of the list
        s = schemas[name]

        if 'properties' in s:
            properties = s['properties']
        elif 'enum' in s:
            # enum
            continue
        else:
            properties = s['allOf'][1]['properties']

        # make all types readOnly
        try:
            properties['type']['readOnly'] = True
        except KeyError:
            # no type has been set in properties for this object
            typ = {
                'title': 'Type', 'default': f'{name}', 'type': 'string',
                'pattern': f'^{name}$', 'readOnly': True,
            }
            properties['type'] = typ

        # add descriminator to every object
        # in Ladybug Tools libraries it is always the type property
        s['discriminator'] = {'propertyName': 'type'}

        # add format to numbers and integers
        # this is helpful for C# generators
        for prop in properties:
            try:
                properties[prop] = set_format(properties[prop])
            except KeyError:
                # referenced object
                if 'anyOf' in properties[prop]:
                    new_any_of = []
                    for item in properties[prop]['anyOf']:
                        new_any_of.append(set_format(item))
                    properties[prop]['anyOf'] = new_any_of
                else:
                    continue

        # sort fields to keep required ones on top
        if 'required' in s:
            required = s['required']
        elif 'allOf' in s:
            try:
                required = s['allOf'][1]['required']
            except KeyError:
                # no required field
                continue
        else:
            continue

        sorted_props = {}
        optional = {}
        for prop, value in properties.items():
            if prop in required:
                sorted_props[prop] = value
            else:
                optional[prop] = value

        sorted_props.update(optional)

        if 'properties' in s:
            s['properties'] = sorted_props
        else:
            s['allOf'][1]['properties'] = sorted_props

    tag_names.sort()
    open_api['tags'] = tags
    open_api['x-tagGroups'][0]['tags'] = tag_names

    open_api['components']['schemas'] = schemas

    return open_api
