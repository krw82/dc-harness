from dc_harness.ontology.defn import load_ontology


def test_load_default_ontology():
    defn = load_ontology(None)
    names = {o.apiName for o in defn.objects}
    assert names == {"Gallery", "Post", "Comment", "Author",
                     "Topic", "Entity", "Issue", "Voice"}
    post = defn.object_("Post")
    assert post.layer == "raw" and post.table == "posts"
    assert post.pk == ["galleryId", "postNo"]
    assert {p.apiName for p in post.properties} >= {"postNo", "title", "recommendCount"}


def test_links_and_cardinality():
    defn = load_ontology(None)
    link_names = {l.apiName for l in defn.links}
    assert link_names == {"WrittenOn", "BelongsTo", "AuthoredBy",
                          "Discusses", "Evidences"}
    discusses = next(l for l in defn.links if l.apiName == "Discusses")
    assert discusses.cardinality == "N:M" and discusses.via == "obj_post_topics"


def test_object_lookup_missing_returns_none():
    assert load_ontology(None).object_("Nope") is None
