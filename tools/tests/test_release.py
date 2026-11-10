"""Release policy regression tests. Git mutations occur only in temporary fixtures."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release as r

ASSET = "plugins/demo/skills/demo-task/SKILL.md"
MANIFEST = "plugins/demo/.claude-plugin/plugin.json"
DATE = "2026-11-10"


def fixture():
    tree = {
        "VERSION": "1.6.2\n",
        "CHANGELOG.md": "# Changelog\n\n## [1.6.2] — 2026-10-29\n\nOriginal history.\n",
        MANIFEST: '{"name":"demo","version":"1.5.1"}\n',
        ASSET: '---\nname: demo-task\nmetadata:\n  owner: "Test Owner <test@example.invalid>"\n  version: "1.2.3"\n---\nExisting behavior.\n',
        "README.md": "Existing docs.\n",
        ".changes/README.md": "Fragment instructions.\n",
        r.DEPENDENCIES: r.json_text({"plugins/demo/scripts/*": [ASSET]}),
    }
    tree[r.BASELINE] = r.json_text({"schema": 1, "status": "legacy-bootstrap-not-proof-of-publication", "versions": r.versions(tree), "hashes": r.hashes(tree), "tags": []})
    return tree


def fragment(tree, name="fix-task", components=None, assets=None, category="Fixed", migration=""):
    tree[".changes/" + name + ".json"] = r.json_text({
        "summary": "Correct behavior.", "category": category,
        "components": components if components is not None else {"marketplace": "patch", "demo": "patch"},
        "assets": assets if assets is not None else {ASSET: "patch"}, "migration": migration})


def pending():
    tree = fixture()
    tree[ASSET] += "Corrected behavior.\n"
    fragment(tree)
    return tree


class PolicyTests(unittest.TestCase):
    def test_semver_and_bumps(self):
        self.assertEqual(r.bump("1.9.9", "minor"), "1.10.0")
        self.assertEqual(r.bump("1.9.9", "major"), "2.0.0")
        for value in ("01.0.0", "1.0", "1.0.0-rc.1", "-1.0.0", None):
            with self.assertRaises(r.Invalid):
                r.version(value)

    def test_branches(self):
        for branch in ("main", "fix/abc-123-runtime-paths", "feat/new-output", "docs/readme", "chore/ci", "refactor/parser", "experiment/prototype", "release/1.7.0"):
            r.validate_branch(branch)
        for branch in ("feature/thing", "fix/ABC-123-thing", "release/latest", "release/01.0.0", "fix/", "detached"):
            with self.assertRaises(r.Invalid):
                r.validate_branch(branch)
        with self.assertRaises(r.Invalid):
            r.validate_branch("experiment/prototype", "main")

    def test_commit_subjects(self):
        for subject in ("fix: correct paths", "feat(config)!: change state", "chore(release): prepare 1.7.0", "revert: remove regression"):
            r.validate_commit(subject)
        for subject in ("fix it", "Fix: typo", "feat: ", "feat(BAD): x", "feat: x\nbody"):
            with self.assertRaises(r.Invalid):
                r.validate_commit(subject)

    def test_no_changes_no_fragment(self):
        r.validate_pending(fixture(), fixture(), "fix/task")

    def test_changed_asset_without_fragment(self):
        tree = fixture()
        tree[ASSET] += "changed"
        with self.assertRaisesRegex(r.Invalid, "marketplace fragment"):
            r.validate_pending(tree, fixture(), "fix/task")

    def test_asset_requires_explicit_coverage(self):
        tree = pending()
        fragment(tree, assets={})
        with self.assertRaisesRegex(r.Invalid, "asset fragment"):
            r.validate_pending(tree, fixture(), "fix/task")

    def test_plugin_docs_need_component_not_asset(self):
        tree = fixture()
        tree["plugins/demo/README.md"] = "Docs"
        fragment(tree, assets={})
        r.validate_pending(tree, fixture(), "docs/plugin")
        fragment(tree, components={"marketplace": "patch"}, assets={})
        with self.assertRaisesRegex(r.Invalid, "plugin fragment"):
            r.validate_pending(tree, fixture(), "docs/plugin")

    def test_root_docs_marketplace_only(self):
        tree = fixture()
        tree["README.md"] += "Updated.\n"
        fragment(tree, components={"marketplace": "patch"}, assets={})
        r.validate_pending(tree, fixture(), "docs/root")
        out, _ = r.plan(tree, DATE)
        self.assertEqual(r.versions(out)["demo"], "1.5.1")
        self.assertEqual(r.versions(out)["marketplace"], "1.6.3")

    def test_shared_dependency_coverage(self):
        tree = fixture()
        tree["plugins/demo/scripts/shared.py"] = "pass\n"
        fragment(tree, assets={})
        with self.assertRaisesRegex(r.Invalid, "asset fragment"):
            r.validate_pending(tree, fixture(), "fix/shared")
        fragment(tree)
        r.validate_pending(tree, fixture(), "fix/shared")

    def test_feature_versions_cannot_change(self):
        tree = pending()
        tree["VERSION"] = "1.6.3\n"
        with self.assertRaisesRegex(r.Invalid, "Final versions"):
            r.validate_pending(tree, fixture(), "fix/task")
        with self.assertRaisesRegex(r.Invalid, "Restore published versions"):
            r.plan(tree, DATE)

    def test_existing_metadata_cannot_change_on_feature(self):
        tree = pending()
        tree[ASSET] = tree[ASSET].replace('"1.2.3"', '"1.2.4"')
        with self.assertRaisesRegex(r.Invalid, "Final versions"):
            r.validate_pending(tree, fixture(), "fix/task")

    def test_old_fragment_does_not_cover_new_mr(self):
        base = pending()
        tree = dict(base)
        tree[ASSET] += "Another change.\n"
        with self.assertRaisesRegex(r.Invalid, "marketplace fragment"):
            r.validate_pending(tree, base, "fix/another")

    def test_merged_fragment_immutable(self):
        base = pending()
        for action in ("edit", "delete"):
            tree = dict(base)
            if action == "edit":
                tree[".changes/fix-task.json"] += "\n"
            else:
                del tree[".changes/fix-task.json"]
            with self.assertRaisesRegex(r.Invalid, "Merged fragments"):
                r.validate_pending(tree, base, "fix/task")

    def test_malformed_and_unknown_fragments(self):
        for extra in (".changes/draft.md", ".changes/nested/foo.json", ".changes/Bad.json"):
            tree = pending()
            tree[extra] = "draft"
            with self.assertRaisesRegex(r.Invalid, "Unknown fragment"):
                r.fragments(tree)
        tree = pending()
        f = json.loads(tree[".changes/fix-task.json"])
        f["version"] = "1.6.3"
        tree[".changes/fix-task.json"] = json.dumps(f)
        with self.assertRaisesRegex(r.Invalid, "Invalid fragment fields"):
            r.fragments(tree)

    def test_unknown_components(self):
        tree = pending()
        fragment(tree, components={"marketplace": "patch", "ghost": "patch"})
        with self.assertRaisesRegex(r.Invalid, "Unknown component"):
            r.plan(tree, DATE)

    def test_breaking_requires_migration_and_marketplace_minor(self):
        tree = pending()
        fragment(tree, components={"marketplace": "minor", "demo": "major"}, assets={ASSET: "major"})
        with self.assertRaisesRegex(r.Invalid, "migration"):
            r.fragments(tree)
        fragment(tree, components={"marketplace": "patch", "demo": "major"}, assets={ASSET: "major"}, category="Breaking", migration="Use the new flag.")
        with self.assertRaisesRegex(r.Invalid, "marketplace minor"):
            r.plan(tree, DATE)
        fragment(tree, components={"marketplace": "minor", "demo": "major"}, assets={ASSET: "major"}, category="Breaking", migration="Use the new flag.")
        out, report = r.plan(tree, DATE)
        self.assertEqual(report["versions"]["demo"], "2.0.0")
        self.assertIn("Migration: Use the new flag.", out["CHANGELOG.md"])

    def test_highest_bump_once_and_deterministic(self):
        tree = pending()
        fragment(tree, name="another", components={"marketplace": "minor", "demo": "minor"}, assets={ASSET: "minor"}, category="Added")
        first = r.plan(tree, DATE)
        self.assertEqual(first, r.plan(dict(reversed(list(tree.items()))), DATE))
        out, report = first
        self.assertEqual(report["versions"][ASSET], "1.3.0")
        self.assertEqual(report["versions"]["demo"], "1.6.0")
        self.assertEqual(report["versions"]["marketplace"], "1.7.0")
        self.assertEqual(out["release/archive/1.7.0/fix-task.json"], tree[".changes/fix-task.json"])
        self.assertNotIn(".changes/fix-task.json", out)
        self.assertEqual(out[".changes/README.md"], tree[".changes/README.md"])
        self.assertEqual(json.loads(out[r.CURRENT])["hashes"], r.hashes(out))

    def test_duplicate_version_and_tag_guard(self):
        tree = pending()
        for tag in ("marketplace-v1.6.3", "demo-v1.5.2"):
            with self.assertRaisesRegex(r.Invalid, "already exists"):
                r.plan(tree, DATE, [tag])
        tree["CHANGELOG.md"] += "\n## [1.6.3] — 2026-01-01\n"
        with self.assertRaisesRegex(r.Invalid, "Duplicate changelog"):
            r.plan(tree, DATE)

    def test_release_branch_and_exact_output(self):
        base = pending()
        out, _ = r.plan(base, DATE)
        r.validate_release(out, base, "release/1.6.3")
        r.validate_release(out, base, "main")
        with self.assertRaisesRegex(r.Invalid, "Release branch"):
            r.validate_release(out, base, "release/1.6.4")
        for path in (ASSET, "CHANGELOG.md", "release/archive/1.6.3/fix-task.json", "VERSION"):
            tampered = dict(out)
            tampered[path] += "tampered\n"
            with self.assertRaisesRegex(r.Invalid, "deterministic plan"):
                r.validate_release(tampered, base, "release/1.6.3")

    def test_new_fragment_after_preparation_invalidates_release(self):
        base = pending()
        out, _ = r.plan(base, DATE)
        fragment(out, name="late")
        with self.assertRaisesRegex(r.Invalid, "deterministic plan"):
            r.validate_release(out, base, "release/1.6.3")
        fragment(base, name="target-advanced")
        with self.assertRaisesRegex(r.Invalid, "deterministic plan"):
            r.validate_release(out, base, "release/1.6.3")

    def test_no_fragment_release_fails(self):
        with self.assertRaisesRegex(r.Invalid, "No pending fragments"):
            r.plan(fixture(), DATE)

    def test_archive_collision_fails(self):
        tree = pending()
        tree["release/archive/1.6.3/fix-task.json"] = "unknown"
        with self.assertRaisesRegex(r.Invalid, "Archive collision"):
            r.plan(tree, DATE)

    def test_new_and_removed_assets(self):
        tree = fixture()
        new = "plugins/demo/skills/demo-new/SKILL.md"
        tree[new] = tree[ASSET].replace("1.2.3", "0.0.0")
        fragment(tree, assets={new: "minor"}, components={"marketplace": "minor", "demo": "minor"})
        r.validate_pending(tree, fixture(), "feat/new")
        out, _ = r.plan(tree, DATE)
        self.assertEqual(r.versions(out)[new], "0.1.0")
        tree = fixture()
        del tree[ASSET]
        tree[r.DEPENDENCIES] = "{}\n"
        fragment(tree, assets={ASSET: "major"}, components={"marketplace": "minor", "demo": "major"}, category="Breaking", migration="Use demo replacement.")
        r.validate_pending(tree, fixture(), "refactor/remove")
        out, _ = r.plan(tree, DATE)
        self.assertNotIn(ASSET, r.versions(out))

    def test_second_release_cannot_reuse_plugin_version(self):
        out, _ = r.plan(pending(), DATE)
        second = dict(out)
        second[ASSET] += "Change after publication.\n"
        fragment(second, name="second", components={"marketplace": "patch"}, assets={})
        with self.assertRaisesRegex(r.Invalid, "plugin fragment"):
            r.plan(second, DATE)
        fragment(second, name="second")
        prepared, report = r.plan(second, DATE)
        self.assertEqual(report["versions"]["demo"], "1.5.3")
        self.assertIn("release/archive/1.6.3/fix-task.json", prepared)

    def test_fragment_map_roles_and_readme_coverage(self):
        tree = pending()
        fragment(tree, components={"marketplace": "patch", ASSET: "patch"}, assets={})
        with self.assertRaisesRegex(r.Invalid, "belong in assets"):
            r.fragments(tree)
        tree = fixture()
        tree[".changes/README.md"] += "Changed rules.\n"
        with self.assertRaisesRegex(r.Invalid, "marketplace fragment"):
            r.validate_pending(tree, fixture(), "docs/rules")

    def test_removal_cannot_be_patch(self):
        tree = fixture()
        del tree[ASSET]
        fragment(tree)
        with self.assertRaisesRegex(r.Invalid, "Removed/renamed"):
            r.plan(tree, DATE)

    def test_experiment_is_nonrelease_not_version_bypass(self):
        tree = fixture()
        tree[ASSET] += "Experiment.\n"
        r.validate_pending(tree, fixture(), "experiment/test")
        tree["VERSION"] = "9.0.0\n"
        with self.assertRaises(r.Invalid):
            r.validate_pending(tree, fixture(), "experiment/test")


class GitIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        r.git(self.root, "init", "-b", "main")
        r.git(self.root, "config", "user.name", "Release Test")
        r.git(self.root, "config", "user.email", "release@example.invalid")
        r.git(self.root, "config", "commit.gpgsign", "false")
        self.write(fixture())
        self.commit("chore: fixture")

    def tearDown(self):
        self.temp.cleanup()

    def write(self, tree):
        for p, text in tree.items():
            path = self.root / p
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")

    def commit(self, message):
        r.git(self.root, "add", "--all")
        r.git(self.root, "commit", "-m", message)

    def test_missing_base_fails(self):
        with patch.object(r, "ROOT", self.root):
            self.assertEqual(r.main(["validate", "--base", "missing", "--branch", "fix/test"]), 1)

    def test_untracked_fragment_and_real_prepare(self):
        self.write(pending())
        tree = r.read_tree(self.root)
        r.validate_pending(tree, r.read_tree(self.root, "main"), "fix/test")
        self.commit("fix: correct behavior")
        r.git(self.root, "checkout", "-b", "release/1.6.3")
        with patch.object(r, "ROOT", self.root):
            self.assertEqual(r.main(["prepare", "--date", DATE]), 0)
            self.assertEqual(r.main(["validate-release", "--base", "main"]), 0)
        self.assertFalse((self.root / ".changes/fix-task.json").exists())
        self.assertTrue((self.root / "release/archive/1.6.3/fix-task.json").exists())
        self.commit("chore(release): prepare 1.6.3")
        for tag in ("marketplace-v1.6.3", "demo-v1.5.2"):
            r.git(self.root, "tag", "-a", tag, "-m", "Fixture release")
            r.verify_tag(self.root, r.read_tree(self.root), tag)
        r.ensure_prior_tags(self.root, r.read_tree(self.root))
        # An edited published file cannot pass tag verification under the same number.
        (self.root / ASSET).write_text((self.root / ASSET).read_text() + "tampering", encoding="utf-8")
        with self.assertRaisesRegex(r.Invalid, "content differs"):
            r.verify_tag(self.root, r.read_tree(self.root), "marketplace-v1.6.3")

    def test_dirty_prepare_and_existing_tag_leave_files_untouched(self):
        self.write(pending())
        r.git(self.root, "checkout", "-b", "release/1.6.3")
        before = r.read_tree(self.root)
        with patch.object(r, "ROOT", self.root):
            self.assertEqual(r.main(["prepare", "--date", DATE]), 1)
        self.assertEqual(before, r.read_tree(self.root))
        self.commit("fix: pending")
        r.git(self.root, "tag", "marketplace-v1.6.3")
        with patch.object(r, "ROOT", self.root):
            self.assertEqual(r.main(["prepare", "--date", DATE]), 1)
        self.assertEqual(before, r.read_tree(self.root))

    def test_lightweight_and_missing_prior_tags_fail(self):
        tree, _ = r.plan(pending(), DATE)
        self.write(tree)
        self.commit("chore(release): prepare fixture")
        with self.assertRaises(r.Invalid):
            r.ensure_prior_tags(self.root, tree)
        r.git(self.root, "tag", "marketplace-v1.6.3")
        with self.assertRaisesRegex(r.Invalid, "annotated"):
            r.verify_tag(self.root, tree, "marketplace-v1.6.3")

    def test_bad_committed_subject_fails(self):
        r.git(self.root, "checkout", "-b", "fix/task")
        self.write(pending())
        self.commit("not conventional")
        with patch.object(r, "ROOT", self.root):
            self.assertEqual(r.main(["validate", "--base", "main", "--commits"]), 1)


if __name__ == "__main__":
    unittest.main()
