import abc
import os
import json
from typing import Any, Callable, TypeVar, Sequence, Union, NamedTuple
from functools import cached_property
from collections import UserList

import boto3
from rich.syntax import Syntax
from rich.traceback import Traceback
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.message import Message, MessageTarget
from textual.widgets import Footer, Header, Static, Tree, TreeNode, Input
import pyperclip


T = TypeVar("T")


class FilteredList(UserList[T]):
    def __init__(self, original: Sequence[T]) -> None:
        if isinstance(original, FilteredList):
            super().__init__(original.data.copy())
            self.original: list[T] = original.original.copy()
            self.current_predicate = original.current_predicate
        else:
            super().__init__(list(original))
            self.original: list[T] = list(original)
            self.current_predicate = None

    def filter(self, predicate: Callable[[T], bool]) -> None:
        self.current_predicate = predicate
        self.data = [e for e in self.original if predicate(e)]

    def refilter(self) -> None:
        if self.current_predicate:
            self.filter(self.current_predicate)

    # append以外はoriginalを操作しなくてもバグらないので手抜き
    def append(self, item: T) -> None:
        self.original.append(item)
        self.refilter()


class Entry(abc.ABC):
    is_filterable = False

    def __init__(self) -> None:
        self.is_loaded = False

    def load(self, node: TreeNode, force: bool = False) -> None:
        if force:
            node._children = []
            self.is_loaded = False
        if self.is_loaded:
            return
        self.load_children(node)
        self.is_loaded = True

    @abc.abstractmethod
    def load_children(self, node: TreeNode) -> None:
        ...

    @property
    @abc.abstractmethod
    def name(self) -> str:
        ...


class IamInlinePolicyEntry(Entry):
    is_filterable = True

    def __init__(self, policy: Any) -> None:
        super().__init__()
        self.policy = policy
        self.policy_document = json.dumps(policy.policy_document, indent=2)

    def load_children(self, node: TreeNode) -> None:
        pass

    @property
    def name(self) -> str:
        return self.policy.policy_name


class IamAttachedPolicyEntry(Entry):
    is_filterable = True

    def __init__(self, policy: Any) -> None:
        super().__init__()
        self.policy = policy

    def load_children(self, node: TreeNode) -> None:
        del self.policy_document

    @property
    def name(self) -> str:
        return self.policy.policy_name

    @cached_property
    def policy_document(self) -> str:
        pv = [v for v in self.policy.versions.all()][0]
        pv.load()
        return json.dumps(pv.document, indent=2)


IamPolicyEntry = Union[IamInlinePolicyEntry, IamAttachedPolicyEntry]


class IamRoleEntry(Entry):
    is_filterable = True

    def __init__(self, role: Any) -> None:
        super().__init__()
        self.role = role

    def load_children(self, node: TreeNode) -> None:
        for p in self.role.policies.all():
            e = IamInlinePolicyEntry(policy=p)
            node.add_leaf(e.name, data=e)
        for p in self.role.attached_policies.all():
            e = IamAttachedPolicyEntry(policy=p)
            node.add_leaf(e.name, data=e)

    @property
    def name(self) -> str:
        return self.role.name


class IamUserEntry(Entry):
    is_filterable = True

    def __init__(self, user: Any) -> None:
        super().__init__()
        self.user = user

    def load_children(self, node: TreeNode) -> None:
        for p in self.user.policies.all():
            e = IamInlinePolicyEntry(policy=p)
            node.add_leaf(e.name, data=e)
        for p in self.user.attached_policies.all():
            e = IamAttachedPolicyEntry(policy=p)
            node.add_leaf(e.name, data=e)

    @property
    def name(self) -> str:
        return self.user.name


class SectionEntry(Entry):
    def __init__(self, name: str, on_load: Callable[[TreeNode], None]) -> None:
        super().__init__()
        self._name = name
        self.on_load = on_load

    def load_children(self, node: TreeNode) -> None:
        self.on_load(node)

    @property
    def name(self) -> str:
        return self._name


class ProfileEntry(Entry):
    def __init__(self, profile_name: str) -> None:
        super().__init__()
        self.profile_name = profile_name

    def load_children(self, node: TreeNode) -> None:
        session = boto3.Session(profile_name=self.profile_name)
        iam = session.resource("iam")

        def load_users(node):
            for u in iam.users.all():  # type: ignore
                e = IamUserEntry(user=u)
                node.add(e.name, data=e)

        def load_roles(node):
            for r in iam.roles.all():  # type: ignore
                e = IamRoleEntry(role=r)
                node.add(e.name, data=e)

        node.add("users", data=SectionEntry("users", on_load=load_users))
        node.add("roles", data=SectionEntry("roles", on_load=load_roles))

    @property
    def name(self) -> str:
        return self.profile_name


