from typing import List, TypedDict, Optional


class Node(TypedDict):
    name: str
    id: str


class EdgesItems(TypedDict):
    node: Node


class Labels(TypedDict):
    totalCount: int
    edges: List[EdgesItems]


class Repository(TypedDict):
    id: str
    labels: Labels


class Data(TypedDict):
    repository: Repository


class LocationsItems(TypedDict):
    line: int
    column: int


class ErrorsItems(TypedDict):
    type: str
    path: List[str]
    locations: List[LocationsItems]
    message: str


class Root(TypedDict):
    data: Data
    errors: Optional[List[ErrorsItems]]
