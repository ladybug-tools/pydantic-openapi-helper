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


def clean_schemas(
        schemas, add_tags=True, add_discriminator=False, add_type=False
        ):
    # goes to tags
    tags = []
    # goes to x-tagGroups['tags']
    tag_names = []

    schema_names = list(schemas.keys())
    schema_names.sort()

    for name in schema_names:
        if add_tags:
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
            if add_type:
                # no type has been set in properties for this object
                typ = {
                    'title': 'Type', 'default': f'{name}', 'type': 'string',
                    'pattern': f'^{name}$', 'readOnly': True,
                }
                properties['type'] = typ
        else:
            if not isinstance(properties['type'], dict) or \
                    'default' not in properties['type']:
                print(f'\t\tType is a protected key for class name: {name}.')
            elif properties['type']['default'] != name:
                print(
                    f'\t\tType is a protected key for class name: {name}.\n'
                    f'\t\tCurrent value is {properties["type"]["default"]}'
                )

        if add_discriminator:
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
    return schemas, tags, tag_names
