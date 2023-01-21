import abc
import json
from typing import Any, Callable, TypeVar, Sequence, Union
from functools import cached_property
from collections import UserList

import boto3
from textual.message import Message, MessageTarget
from textual.widgets import Tree, TreeNode

from settings import IGNORE_PROFILES


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
            if p in IGNORE_PROFILES:
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
