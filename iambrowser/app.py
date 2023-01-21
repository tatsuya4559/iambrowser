from rich.syntax import Syntax
from rich.traceback import Traceback
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Footer, Header, Static, Input
import pyperclip

from tree import IamTree


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


if __name__ == "__main__":
    IamBrowser().run()
