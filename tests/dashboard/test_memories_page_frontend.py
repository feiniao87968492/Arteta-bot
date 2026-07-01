import os


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
MEMORIES_PAGE = os.path.join(REPO_ROOT, "dashboard", "web", "src", "pages", "MemoriesPage.tsx")


def read_memories_page():
    with open(MEMORIES_PAGE, "r", encoding="utf-8") as f:
        return f.read()


def test_memories_page_groups_chroma_memories_by_group():
    source = read_memories_page()
    assert "apiGet<Group[]>('/api/groups')" in source
    assert "memory-group-layout" in source
    assert "群组分类" in source
    assert "全部群组" not in source
    assert "selectGroup(group.group_id)" in source
    assert "selectGroup('')" not in source
    assert "load('')" not in source
    assert "memory_password_enabled" in source
    assert "X-Group-Password" in source
    assert "group_id" in source
    assert "group_name" in source
    assert "groupLabel" in source
    assert "群号" in source
    assert 'placeholder="按 group_id 过滤"' not in source
