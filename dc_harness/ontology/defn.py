from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ONTOLOGY_PATH = Path(__file__).parent / "ontology.toml"


@dataclass
class PropertyDef:
    apiName: str
    type: str
    description: str


@dataclass
class ObjectDef:
    apiName: str
    displayName: str
    description: str
    pk: list[str]
    layer: str
    table: str
    properties: list[PropertyDef] = field(default_factory=list)


@dataclass
class LinkDef:
    apiName: str
    displayName: str
    description: str
    fromObject: str
    toObject: str
    cardinality: str
    via: str = ""


@dataclass
class OntologyDef:
    objects: list[ObjectDef] = field(default_factory=list)
    links: list[LinkDef] = field(default_factory=list)

    def object_(self, api_name: str) -> ObjectDef | None:
        return next((o for o in self.objects if o.apiName == api_name), None)


def load_ontology(path: Path | None = None) -> OntologyDef:
    data = tomllib.loads((path or DEFAULT_ONTOLOGY_PATH).read_text(encoding="utf-8"))
    return OntologyDef(
        objects=[ObjectDef(
            apiName=o["apiName"], displayName=o["displayName"],
            description=o["description"], pk=list(o.get("pk", [])),
            layer=o.get("layer", "raw"), table=o.get("table", ""),
            properties=[PropertyDef(**p) for p in o.get("property", [])],
        ) for o in data.get("object", [])],
        links=[LinkDef(**link) for link in data.get("link", [])],
    )
