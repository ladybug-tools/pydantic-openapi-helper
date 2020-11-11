import enum

from pydantic.utils import get_model
from pydantic.schema import schema, get_flat_models_from_model, get_model_name_map

from .helper import _OpenAPIGenBaseModel, inherit_fom_basemodel


# list of top level class names that we should stop at
STOPPAGE = set(['NoExtraBaseModel', 'ModelMetaclass', 'BaseModel', 'object', 'Enum'])


def get_schemas_inheritance(model_cls):
    """This method modifies the default OpenAPI from Pydantic.

    It adds referenced values to subclasses using allOf field as explained in this post:
    https://swagger.io/docs/specification/data-models/inheritance-and-polymorphism
    """

    # get a dictionary that maps the name of each model schema to its Pydantic class.
    model_name_map = get_model_mapper(model_cls, STOPPAGE, full=True, include_enum=False)

    # get the standard OpenAPI schema for Pydantic for all the new objects
    ref_prefix = '#/components/schemas/'
    schemas = \
        schema(model_name_map.values(), ref_prefix=ref_prefix)['definitions']

    # add the [possibly] needed baseclass to the list of classes
    schemas['_OpenAPIGenBaseModel'] = dict(eval(_OpenAPIGenBaseModel.schema_json()))
    model_name_map['_OpenAPIGenBaseModel'] = _OpenAPIGenBaseModel

    # An empty dictionary to collect updated objects
    updated_schemas = {}

    # iterate through all the data models
    # find the ones which are subclassed and updated them based on the properties of
    # baseclasses.
    for name in schemas.keys():
        # find the class object from class name
        try:
            main_cls = model_name_map[name]
        except KeyError:
            # enum objects are not included.
            if 'enum' in schemas[name]:
                continue
            raise KeyError(f'{name} key not found.')

        top_classes = get_ancestors(main_cls)
        if not top_classes:
            # update the object to inherit from baseclass which only has type
            # this is required for dotnet bindings
            if name != '_OpenAPIGenBaseModel':
                updated_schemas[name] = inherit_fom_basemodel(schemas[name])
            continue

        # Do the real work and update the current schema to use inheritance
        updated_schemas[name] = set_inheritance(name, top_classes, schemas)

    # replace updated schemas in original schema
    for name, value in updated_schemas.items():
        schemas[name] = value

    return schemas


def get_ancestors(cls):
    # use type.mro to go through all the ancestors for this class and collect them
    top_classes = []
    for cls in type.mro(cls):
        if cls.__name__ in STOPPAGE:
            break
        top_classes.append(cls)
    if len(top_classes) < 2:
        # this class is not a subclass
        return []
    else:
        return top_classes


def _check_object_types(source, target, prop):
    """Check if objects with same name have different types.

    In such a case we need to subclass from one higher level.
    """
    if 'type' in source:
        if source['type'] != 'array':
            return source['type'] != target[prop]
        else:
            # for an array check both the type and the type for items
            return (source['type'], source['items']) != target[prop]


