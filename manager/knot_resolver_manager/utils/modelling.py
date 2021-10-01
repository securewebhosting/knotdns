import inspect
from typing import Any, Dict, Optional, Set, Tuple, Type, Union

from knot_resolver_manager.exceptions import DataException, SchemaException
from knot_resolver_manager.utils.custom_types import CustomValueType
from knot_resolver_manager.utils.parsing import ParsedTree
from knot_resolver_manager.utils.types import (
    NoneType,
    get_generic_type_argument,
    get_generic_type_arguments,
    is_dict,
    is_enum,
    is_internal_field_name,
    is_list,
    is_literal,
    is_none_type,
    is_optional,
    is_tuple,
    is_union,
)


def is_obj_type(obj: Any, types: Union[type, Tuple[Any, ...], Tuple[type, ...]]) -> bool:
    # To check specific type we are using 'type()' instead of 'isinstance()'
    # because for example 'bool' is instance of 'int', 'isinstance(False, int)' returns True.
    # pylint: disable=unidiomatic-typecheck
    if isinstance(types, Tuple):
        return type(obj) in types
    return type(obj) == types


def _validated_object_type(
    cls: Type[Any], obj: Any, default: Any = ..., use_default: bool = False, object_path: str = "/"
) -> Any:
    """
    Given an expected type `cls` and a value object `obj`, validate the type of `obj` and return it
    """

    # Disabling these checks, because I think it's much more readable as a single function
    # and it's not that large at this point. If it got larger, then we should definitely split it
    # pylint: disable=too-many-branches,too-many-locals,too-many-statements

    # default values
    if obj is None and use_default:
        return default

    # NoneType
    elif is_none_type(cls):
        if obj is None:
            return None
        else:
            raise SchemaException(f"Expected None, found '{obj}'.", object_path)

    # Union[*variants] (handles Optional[T] due to the way the typing system works)
    elif is_union(cls):
        variants = get_generic_type_arguments(cls)
        for v in variants:
            try:
                return _validated_object_type(v, obj, object_path=object_path)
            except SchemaException:
                pass
        raise SchemaException(f"Union {cls} could not be parsed - parsing of all variants failed.", object_path)

    # after this, there is no place for a None object
    elif obj is None:
        raise SchemaException(f"Unexpected value 'None' for type {cls}", object_path)

    # int
    elif cls == int:
        # we don't want to make an int out of anything else than other int
        # except for CustomValueType class instances
        if is_obj_type(obj, int) or isinstance(obj, CustomValueType):
            return int(obj)
        raise SchemaException(f"Expected int, found {type(obj)}", object_path)

    # str
    elif cls == str:
        # we are willing to cast any primitive value to string, but no compound values are allowed
        if is_obj_type(obj, (str, float, int)) or isinstance(obj, CustomValueType):
            return str(obj)
        elif is_obj_type(obj, bool):
            raise SchemaException(
                "Expected str, found bool. Be careful, that YAML parsers consider even"
                ' "no" and "yes" as a bool. Search for the Norway Problem for more'
                " details. And please use quotes explicitly.",
                object_path,
            )
        else:
            raise SchemaException(
                f"Expected str (or number that would be cast to string), but found type {type(obj)}", object_path
            )

    # bool
    elif cls == bool:
        if is_obj_type(obj, bool):
            return obj
        else:
            raise SchemaException(f"Expected bool, found {type(obj)}", object_path)

    # float
    elif cls == float:
        raise NotImplementedError(
            "Floating point values are not supported in the parser."
            " Please implement them and be careful with type coercions"
        )

    # Literal[T]
    elif is_literal(cls):
        expected = get_generic_type_argument(cls)
        if obj == expected:
            return obj
        else:
            raise SchemaException(f"Literal {cls} is not matched with the value {obj}", object_path)

    # Dict[K,V]
    elif is_dict(cls):
        key_type, val_type = get_generic_type_arguments(cls)
        try:
            return {
                _validated_object_type(key_type, key, object_path=f"{object_path} @ key {key}"): _validated_object_type(
                    val_type, val, object_path=f"{object_path} @ value for key {key}"
                )
                for key, val in obj.items()
            }
        except AttributeError as e:
            raise SchemaException(
                f"Expected dict-like object, but failed to access its .items() method. Value was {obj}", object_path
            ) from e

    # any Enums (probably used only internally in DataValidator)
    elif is_enum(cls):
        if isinstance(obj, cls):
            return obj
        else:
            raise SchemaException(f"Unexpected value '{obj}' for enum '{cls}'", object_path)

    # List[T]
    elif is_list(cls):
        inner_type = get_generic_type_argument(cls)
        return [_validated_object_type(inner_type, val, object_path=f"{object_path}[]") for val in obj]

    # Tuple[A,B,C,D,...]
    elif is_tuple(cls):
        types = get_generic_type_arguments(cls)
        return tuple(_validated_object_type(typ, val, object_path=object_path) for typ, val in zip(types, obj))

    # type of obj and cls type match
    elif is_obj_type(obj, cls):
        return obj

    # CustomValueType subclasses
    elif inspect.isclass(cls) and issubclass(cls, CustomValueType):
        if isinstance(obj, cls):
            # if we already have a custom value type, just pass it through
            return obj
        else:
            # no validation performed, the implementation does it in the constuctor
            return cls(obj, object_path=object_path)

    # nested SchemaNode subclasses
    elif inspect.isclass(cls) and issubclass(cls, SchemaNode):
        # we should return DataParser, we expect to be given a dict,
        # because we can construct a DataParser from it
        if isinstance(obj, (dict, SchemaNode)):
            return cls(obj, object_path=object_path)  # type: ignore
        raise SchemaException(f"Expected 'dict' or 'SchemaNode' object, found '{type(obj)}'", object_path)

    # if the object matches, just pass it through
    elif inspect.isclass(cls) and isinstance(obj, cls):
        return obj

    # default error handler
    else:
        raise SchemaException(
            f"Type {cls} cannot be parsed. This is a implementation error. "
            "Please fix your types in the class or improve the parser/validator.",
            object_path,
        )


