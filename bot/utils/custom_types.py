from typing import TypedDict, Mapping


class StateDict(dict):
    def __init__(self, d_):
        self.changed = False
        super(StateDict, self).__init__(d_)

    def __setitem__(self, key, value):
        self.changed = True
        super().__setitem__(key, value)

    def update(self, __m, **kwargs) -> None:
        self.changed = True
        super(StateDict, self).update(__m, **kwargs)


class ConfigItemDict(TypedDict):
    name: str
    enabled: bool


class ConfigDict(TypedDict):
    cogs: Mapping[str, ConfigItemDict]
