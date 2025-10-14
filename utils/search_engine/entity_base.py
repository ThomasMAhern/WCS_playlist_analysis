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
