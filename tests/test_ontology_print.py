from dc_harness.cli import main


def test_ontology_command_prints_model(capsys):
    assert main(["ontology"]) == 0
    out = capsys.readouterr().out
    assert "Topic" in out and "Discusses" in out and "논의된 토픽이다" in out
