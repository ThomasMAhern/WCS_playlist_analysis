"""Utility functions for dealing with Python generic types."""
from typing import get_args, get_origin
import types


def get_type_args_of_base(cls: type, base: type) -> tuple[type, ...]:
    for base_cls in types.get_original_bases(cls):
        if base_cls == base or (isinstance(base_cls, type) and issubclass(base_cls, base)):
            raise ValueError(f'Invalid: Non-parametrized occurence of {base} in bases of {cls}')
        origin = get_origin(base_cls)
        if origin == base or issubclass(origin, base):
            assert getattr(origin, '__type_params__', ()) != ()
            return get_args(base_cls)

    raise ValueError(f'Invalid: {base} is not an immediate base of {cls}')
