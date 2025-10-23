from typing import LiteralString#

import polars as pl
import polars.selectors as cs

from utils.typing import get_type_args_of_base


class Entity:
    @classmethod
    def matching_columns(cls) -> cs.Selector:
        return cs.starts_with(getattr(cls, 'PREFIX'))


class SubEntity[Child: Entity]:
    entity_type: type[Child]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.entity_type = get_type_args_of_base(cls, SubEntity)[0]


type PolarsLazyFrame[T: Entity] = pl.LazyFrame


class Field[FieldName: LiteralString, FieldType: pl.DataType](str):
    @property
    def field_name(self) -> str:
        return self

    @property
    def field_type(self) -> pl.DataType | type[pl.DataType]:
        return self._field_type

    def __new__(cls, field_name: FieldName, field_type: FieldType | type[FieldType] | None = None):
        field = str.__new__(cls, field_name)
        if field_type is not None:
            field._field_type = field_type
        return field

    def alias[NewName: LiteralString](self, new_name: NewName) -> 'Field[NewName, FieldType]':
        return Field(new_name, self.field_type)

    def cast[NewType: pl.DataType](self, new_type: NewType | type[NewType]) -> 'Field[FieldName, NewType]':
        return Field(self.field_name, new_type)


def field[FieldName: LiteralString, FieldType: pl.DataType](
    field_name: FieldName,
    field_type: FieldType | type[FieldType] | None = None,
) -> Field[FieldName, FieldType]:
    return Field(field_name, field_type)