class IamTree(Tree[Entry]):
    class PolicySelected(Message, bubble=True):
        def __init__(self, sender: MessageTarget, selected: IamPolicyEntry):
            super().__init__(sender)
            self.name = selected.name
            self.document = selected.policy_document

    def load_profiles(self, node: TreeNode[Entry]) -> None:
        profiles = boto3.Session().available_profiles
        for p in profiles:
            if p in APP_CONFIG.IGNORE_PROFILES:
                continue
            node.add(p, data=ProfileEntry(profile_name=p))
        node.expand()

    def on_mount(self) -> None:
        self.load_profiles(self.root)

    def on_tree_node_expanded(self, event: Tree.NodeSelected) -> None:
        event.stop()
        entry = event.node.data
        if entry is None:
            return
        entry.load(event.node)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        event.stop()
        entry = event.node.data
        if not isinstance(entry, (IamInlinePolicyEntry, IamAttachedPolicyEntry)):
            return
        self.emit_no_wait(IamTree.PolicySelected(self, entry))

    def filter_node(self, filtering_text: str) -> None:
        def f(node: TreeNode[Entry]) -> bool:
            if node.data is None:
                return True
            if not node.data.is_filterable:
                return True
            if filtering_text in node.data.name:
                return True
            return False

        for node in self._nodes.values():
            node._children = FilteredList(node._children)  # type: ignore
            node._children.filter(f)
        self.refresh()


class IamBrowser(App):
    BINDINGS = [
        # key, action, descripiton
        ("q", "quit", "Quit"),
        ("c", "copy", "Copy policy"),
        ("f5", "reload", "Reload current node"),
    ]
    CSS_PATH = "iam_browser.css"

    def __init__(self):
        super().__init__()
        self.rendering_policy_document = ""

    def on_mount(self, event: events.Mount) -> None:
        self.tree_view.focus()

    def compose(self) -> ComposeResult:
        yield Header()
        self.tree_view = IamTree("profile", id="tree-view")
        self.search_box = Input(id="search-box")
        yield Container(
            self.tree_view,
            # FIXME: マウスで選択してコピペしたい
            Vertical(Static(id="document", expand=True), id="document-view"),
            self.search_box,
        )
        yield Footer()

    def on_iam_tree_policy_selected(self, event: IamTree.PolicySelected) -> None:
        event.stop()
        document_view = self.query_one("#document", Static)
        try:
            syntax = Syntax(
                code=event.document,
                lexer="json",
                line_numbers=True,
                word_wrap=False,
                indent_guides=True,
                theme="github-dark",
            )
        except Exception:
            document_view.update(Traceback(theme="github-dark", width=None))
            self.sub_title = "ERROR"
            return
        document_view.update(syntax)
        self.rendering_policy_document = event.document
        self.query_one("#document-view").scroll_home(animate=False)
        self.sub_title = event.name

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.tree_view.filter_node(self.search_box.value)

    def on_key(self, event: events.Key) -> None:
        if event.key == "j":
            self.action_move_cursor(self.tree_view.cursor_line + 1)
        elif event.key == "k":
            self.action_move_cursor(self.tree_view.cursor_line - 1)
        elif event.key == "g":
            self.action_move_cursor(0)
        elif event.key == "G":
            self.action_move_cursor(self.tree_view.last_line)

    def action_move_cursor(self, line: int) -> None:
        node = self.tree_view.get_node_at_line(line)
        self.tree_view.select_node(node)
        assert self.tree_view.cursor_node is not None
        self.tree_view.scroll_to_node(self.tree_view.cursor_node)

    def action_copy(self) -> None:
        pyperclip.copy(self.rendering_policy_document)

    def action_reload(self) -> None:
        node = self.tree_view.cursor_node
        if node is None or node.data is None:
            return
        node.data.load(node, force=True)
        # refilter
        self.tree_view.filter_node(self.search_box.value)


class AppConfig(NamedTuple):
    IGNORE_PROFILES: tuple[str]


APP_CONFIG: AppConfig
with open(os.path.expanduser("~/.config/iambrowser/ignore")) as fp:
    ignore_profiles = tuple(l.strip() for l in fp.readlines())
    APP_CONFIG = AppConfig(IGNORE_PROFILES=ignore_profiles)


if __name__ == "__main__":
    IamBrowser().run()
