"""Retrieval layer against a local embedded Qdrant in a temporary directory."""

import json
import os

import pytest

import automatron_core as core


@pytest.fixture(scope="module")
def rag_env(tmp_path_factory):
    """Point the whole layer at a throwaway directory, then release the file lock."""
    runtime = tmp_path_factory.mktemp("runtime")
    previous = os.environ.get("RUNTIME_DIR")
    os.environ["RUNTIME_DIR"] = str(runtime)
    core.reset_settings_cache()
    core.reset_rag_cache()

    yield runtime

    try:
        core.get_qdrant().close()
    except Exception:
        pass
    core.reset_rag_cache()
    if previous is None:
        os.environ.pop("RUNTIME_DIR", None)
    else:
        os.environ["RUNTIME_DIR"] = previous
    core.reset_settings_cache()


@pytest.fixture(scope="module")
def seeded(rag_env, tmp_path_factory):
    """A tiny knowledge tree, seeded once for the search tests to read."""
    knowledge = tmp_path_factory.mktemp("data") / "knowledge"
    for sector, name, body in [
        (
            "space",
            "pc_basics.md",
            "Probability of collision is integrated over the hard-body circle in the encounter "
            "plane. Operators often treat 1e-4 as a review threshold.",
        ),
        (
            "space",
            "debris.md",
            "Post-mission disposal removes a spacecraft from low Earth orbit within a defined "
            "period after the end of its mission.",
        ),
        (
            "quant",
            "dsr.md",
            "The deflated Sharpe ratio adjusts an observed Sharpe ratio for the number of trials "
            "attempted during the search.",
        ),
    ]:
        folder = knowledge / sector
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(
            f"---\ntitle: {name.removesuffix('.md')}\nsource_url: https://example.invalid/{name}\n"
            f"doc_type: reference\n---\n\n{body}\n",
            encoding="utf-8",
        )
    (knowledge / "space" / "cases").mkdir(parents=True, exist_ok=True)
    (knowledge / "space" / "cases" / "case_spike.md").write_text(
        "---\ntitle: Pc spike case\n---\n\nA Pc spike was traced to a stale covariance and no "
        "manoeuvre was performed.\n",
        encoding="utf-8",
    )

    previous = os.environ.get("DATA_DIR")
    os.environ["DATA_DIR"] = str(knowledge.parent)
    core.reset_settings_cache()
    first = core.seed_knowledge()
    yield first
    if previous is None:
        os.environ.pop("DATA_DIR", None)
    else:
        os.environ["DATA_DIR"] = previous
    core.reset_settings_cache()


class TestHelpers:
    def test_point_ids_are_deterministic(self):
        assert core.node_id("abc", 3, "public") == core.node_id("abc", 3, "public")

    def test_point_ids_separate_tenants_and_chunks(self):
        base = core.node_id("abc", 0, "public")
        assert core.node_id("abc", 0, "run-1") != base
        assert core.node_id("abc", 1, "public") != base

    def test_clean_text_removes_control_characters(self):
        assert core.clean_text("a\x00b\x07c") == "a b c"

    def test_front_matter_is_split_off(self):
        meta, body = core.split_front_matter("---\ntitle: T\ndoc_type: policy\n---\n\nBody here.\n")
        assert meta == {"title": "T", "doc_type": "policy"}
        assert body.strip() == "Body here."

    def test_missing_front_matter_is_fine(self):
        meta, body = core.split_front_matter("Just a body.")
        assert meta == {}
        assert body == "Just a body."

    def test_malformed_front_matter_does_not_raise(self):
        meta, _ = core.split_front_matter("---\n: : :\n bad\n---\nbody")
        assert isinstance(meta, dict)

    def test_untrusted_wrapper_names_its_source(self):
        wrapped = core.wrap_untrusted("text", "upload:lease.pdf")
        assert wrapped.startswith('<untrusted_data source="upload:lease.pdf">')
        assert wrapped.endswith("</untrusted_data>")


