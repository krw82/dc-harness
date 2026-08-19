import pytest

from dc_harness.ontology.defn import (LinkDef, ObjectDef, OntologyDef,
                                      PropertyDef, load_ontology)
from dc_harness.ontology.validate import OntologyValidationError, collect_errors, validate


def obj(api_name="Topic", display="토픽", layer="derived", pk=("topicId",),
        props=("topicId", "label", "runId", "promptVersion"), table="obj_topics"):
    return ObjectDef(apiName=api_name, displayName=display, description="d",
                     pk=list(pk), layer=layer, table=table,
                     properties=[PropertyDef(p, "text", "d") for p in props])


def test_shipped_ontology_is_valid():
    assert collect_errors(load_ontology(None)) == []


def test_v1_naming_and_uniqueness():
    bad = obj(api_name="topic")  # PascalCase 아님
    bad.properties.append(PropertyDef("BadProp", "text", "d"))
    errors = collect_errors(OntologyDef(objects=[bad]))
    assert any("topic" in e for e in errors)          # 객체명 형식
    assert any("BadProp" in e for e in errors)        # 속성명 형식
    ok_pair = OntologyDef(objects=[obj(), obj(api_name="Theme", display="주제")])
    assert not any("duplicate" in e for e in collect_errors(ok_pair))  # apiName 다르면 OK


def test_v2_pk_must_exist():
    errors = collect_errors(OntologyDef(objects=[obj(pk=("nope",))]))
    assert any("pk" in e.lower() for e in errors)


def test_v3_link_endpoints_and_via():
    topic = obj()
    post = obj(api_name="Post", display="게시글", layer="raw", pk=("postNo",),
               props=("postNo",), table="posts")
    link_bad = LinkDef("PointsTo", "가리킨다", "d", "Post", "Ghost", "N:1")
    link_nm_no_via = LinkDef("Discusses", "논의", "d", "Post", "Topic", "N:M")
    errors = collect_errors(OntologyDef(objects=[post, topic],
                                        links=[link_bad, link_nm_no_via]))
    assert any("Ghost" in e for e in errors)
    assert any("via" in e for e in errors)


def test_v4_duplicate_concept():
    a = obj(api_name="Topic", display="토픽")
    b = obj(api_name="Subject", display="토픽")
    errors = collect_errors(OntologyDef(objects=[a, b]))
    assert any("duplicate" in e for e in errors)


def test_v5_derived_requires_provenance():
    missing = obj(props=("topicId", "label"))  # runId/promptVersion 없음
    errors = collect_errors(OntologyDef(objects=[missing]))
    assert any("runId" in e for e in errors)


def test_validate_raises_on_errors():
    with pytest.raises(OntologyValidationError):
        validate(OntologyDef(objects=[obj(props=("topicId",))]))
