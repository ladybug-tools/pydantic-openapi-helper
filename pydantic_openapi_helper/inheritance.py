import enum
import warnings
import inspect
from typing import Set, Type
from typing import get_args, get_origin

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

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
    model_list = list(model_name_map.values())

    # generate schema.
    _, schemas = models_json_schema(
        [(m, 'serialization') for m in model_list], 
        ref_template='#/components/schemas/{model}'
    )

    if '$defs' in schemas:
        defs = schemas.pop('$defs')
        for k, v in defs.items():
            if k not in schemas:
                schemas[k] = v

    # add the [possibly] needed baseclass to the list of classes
    schemas['_OpenAPIGenBaseModel'] = _OpenAPIGenBaseModel.model_json_schema()
    model_name_map['_OpenAPIGenBaseModel'] = _OpenAPIGenBaseModel

    # an empty dictionary to collect updated objects
    updated_schemas = {}

    # iterate through all the data models
    # find the ones which are subclassed and updated them based on the properties of
    # baseclasses.
    for name, model_schema in list(schemas.items()):
        # find the class object from class name
        try:
            main_cls = model_name_map[name]
        except KeyError:
            if 'enum' in model_schema:
                continue

            warnings.warn(f'***KeyError: {name} key not found in model map.***')

            if name != '_OpenAPIGenBaseModel' and isinstance(model_schema, dict):
                updated_schemas[name] = inherit_fom_basemodel(model_schema)
            continue

        top_classes = get_ancestors(main_cls)

        if not top_classes:
            if name != '_OpenAPIGenBaseModel':
                updated_schemas[name] = inherit_fom_basemodel(model_schema)
            continue

        updated_schemas[name] = set_inheritance(name, top_classes, schemas)

    # replace updated schemas in original schema
    for name, value in updated_schemas.items():
        schemas[name] = value

    return schemas


def get_ancestors(cls):
    """Use type.mro to go through all the ancestors for this class and collect them."""
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


def _extract_type_from_schema(prop_schema):
    """Helper to extract a type from a schema dict, handling anyOf/oneOf."""
    if 'type' in prop_schema:
        if prop_schema['type'] == 'array':
            return 'array', prop_schema.get('items')
        return prop_schema['type']

    # handle Optional/Union types (anyOf/oneOf)
    # we look for a non-null type inside
    candidates = prop_schema.get('anyOf') or prop_schema.get('oneOf')
    if candidates:
        for c in candidates:
            if c.get('type') != 'null':
                # recursive call in case nested (though usually flat)
                return _extract_type_from_schema(c)

    return '###'  # unknown or complex type


def _check_object_types(source, target, prop):
    """Check if objects with same name have different types."""

    source_type = _extract_type_from_schema(source)

    # if target doesn't have the prop, we can't conflict
    if prop not in target:
        return True

    target_type = target[prop]

    # if types are identical, no conflict
    if source_type == target_type:
        return False

    # if one is ### (complex) and the other isn't, we assume they might be different
    # but usually if we can't determine type, we assume it's complex and let Pydantic handle it
    if source_type == '###' or target_type == '###':
        return True

    return True


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
        t_name = t.__name__
        if t_name not in schemas:
            continue

        schema_t = schemas[t_name]

        tc_required = schema_t.get('required', [])
        for r in tc_required:
            if r not in top_classes_required:
                top_classes_required.append(r)

        tc_prop = schema_t.get('properties', {})
        for pn, dt in tc_prop.items():
            # use helper function to resolve types including Optional/Union
            top_classes_prop[pn] = _extract_type_from_schema(dt)
            print(f"Parent class {t_name} has property: {pn} with type: {top_classes_prop[pn]}")

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

    # handle Required Fields
    current_required = object_dict.get('required', [])
    new_required = []

    if not top_classes_required and current_required:
        new_required = current_required
    elif current_required and top_classes_required:
        # only add the new required fields
        for r in current_required:
            if r not in top_classes_required:
                new_required.append(r)

    if new_required:
        data_copy['allOf'][1]['required'] = new_required

    # get full list of the properties and add the ones that doesn't exist in
    # ancestor objects.
    properties = object_dict.get('properties', {})
    for prop, values in properties.items():
        if prop not in top_classes_prop:
            # new field. add it to the properties
            print(f'Extending: {prop}')
            data_copy['allOf'][1]['properties'][prop] = values
        elif _check_object_types(values, top_classes_prop, prop):
            # same name different types
            print(f'Found a field with the same name and different type: {prop}.')
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


def _collect_models_recursive(model: Type[BaseModel], found: Set[Type[BaseModel]]):
    """Recursively find all nested Pydantic models in fields."""
    if model in found or not hasattr(model, 'model_fields'):
        return

    found.add(model)

    for field in model.model_fields.values():
        annotation = field.annotation
        _extract_models_from_type(annotation, found)


def _extract_models_from_type(type_, found: Set[Type[BaseModel]]):
    """Helper to unwrap types and find Pydantic models."""
    if inspect.isclass(type_) and issubclass(type_, BaseModel):
        _collect_models_recursive(type_, found)
        return

    origin = get_origin(type_)
    args = get_args(type_)

    if origin is not None:
        for arg in args:
            _extract_models_from_type(arg, found)


def get_model_mapper(models, stoppage=None, full=True, include_enum=False):
    """Get a dictionary of name: class for all the objects in model."""
    if not isinstance(models, (list, tuple)):
        models = [models]

    flat_models_set = set()

    for model in models:
        if inspect.isclass(model) and issubclass(model, BaseModel):
            _collect_models_recursive(model, flat_models_set)
        elif isinstance(model, enum.EnumMeta):
            if include_enum:
                flat_models_set.add(model)

    model_name_map = {m.__name__: m for m in flat_models_set}

    if full:
        stoppage = stoppage or STOPPAGE

        # collect ancestors
        current_models = list(model_name_map.values())
        for model in current_models:
            if not inspect.isclass(model): continue

            for cls in inspect.getmro(model):
                if cls.__name__ in stoppage:
                    break
                if cls.__name__ not in model_name_map:
                    if issubclass(cls, BaseModel) or isinstance(cls, enum.EnumMeta):
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

    for name, s in schemas.items():
        if 'enum' in s and name in mapper:
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

    module_mapper['classes'] = {k: classes[k] for k in sorted(classes)}
    module_mapper['enums'] = {k: enums[k] for k in sorted(enums)}

    return module_mapper
