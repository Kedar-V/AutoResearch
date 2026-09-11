from autoresearch_api.code_agent import summarize_diff


def test_summarize_diff_lists_changed_files() -> None:
    diff = """diff --git a/train.py b/train.py
index 111..222 100644
--- a/train.py
+++ b/train.py
@@ -1 +1 @@
-old
+new
"""
    assert summarize_diff(diff) == "Modified train.py."
    assert summarize_diff("") == "No file changes."
