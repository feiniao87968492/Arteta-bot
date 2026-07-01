import os


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
GROUPS_PAGE = os.path.join(REPO_ROOT, "dashboard", "web", "src", "pages", "GroupsPage.tsx")


def read_groups_page():
    with open(GROUPS_PAGE, "r", encoding="utf-8") as f:
        return f.read()


def test_groups_page_can_manage_group_memory_passwords():
    source = read_groups_page()

    assert "memory_password_enabled" in source
    assert "访问密码" in source
    assert "/settings/password" in source
    assert "apiDelete" in source
    assert "设置/更新访问密码" in source
    assert "确认当前访问密码后清除" in source


def test_groups_page_uses_group_password_for_profile_access():
    source = read_groups_page()

    assert "X-Group-Password" in source
    assert "解锁群组档案" in source
    assert "groupPasswords" in source
    assert "password: groupPasswords[selectedGroup]" in source


def test_groups_page_hides_profile_data_after_setting_password():
    source = read_groups_page()

    assert "clearUnlockedGroup" in source
    assert "setUsers([])" in source
    assert "setDetail(null)" in source
    assert "setSelectedUser('')" in source
    assert "setGroupPasswords(current => ({ ...current, [selectedGroup]: groupPassword }))" not in source
    assert "确认当前访问密码后清除" in source


def test_groups_page_displays_group_number_with_name():
    source = read_groups_page()

    assert "group_name" in source
    assert "groupLabel" in source
    assert "群号" in source


def test_groups_page_can_edit_group_name():
    source = read_groups_page()

    assert "editingGroupName" in source
    assert "groupNameDraft" in source
    assert "/settings/name" in source
    assert "编辑名称" in source
    assert "保存名称" in source
    assert "group-row" in source
    assert "group-row-actions" in source


def test_groups_page_keeps_group_and_password_actions_visible():
    source = read_groups_page()

    assert "group-password-actions" in source
    assert "group-row-actions" in source
    assert "设置/更新访问密码" in source
    assert "确认当前访问密码后清除" in source
    assert "编辑名称" in source


def test_groups_page_edits_profile_as_entries_not_raw_json():
    source = read_groups_page()

    assert "profileEntries" in source
    assert "addProfileEntry" in source
    assert "updateProfileEntry" in source
    assert "removeProfileEntry" in source
    assert "profileEntriesToRecord" in source
    assert "添加条目" in source
    assert "删除条目" in source
    assert "条目名称" in source
    assert "条目内容" in source
    assert "profile-json-label" not in source
    assert "主教练对这名球员的了解（JSON）" not in source
    assert "JSON.parse(profileText" not in source