def set_inheritance(name, top_classes, schemas):
    """Set inheritance for an object.

    Args:
        name: name of the object.
        top_classes: List of ancestors for this class.
        schemas: A dictionary of all the schema objects.

    Returns:
        Dict - updated schema for the object with the input name.
    """
    # this is the list of special keys that we copy in manually
    copied_keys = set(['type', 'properties', 'required', 'additionalProperties'])
    # remove the class itself
    print(f'\nProcessing {name}')
    top_classes = top_classes[1:]
    top_class = top_classes[0]
    tree = ['....' * (i + 1) + c.__name__ for i, c in enumerate(top_classes)]
    print('\n'.join(tree))

    # the immediate top class openapi schema
    object_dict = schemas[name]
    if 'enum' in object_dict:
        return object_dict

    # collect required and properties from top classes and do not include them in
    # the object itself so we don't end up with duplicate values in the schema for
    # the subclass - if it is required then it will be provided upstream.
    top_classes_required = []
    top_classes_prop = {}

    # collect required keys
    for t in top_classes:
        try:
            schema_t = schemas[t.__name__]
        except KeyError as error:
            raise KeyError(f'Failed to find the model name: {error}')

        try:
            tc_required = schema_t['required']
        except KeyError:
            # no required field
            continue

        for r in tc_required:
            top_classes_required.append(r)

    # collect properties
    for t in top_classes:
        tc_prop = schemas[t.__name__]['properties']
        for pn, dt in tc_prop.items():
            # collect type for every field. This is helpful to catch the cases where
            # the same field name has a different new type in the subclass and should be
            # kept to overwrite the original field.
            if 'type' in dt:
                if dt['type'] == 'array':
                    # collect both the type and the type for its items
                    top_classes_prop[pn] = dt['type'], dt['items']
                else:
                    top_classes_prop[pn] = dt['type']
            else:
                top_classes_prop[pn] = '###'  # no type means use of oneOf or allOf

    # create a new schema for this object based on the top level class
    data = {
        'allOf': [
            {
                '$ref': f'#/components/schemas/{top_class.__name__}'
            },
            {
                'type': 'object',
                'required': [],
                'properties': {}
            }
        ]
    }

    data_copy = dict(data)

    if not top_classes_required and 'required' in object_dict:
        # no required in top level class
        # add all the required to the subclass
        for r in object_dict['required']:
            data_copy['allOf'][1]['required'].append(r)
    elif 'required' in object_dict and top_classes_required:
        # only add the new required fields
        for r in object_dict['required']:
            if r not in top_classes_required:
                data_copy['allOf'][1]['required'].append(r)

    # no required fields - delete it from the dictionary
    if len(data_copy['allOf'][1]['required']) == 0:
        del(data_copy['allOf'][1]['required'])

    # get full list of the properties and add the ones that doesn't exist in 
    # ancestor objects.
    properties = object_dict['properties']
    for prop, values in properties.items():
        if prop not in top_classes_prop:
            # new field. add it to the properties
            print(f'Extending: {prop}')
            data_copy['allOf'][1]['properties'][prop] = values
        elif _check_object_types(values, top_classes_prop, prop) \
                or 'type' not in values and ('allOf' in values or 'anyOf' in values):
            # same name different types
            print(f'Found a field with the same name: {prop}.')
            if len(top_classes) > 1:
                print(f'Trying {name} against {top_classes[1].__name__}.')
                return set_inheritance(name, top_classes, schemas)
            else:
                # try against a base object.
                print(f'Trying {name} against OpenAPI base object.')
                _top_classes = [_OpenAPIGenBaseModel, _OpenAPIGenBaseModel]
                return set_inheritance(name, _top_classes, schemas)

    try:
        data_copy['allOf'][1]['properties']['type'] = properties['type']
    except KeyError:
        print(f'Found object with no type:{name}')

    if 'additionalProperties' in object_dict:
        data_copy['allOf'][1]['additionalProperties'] = \
            object_dict['additionalProperties']

    # add other items in addition to copied_keys
    for key, value in schemas[name].items():
        if key in copied_keys:
            continue
        data_copy[key] = value
    return data_copy


def get_model_mapper(models, stoppage=None, full=True, include_enum=False):
    """Get a dictionary of name: class for all the objects in model."""
    models = [get_model(model) for model in models]
    if include_enum:
        flat_models = [
            m
            for model in models
            for m in get_flat_models_from_model(model)
        ]
    else:
        flat_models = [
            m
            for model in models
            for m in get_flat_models_from_model(model)
            if not isinstance(m, enum.EnumMeta)
        ]

    flat_models = list(set(flat_models))

    # this is the list of all the referenced objects
    model_name_map = get_model_name_map(flat_models)
    # flip the dictionary so I can access each class by name
    model_name_map = {v: k for k, v in model_name_map.items()}

    if full:
        if not stoppage:
            stoppage = set(
                [
                    'NoExtraBaseModel', 'ModelMetaclass', 'BaseModel', 'object', 'str',
                    'Enum'
                ]
            )
        # Pydantic does not necessarily add all the baseclasses to the OpenAPI
        # documentation. We check all of them and them to the list if they are not
        # already added
        models = list(model_name_map.values())
        for model in models:
            for cls in type.mro(model):
                if cls.__name__ in stoppage:
                    break
                if cls.__name__ not in model_name_map:
                    model_name_map[cls.__name__] = cls

    return model_name_map


def class_mapper(models, find_and_replace=None):
    """Create a mapper between OpenAPI models and Python modules.

    This mapper is used by dotnet generator to organize the models under similar
    module structure.

    Args:
        models: Input Pydantic models.
        find_and_replace: A list of two string values for pattern and what  it should be
            replaced with.

    """

    if not hasattr(models, '__iter__'):
        models = [models]

    mapper = get_model_mapper(models, full=True, include_enum=True)

    # add enum classes to mapper
    schemas = get_schemas_inheritance(models)
    enums = {}
    for name in schemas:
        s = schemas[name]
        if 'enum' in s:
            # add enum
            info = mapper[name]
            if info.__name__ not in enums:
                enums[info.__name__] = info

    module_mapper = {}
    # remove enum from mapper
    classes = {k: c.__module__ for k, c in mapper.items() if k not in enums}
    enums = {k: c.__module__ for k, c in enums.items()}

    if find_and_replace:
        fi, rep = find_and_replace
        for k, v in classes.items():
            classes[k] = v.replace(fi, rep)
        for k, v in enums.items():
            enums[k] = v.replace(fi, rep)

    # this sorting only works in python3.7+
    module_mapper['classes'] = {k: classes[k] for k in sorted(classes)}
    module_mapper['enums'] = {k: enums[k] for k in sorted(enums)}

    return module_mapper