TSource = Union[NoneType, ParsedTree, "SchemaNode", Dict[str, Any]]


def _create_untouchable(name: str):
    class _Untouchable:
        def __getattribute__(self, item_name: str) -> Any:
            raise RuntimeError(f"You are not supposed to access object '{name}'.")

        def __setattr__(self, item_name: str, value: Any) -> None:
            raise RuntimeError(f"You are not supposed to access object '{name}'.")

    return _Untouchable()


class SchemaNode:
    """
    Class for modelling configuration schema. It somewhat resembles standard dataclasses with additional
    functionality:

    * type validation
    * data conversion

    To create an instance of this class, you have to provide source data in the form of dict-like object.
    Generally, we expect `ParsedTree`, raw dict or another `SchemaNode` instance. The provided data object
    is traversed, transformed and validated before assigned to the appropriate fields.

    Fields (attributes)
    ===================

    The fields (or attributes) of the class are defined the same way as in a dataclass by creating a class-level
    type-annotated fields. An example of that is:

    class A(SchemaNode):
        awesome_number: int

    If your `SchemaNode` instance has a field with type of a SchemaNode, its value is recursively created
    from the nested input data. This way, you can specify a complex tree of SchemaNode's and use the root
    SchemaNode to create instance of everything.

    Transformation
    ==============

    You can provide the SchemaNode class with a field and a function with the same name, but starting with
    underscore ('_'). For example, you could have field called `awesome_number` and function called
    `_awesome_number(self, source)`. The function takes one argument - the source data (optionally with self,
    but you are not supposed to touch that). It can read any data from the source object and return a value of
    an appropriate type, which will be assigned to the field `awesome_number`. If you want to report an error
    during validation, raise a `ValueError` exception.

    Using this, you can convert any input values into any type and field you want. To make the conversion easier
    to write, you could also specify a special class variable called `_PREVIOUS_SCHEMA` pointing to another
    SchemaNode class. This causes the source object to be first parsed as the specified SchemaNode and after that
    used a source for this class. This therefore allows nesting of transformation functions.

    Validation
    ==========

    All assignments to fields during object construction are checked at runtime for proper types. This means,
    you are free to use an untrusted source object and turn it into a data structure, where you are sure what
    is what.

    You can also define a `_validate` method, which will be called once the whole data structure is built. You
    can validate the data in there and raise a `ValueError`, if they are invalid.

    Default values
    ==============

    If you create a field with a value, it will be used as a default value whenever the data in source object
    are not present. As a special case, default value for Optional type is None if not specified otherwise. You
    are not allowed to have a field with a default value and a transformation function at once.

    Example
    =======

    See tests/utils/test_modelling.py for example usage.
    """

    _PREVIOUS_SCHEMA: Optional[Type["SchemaNode"]] = None

    def _assign_default(self, name: str, python_type: Any, object_path: str):
        cls = self.__class__
        default = getattr(cls, name, None)
        value = _validated_object_type(python_type, default, object_path=f"{object_path}/{name}")
        setattr(self, name, value)

    def _assign_field(self, name: str, python_type: Any, value: Any, object_path: str):
        value = _validated_object_type(python_type, value, object_path=f"{object_path}/{name}")
        setattr(self, name, value)

    def _assign_fields(self, source: Union[ParsedTree, "SchemaNode", NoneType], object_path: str) -> Set[str]:
        """
        Order of assignment:
          1. all direct assignments
          2. assignments with conversion method
        """
        cls = self.__class__
        annot = cls.__dict__.get("__annotations__", {})

        used_keys: Set[str] = set()
        for name, python_type in annot.items():
            if is_internal_field_name(name):
                continue

            # populate field
            if source is None:
                self._assign_default(name, python_type, object_path)

            # check for invalid configuration with both transformation function and default value
            elif hasattr(self, f"_{name}") and hasattr(self, name):
                raise RuntimeError(
                    f"Field '{self.__class__.__name__}.{name}' has default value and transformation function at"
                    " the same time. That is now allowed. Store the default in the transformation function."
                )

            # there is a transformation function to create the value
            elif hasattr(self, f"_{name}"):
                val = self._get_converted_value(name, source, object_path)
                self._assign_field(name, python_type, val, object_path)
                used_keys.add(name)

            # source just contains the value
            elif name in source:
                val = source[name]
                self._assign_field(name, python_type, val, object_path)
                used_keys.add(name)

            # there is a default value, or the type is optional => store the default or null
            elif hasattr(self, name) or is_optional(python_type):
                self._assign_default(name, python_type, object_path)

            # we expected a value but it was not there
            else:
                raise SchemaException(f"Missing attribute '{name}'.", object_path)

        return used_keys

    def __init__(self, source: TSource = None, object_path: str = ""):
        # make sure that all raw data checks passed on the source object
        if source is None:
            source = ParsedTree({})
        if isinstance(source, dict):
            source = ParsedTree(source)

        # save source
        self._source: Union[ParsedTree, SchemaNode] = source

        # construct lower level schema node first if configured to do so
        if self._PREVIOUS_SCHEMA is not None:
            source = self._PREVIOUS_SCHEMA(source, object_path=object_path)  # pylint: disable=not-callable

        # assign fields
        used_keys = self._assign_fields(source, object_path)

        # check for unused keys in the source object
        if source and not isinstance(source, SchemaNode):
            unused = source.keys() - used_keys
            if len(unused) > 0:
                raise SchemaException(
                    f"Keys {unused} in your configuration object are not part of the configuration schema."
                    " Are you using '-' instead of '_'?",
                    object_path,
                )

        # validate the constructed value
        try:
            self._validate()
        except ValueError as e:
            raise SchemaException(e.args[0] if len(e.args) > 0 else "Validation error", object_path) from e

    def get_unparsed_data(self) -> ParsedTree:
        if isinstance(self._source, SchemaNode):
            return self._source.get_unparsed_data()
        else:
            return self._source

    def _get_converted_value(self, key: str, source: TSource, object_path: str) -> Any:
        """
        Get a value of a field by invoking appropriate transformation function.
        """
        try:
            func = getattr(self.__class__, f"_{key}")
            argc = len(inspect.signature(func).parameters)
            if argc == 1:
                # it is a static method
                return func(source)
            elif argc == 2:
                # it is a instance method
                return func(_create_untouchable("self"), source)
            else:
                raise RuntimeError("Transformation function has wrong number of arguments")
        except (ValueError, DataException) as e:
            if len(e.args) > 0 and isinstance(e.args[0], str):
                msg = e.args[0]
            else:
                msg = "Failed to validate value type"
            raise SchemaException(msg, object_path) from e

    def __getitem__(self, key: str) -> Any:
        if not hasattr(self, key):
            raise RuntimeError(f"Object '{self}' of type '{type(self)}' does not have field named '{key}'")
        return getattr(self, key)

    def __contains__(self, item: Any) -> bool:
        return hasattr(self, item)

    def _validate(self) -> None:
        """
        Validation procedure called after all field are assigned. Should throw a ValueError in case of failure.
        """
