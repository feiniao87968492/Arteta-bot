import os
from typing import Dict, List


class DocsService:
    def __init__(self, roots: List[str]):
        self.roots = [os.path.abspath(root) for root in roots]
        self.root_names = {os.path.basename(root): root for root in self.roots}

    def _resolve(self, relative_path: str) -> str:
        normalized = relative_path.replace("\\", "/")
        parts = normalized.split("/", 1)
        if not parts or parts[0] not in self.root_names:
            raise ValueError("path not allowed")
        root = self.root_names[parts[0]]
        tail = parts[1] if len(parts) > 1 else ""
        target = os.path.abspath(os.path.join(root, tail))
        if target != root and not target.startswith(root + os.sep):
            raise ValueError("path not allowed")
        return target

    def tree(self) -> List[Dict[str, object]]:
        return [self._tree_root(root) for root in self.roots if os.path.isdir(root)]

    def _tree_root(self, root: str) -> Dict[str, object]:
        name = os.path.basename(root)
        children = []
        for entry in sorted(os.listdir(root)):
            full = os.path.join(root, entry)
            if os.path.isdir(full):
                children.append(self._tree_node(root, full))
            elif entry.endswith(".md"):
                children.append({"type": "file", "name": entry, "path": name + "/" + entry})
        return {"type": "directory", "name": name, "path": name, "children": children}

    def _tree_node(self, root: str, path: str) -> Dict[str, object]:
        root_name = os.path.basename(root)
        rel = os.path.relpath(path, root).replace("\\", "/")
        node_path = root_name + "/" + rel
        children = []
        for entry in sorted(os.listdir(path)):
            full = os.path.join(path, entry)
            if os.path.isdir(full):
                children.append(self._tree_node(root, full))
            elif entry.endswith(".md"):
                children.append({"type": "file", "name": entry, "path": node_path + "/" + entry})
        return {"type": "directory", "name": os.path.basename(path), "path": node_path, "children": children}

    def read_file(self, relative_path: str) -> Dict[str, str]:
        normalized = relative_path.replace("\\", "/")
        target = self._resolve(normalized)
        if not target.endswith(".md") or not os.path.isfile(target):
            raise ValueError("path not allowed")
        with open(target, "r", encoding="utf-8") as f:
            return {"path": normalized, "content": f.read()}

    def search(self, query: str) -> List[Dict[str, str]]:
        needle = query.lower().strip()
        if not needle:
            return []
        results = []
        for root in self.roots:
            if not os.path.isdir(root):
                continue
            root_name = os.path.basename(root)
            for current, _, files in os.walk(root):
                for filename in files:
                    if not filename.endswith(".md"):
                        continue
                    full = os.path.join(current, filename)
                    with open(full, "r", encoding="utf-8") as f:
                        text = f.read()
                    idx = text.lower().find(needle)
                    if idx >= 0:
                        rel = os.path.relpath(full, root).replace("\\", "/")
                        start = max(0, idx - 80)
                        end = min(len(text), idx + 160)
                        results.append({"path": root_name + "/" + rel, "excerpt": text[start:end]})
        return results[:50]
