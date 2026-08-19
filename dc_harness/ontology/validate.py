from __future__ import annotations

import re

from .defn import OntologyDef

_PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_CAMEL = re.compile(r"^[a-z][A-Za-z0-9]*$")
_CARDINALITIES = {"1:1", "1:N", "N:1", "N:M"}


class OntologyValidationError(ValueError):
    pass


def collect_errors(defn: OntologyDef) -> list[str]:
    errors: list[str] = []
    seen_names: set[str] = set()
    seen_concepts: dict[str, str] = {}

    for o in defn.objects:
        if not _PASCAL.match(o.apiName):
            errors.append(f"V1 object apiName must be PascalCase: {o.apiName}")
        if o.apiName in seen_names:
            errors.append(f"V1 duplicate object apiName: {o.apiName}")
        seen_names.add(o.apiName)
        concept = re.sub(r"\s+", "", o.displayName).casefold()
        if concept and concept in seen_concepts:
            errors.append(f"V4 duplicate concept: {o.apiName} ~ {seen_concepts[concept]} "
                          f"(displayName={o.displayName})")
        seen_concepts[concept] = o.apiName

        prop_names = {p.apiName for p in o.properties}
        for p in o.properties:
            if not _CAMEL.match(p.apiName):
                errors.append(f"V1 property apiName must be camelCase: {o.apiName}.{p.apiName}")
        if not o.pk:
            errors.append(f"V2 object has empty pk: {o.apiName}")
        for key in o.pk:
            if key not in prop_names:
                errors.append(f"V2 pk property missing on {o.apiName}: {key}")
        if o.layer == "derived":
            for required in ("runId", "promptVersion"):
                if required not in prop_names:
                    errors.append(f"V5 derived object {o.apiName} lacks provenance "
                                  f"property: {required}")

    for l in defn.links:
        if not _PASCAL.match(l.apiName):
            errors.append(f"V1 link apiName must be PascalCase: {l.apiName}")
        if l.cardinality not in _CARDINALITIES:
            errors.append(f"V6 invalid cardinality on {l.apiName}: {l.cardinality}")
        for end in (l.fromObject, l.toObject):
            if end not in seen_names:
                errors.append(f"V3 link {l.apiName} references unknown object: {end}")
        if l.cardinality == "N:M" and not l.via:
            errors.append(f"V3 N:M link {l.apiName} must declare via (junction table)")
        if l.cardinality != "N:M" and l.via:
            errors.append(f"V3 via is only allowed for N:M link: {l.apiName}")
    return errors


def validate(defn: OntologyDef) -> None:
    errors = collect_errors(defn)
    if errors:
        raise OntologyValidationError("invalid ontology:\n- " + "\n- ".join(errors))