class TestLoaders:
    def test_markdown_front_matter_becomes_metadata(self, tmp_path):
        path = tmp_path / "doc.md"
        path.write_text(
            "---\ntitle: Zoning\nsource_url: https://example.invalid\n---\n\nR-1 rules.\n"
        )
        documents = core.load_documents(path, {"sector": "realestate"})
        assert len(documents) == 1
        assert documents[0].metadata["title"] == "Zoning"
        assert documents[0].metadata["sector"] == "realestate"
        assert "R-1 rules." in documents[0].text

    def test_csv_preview_includes_a_shape_summary(self, tmp_path):
        path = tmp_path / "orders.csv"
        path.write_text("order_id,value\n1,10\n2,20\n")
        text = core.load_documents(path, {})[0].text
        assert "Columns: order_id, value" in text
        assert "Rows shown: 2" in text

    def test_json_preview_lists_keys(self, tmp_path):
        path = tmp_path / "ticket.json"
        path.write_text(json.dumps([{"ticket_id": "T1", "side": "buy"}]))
        text = core.load_documents(path, {})[0].text
        assert "Keys: side, ticket_id" in text

    def test_unsupported_suffix_is_refused(self, tmp_path):
        path = tmp_path / "thing.xyz"
        path.write_text("data")
        with pytest.raises(ValueError, match="no reader"):
            core.load_documents(path, {})

    def test_empty_file_yields_no_documents(self, tmp_path):
        path = tmp_path / "empty.md"
        path.write_text("")
        assert core.load_documents(path, {}) == []


class TestSeeding:
    def test_seeding_indexes_every_sector_present(self, seeded):
        assert seeded.get("space", 0) > 0
        assert seeded.get("quant", 0) > 0

    def test_second_seed_adds_nothing(self, seeded):
        assert core.seed_knowledge() == {}, "a repeat seed must not duplicate work"

    def test_forced_reseed_reindexes(self, seeded):
        again = core.seed_knowledge(force=True)
        assert again.get("space", 0) > 0


class TestSearch:
    def test_finds_a_relevant_passage(self, seeded):
        found = core.search_knowledge(
            "what threshold do operators use for collision probability?", sector="space"
        )
        assert found["warning"] == ""
        assert found["results"], "expected at least one passage"
        assert "1e-4" in " ".join(hit["text"] for hit in found["results"])

    def test_results_carry_citable_ids_and_metadata(self, seeded):
        hits = core.search_knowledge("post-mission disposal", sector="space")["results"]
        assert hits[0]["id"] == "S1"
        assert hits[0]["source_url"].startswith("https://example.invalid/")
        assert set(hits[0]) >= {"id", "title", "doc_type", "score", "text"}

    def test_a_sector_never_sees_another_sectors_documents(self, seeded):
        hits = core.search_knowledge("deflated Sharpe ratio trials", sector="space")["results"]
        assert not any("Sharpe" in hit["text"] for hit in hits)

    def test_the_other_sector_does_find_it(self, seeded):
        hits = core.search_knowledge("deflated Sharpe ratio trials", sector="quant")["results"]
        assert any("Sharpe" in hit["text"] for hit in hits)

    def test_cases_are_excluded_unless_asked_for(self, seeded):
        without = core.search_knowledge("stale covariance spike", sector="space")["results"]
        assert not any(hit["doc_type"] == "case" for hit in without)
        with_cases = core.search_knowledge(
            "stale covariance spike", sector="space", include_cases=True
        )["results"]
        assert any(hit["doc_type"] == "case" for hit in with_cases)

    def test_result_count_is_capped(self, seeded):
        hits = core.search_knowledge("orbit", sector="space", k=99)["results"]
        assert len(hits) <= core.MAX_SEARCH_RESULTS

    def test_snippets_are_truncated(self, seeded):
        for hit in core.search_knowledge("collision", sector="space")["results"]:
            assert len(hit["text"]) <= core.SNIPPET_CHARS

    def test_unreachable_backend_warns_instead_of_raising(self, seeded, monkeypatch):
        def explode(*args, **kwargs):
            raise RuntimeError("qdrant is gone")

        monkeypatch.setattr(core, "get_index", explode)
        found = core.search_knowledge("anything", sector="space")
        assert found["results"] == []
        assert "unavailable" in found["warning"]


