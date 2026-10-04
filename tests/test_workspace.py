import pytest

from ai_ceo.workspace import GitError, GitRepo, UnsafePathError, Workspace, validate_rel_path
from ai_ceo.workspace.analysis import analyze_repository, parse_python, search


@pytest.mark.parametrize(
    "bad",
    ["../x.js", "/etc/passwd", ".git/config", "a\\b.js", "x.exe", "C:/x.js", ".env", "a/b/c/d/e.js", "", "a/../b.js", "sub/.hidden.js"],
)
def test_unsafe_paths_rejected(bad):
    with pytest.raises(UnsafePathError):
        validate_rel_path(bad)


@pytest.mark.parametrize("good", ["index.html", "backend/main.py", "docs/REQUIREMENTS.md", "Dockerfile", ".gitignore"])
def test_safe_paths_accepted(good):
    assert validate_rel_path(good) == good


def test_workspace_write_read_and_size_limit(tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.create()
    ws.write("a/b.js", "x\r\ny")
    assert ws.read("a/b.js") == "x\ny"
    assert ws.list_files() == ["a/b.js"]
    with pytest.raises(UnsafePathError):
        ws.write("big.js", "x" * 500_000)


def test_git_commit_log_restore_archive(tmp_path):
    root = tmp_path / "repo"
    ws, repo = Workspace(root), GitRepo(root)
    ws.create()
    assert repo.init()
    repo.checkout("develop", create=True)
    ws.write("index.html", "<p>v1</p>")
    c1 = repo.commit_all("feat: v1", author="Frontend Developer")
    ws.write("index.html", "<p>v2</p>")
    ws.write("extra.js", "1")
    repo.commit_all("feat: v2")
    assert repo.commit_all("noop") is None  # nothing changed

    log = repo.log()
    assert [c.message for c in log][:2] == ["feat: v2", "feat: v1"]
    assert log[1].author == "Frontend Developer"
    assert "v2" in repo.show(log[0].sha)

    # Rollback is a new commit restoring the old tree (history preserved, added files removed).
    new = repo.restore_to(c1, "revert to v1")
    assert new and ws.read("index.html") == "<p>v1</p>" and not ws.exists("extra.js")
    assert len(repo.log()) == 4

    repo.checkout("main")
    repo.merge("develop", "release")
    repo.tag("v1.0.0", "release")
    out = repo.archive("v1.0.0", tmp_path / "rel.zip")
    assert out.stat().st_size > 0
    with pytest.raises(GitError):
        repo.restore_to("not-a-sha", "x")


def test_analysis_graph_routes_and_search():
    files = {
        "index.html": '<html><body><p id="a"></p><script src="app.js"></script><link rel="stylesheet" href="style.css"></body></html>',
        "app.js": "function go() {}\nfetch('/api/items')",
        "style.css": "body{}",
        "backend/main.py": "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/api/items')\ndef items(): return []\n",
    }
    a = analyze_repository(files)
    kinds = {(d["from"], d["to"], d["kind"]) for d in a["dependencies"]}
    assert ("index.html", "app.js", "script") in kinds
    assert ("app.js", "/api/items", "http") in kinds
    assert a["routes"] == [{"method": "GET", "path": "/api/items", "file": "backend/main.py"}]
    assert search(files, "fetch")[0]["path"] == "app.js"
    assert parse_python("def (:").syntax_error
