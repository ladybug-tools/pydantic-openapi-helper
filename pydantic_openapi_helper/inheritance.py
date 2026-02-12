import enum
from typing import List, Any, Union

from pydantic import BaseModel, TypeAdapter

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
    # V2 Change: Use TypeAdapter to generate schema.
    # Reference template replaces ref_prefix.
    # Definitions are now found in '$defs'.
    adapter = TypeAdapter(List[Any])
    # We create a dummy schema including all found models to ensure they are in definitions
    # However, generating schema for the list of values is the standard way.
    json_schema = adapter.json_schema(
        ref_template='#/components/schemas/{model}'
    )
    # We might need to ensure all models are actually referenced or included.
    # For a robust generation, we might want to generate the schema for the union of all models.
    # But sticking to the pattern of passing the list of models:
    # In V2, generating schema for a list of Types doesn't automatically populate $defs
    # with those types unless they are referenced.
    # A better approach in V2 for a flat list of models is generating for each or a Union.
    # Let's try to mimic the V1 behavior by creating a TypeAdapter for a Union of all models.

    # Simpler approach compatible with previous logic:
    # Use the discovered models to build the schema.
    if not model_name_map:
        schemas = {}
    else:
        # Create a union of all types to force generation of definitions
        UnionType = Any # Fallback
        if len(model_name_map) > 0:
            UnionType = List[Union[tuple(model_name_map.values())]]

        adapter = TypeAdapter(UnionType)
        full_schema = adapter.json_schema(ref_template='#/components/schemas/{model}')
        schemas = full_schema.get('$defs', {})


    # add the [possibly] needed baseclass to the list of classes
    # V2 Change: .model_json_schema() returns a dict, no eval needed.
    schemas['_OpenAPIGenBaseModel'] = _OpenAPIGenBaseModel.model_json_schema()
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
            # In V2, some auxiliary schemas might appear in $defs that aren't mapped models
            # We can skip them if they aren't in our map
            continue

        else:
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
    if not hasattr(cls, 'mro'):
        return []
    for cls in cls.mro():
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
            return (source['type'], source.get('items')) != target[prop]


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
            # It's possible an ancestor isn't in schemas if it wasn't exported
            # or if it is a base type.
            continue 

        # V2: use .get() as required is optional
        tc_required = schema_t.get('required', [])
        for r in tc_required:
            top_classes_required.append(r)

    # collect properties
    for t in top_classes:
        if t.__name__ not in schemas: continue
        tc_prop = schemas[t.__name__].get('properties', {})
        for pn, dt in tc_prop.items():
            # collect type for every field. This is helpful to catch the cases where
            # the same field name has a different new type in the subclass and should be
            # kept to overwrite the original field.
            if 'type' in dt:
                if dt['type'] == 'array':
                    # collect both the type and the type for its items
                    top_classes_prop[pn] = dt['type'], dt.get('items')
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

    current_required = object_dict.get('required', [])

    if not top_classes_required and current_required:
        # no required in top level class
        # add all the required to the subclass
        for r in current_required:
            data_copy['allOf'][1]['required'].append(r)
    elif current_required and top_classes_required:
        # only add the new required fields
        for r in current_required:
            if r not in top_classes_required:
                data_copy['allOf'][1]['required'].append(r)

    # no required fields - delete it from the dictionary
    if len(data_copy['allOf'][1]['required']) == 0:
        del(data_copy['allOf'][1]['required'])

    # get full list of the properties and add the ones that doesn't exist in
    # ancestor objects.
    properties = object_dict.get('properties', {})
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

    if 'type' in properties:
        data_copy['allOf'][1]['properties']['type'] = properties['type']

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
    # Pydantic V2 does not have get_flat_models_from_model.
    # We must manually traverse the models to find dependencies.
    model_name_map = {}

    if not isinstance(models, (list, tuple)):
        models = [models]

    stack = list(models)
    visited = set()

    while stack:
        m = stack.pop()

        # Skip if not a class or already visited
        if not isinstance(m, type) or m in visited:
            continue

        visited.add(m)

        # Check for Pydantic Model
        is_model = False
        try:
            if issubclass(m, BaseModel):
                is_model = True
        except TypeError:
            pass

        # Check for Enum
        is_enum = isinstance(m, enum.EnumMeta)

        if is_model or is_enum:
            model_name_map[m.__name__] = m

        if is_model:
            # Recurse into fields
            for field_name, field_info in m.model_fields.items():
                # In V2, annotation holds the type
                ann = field_info.annotation
                if hasattr(ann, '__origin__'):
                    # Handle List[], Union[], etc.
                    args = getattr(ann, '__args__', [])
                    for arg in args:
                        if isinstance(arg, type):
                            stack.append(arg)
                elif isinstance(ann, type):
                    stack.append(ann)

    if full:
        stoppage = stoppage or set(
            ['NoExtraBaseModel', 'ModelMetaclass', 'BaseModel', 'object', 'str', 'Enum']
        )

        # Collect ancestors
        current_models = list(model_name_map.values())
        for model in current_models:
            if hasattr(model, 'mro'):
                for cls in model.mro():
                    if cls.__name__ in stoppage:
                        break
                    if cls.__name__ not in model_name_map:
                        model_name_map[cls.__name__] = cls

        # filter out enum objects
        if not include_enum:
            model_name_map = {
                k: v for k, v in model_name_map.items()
                if not isinstance(v, enum.EnumMeta)
            }

        # remove base type objects
        model_name_map = {
            k: v for k, v in model_name_map.items()
            if k not in ('str', 'int', 'dict')
        }

    assert len(model_name_map) > 0, 'Found no valid Pydantic model in input classes.'

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
            # Some schemas in V2 might be autogenerated and not in our mapper
            if name in mapper:
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
