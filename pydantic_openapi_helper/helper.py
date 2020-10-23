"""Helper functions."""
from pydantic import BaseModel, Field


def create_tag(name):
    """Create a viewer tag from a class name.

    This tag is specific to redocly and will be ignored by generators and other viewers.
    """
    model_name = '%s_model' % name.lower()
    tag = {
        'name': model_name,
        'x-displayName': name,
        'description':
            '<SchemaDefinition schemaRef=\"#/components/schemas/%s\" />\n' % name
    }
    return model_name, tag


def set_format(p):
    """Set format for numbers and integers.

    This is helpful for dotnet code generator.
    """
    if '$ref' in p:
        return p
    elif p['type'] == 'number' and 'format' not in p:
        p['format'] = 'double'
    elif p['type'] == 'integer' and 'format' not in p:
        p['format'] = 'int32'
    elif p['type'] == 'array':
        if p['items']:
            # in some cases the items is left empty - I assume that means any type is
            # allowed.
            p['items'] = set_format(p['items'])
    return p


class _OpenAPIGenBaseModel(BaseModel):

    type: str = Field(
        'InvalidType',
        description='A base class to use when there is no baseclass available to fall '
        'on.'
    )


def inherit_fom_basemodel(model: dict):
    """Change the schema to inherit from _OpenAPIGenBaseModel."""
    base = {
        'allOf': [
          {
            '$ref': '#/components/schemas/_OpenAPIGenBaseModel'
          },
          {
            'type': 'object',
            'properties': {}
          }
        ]
    }

    high_level_keys = {'title', 'description'}

    for key, value in model.items():
        if key in high_level_keys:
            base[key] = model[key]
        else:
            base['allOf'][1][key] = value

    return base
