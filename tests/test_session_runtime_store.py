def test_session_runtime_store_persists_discussion_lifecycle(tmp_path):
    from agentmind.services.session_runtime_store import SessionRuntimeStore

    db_path = tmp_path / "runtime.db"
    store = SessionRuntimeStore(db_path)

    store.upsert_discussion("u1", stop=False)
    assert store.list_discussions() == {"u1": {"stop": False}}

    store.upsert_discussion("u1", stop=True)
    assert store.list_discussions() == {"u1": {"stop": True}}

    store.delete_discussion("u1")
    assert store.list_discussions() == {}


def test_session_runtime_store_initializes_schema_for_new_database(tmp_path):
    from agentmind.services.session_runtime_store import SessionRuntimeStore

    db_path = tmp_path / "nested" / "runtime.db"
    store = SessionRuntimeStore(db_path)

    assert store.list_discussions() == {}
    assert db_path.exists()


def test_default_session_runtime_store_uses_current_data_dir(monkeypatch, tmp_path):
    import agentmind.storage.db as storage_db
    from agentmind.services.session_runtime_store import SessionRuntimeStore

    store = SessionRuntimeStore()
    monkeypatch.setattr(storage_db, "DATA_DIR", tmp_path / "data")

    store.upsert_discussion("u1", stop=False)

    assert (tmp_path / "data" / "runtime_state.db").exists()

    store.upsert_attach_binding("s1", "t1")
    assert store.list_attach_bindings() == {"s1": "t1"}


def test_session_runtime_store_persists_attach_bindings(tmp_path):
    from agentmind.services.session_runtime_store import SessionRuntimeStore

    store = SessionRuntimeStore(tmp_path / "runtime.db")

    store.upsert_attach_binding("s1", "t1")
    assert store.list_attach_bindings() == {"s1": "t1"}

    store.upsert_attach_binding("s1", "t2")
    assert store.list_attach_bindings() == {"s1": "t2"}

    store.delete_attach_binding("t2")
    assert store.list_attach_bindings() == {}