class TestSessionUploads:
    def test_an_upload_is_visible_only_to_its_own_run(self, seeded, tmp_path):
        upload = tmp_path / "notes.md"
        upload.write_text("The tenant reported a broken boiler on 3 March.")
        core.ingest_upload(upload, run_id="run-a", sector="realestate")

        mine = core.search_knowledge("broken boiler", sector="realestate", run_id="run-a")
        assert any("boiler" in hit["text"] for hit in mine["results"])

        theirs = core.search_knowledge("broken boiler", sector="realestate", run_id="run-b")
        assert not any("boiler" in hit["text"] for hit in theirs["results"])

        public_only = core.search_knowledge("broken boiler", sector="realestate")
        assert not any("boiler" in hit["text"] for hit in public_only["results"])

    def test_cleanup_leaves_public_knowledge_alone(self, seeded, tmp_path):
        upload = tmp_path / "temp.md"
        upload.write_text("Ephemeral session content about a disputed fence.")
        core.ingest_upload(upload, run_id="run-old", sector="realestate")

        # Everything older than zero hours, which is everything.
        core.cleanup_sessions(older_than_hours=0)

        gone = core.search_knowledge("disputed fence", sector="realestate", run_id="run-old")
        assert not any("Ephemeral" in hit["text"] for hit in gone["results"])
        assert core.search_knowledge("collision probability", sector="space")["results"]


class TestBundledKnowledge:
    """The committed knowledge files, checked without embedding them."""

    def files(self):
        root = core.ROOT / "data" / "knowledge"
        return sorted(root.rglob("*.md"))

    def test_every_sector_ships_knowledge(self):
        root = core.ROOT / "data" / "knowledge"
        for sector in core.SECTOR_ORDER:
            assert list((root / sector).glob("*.md")), f"{sector} has no knowledge files"
            assert list((root / sector / "cases").glob("*.md")), f"{sector} has no cases"

    def test_front_matter_parses_and_is_labelled(self):
        for path in self.files():
            meta, body = core.split_front_matter(path.read_text(encoding="utf-8"))
            assert meta.get("title"), f"{path.name} has no title"
            assert meta.get("license_note"), f"{path.name} has no licence note"
            assert body.strip(), f"{path.name} has no body"

    def test_synthetic_material_says_so(self):
        for path in self.files():
            meta, _ = core.split_front_matter(path.read_text(encoding="utf-8"))
            note = meta["license_note"].lower()
            assert "synthetic" in note or "authored summary" in note, path.name

    def test_knowledge_stays_small(self):
        total = sum(path.stat().st_size for path in self.files())
        assert total < 3_000_000, "knowledge base should stay under 3 MB of text"


class TestCloudFallback:
    """A free Space loses its disk on restart, so the cloud cluster matters; an
    unreachable one must degrade rather than take the app down."""

    def test_an_unreachable_cluster_falls_back_to_local_storage(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
        monkeypatch.setenv("QDRANT_URL", "https://nonexistent-cluster.invalid:6333")
        monkeypatch.setenv("QDRANT_API_KEY", "not-a-real-key")
        core.reset_settings_cache()
        core.reset_rag_cache()
        try:
            assert core.get_settings().qdrant_url, "the test needs a cloud url configured"
            client = core.get_qdrant()
            assert core.is_local_qdrant(client), "an unreachable cluster should fall back"
        finally:
            try:
                core.get_qdrant().close()
            except Exception:
                pass
            core.reset_rag_cache()
            core.reset_settings_cache()

    def test_no_cloud_url_uses_local_storage_without_trying(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
        monkeypatch.delenv("QDRANT_URL", raising=False)
        core.reset_settings_cache()
        core.reset_rag_cache()
        try:
            assert core.is_local_qdrant(core.get_qdrant())
        finally:
            try:
                core.get_qdrant().close()
            except Exception:
                pass
            core.reset_rag_cache()
            core.reset_settings_cache()
