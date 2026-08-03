from pathlib import Path

from pampapilot.knowledge_retrieval import retrieve_knowledge


def test_retrieval_selects_relevant_cited_knowledge(tmp_path: Path) -> None:
    (tmp_path / "mixing").mkdir()
    (tmp_path / "midi").mkdir()
    (tmp_path / "mixing" / "compressor.yaml").write_text(
        "id: mixing.compressor\ntitle: Compresión de percusión\nstage: mixing\n"
        "principles:\n  - conservar transitorios con ataque lento\n",
        encoding="utf-8",
    )
    (tmp_path / "midi" / "cleanup.yaml").write_text(
        "id: midi.cleanup\ntitle: Limpieza MIDI\nstage: editing\n",
        encoding="utf-8",
    )

    result = retrieve_knowledge(
        "ajustar ataque del compresor de percusión", knowledge_root=tmp_path
    )

    assert result["retrieval"] == "lexical-v1"
    assert result["items"][0]["knowledge_id"] == "mixing.compressor"
    assert result["items"][0]["source"] == "mixing/compressor.yaml"
    assert "Limpieza MIDI" not in result["items"][0]["excerpt"]
