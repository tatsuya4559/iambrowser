import pathlib
from typing import Final


def read_text_config(filename: str) -> tuple[str]:
    config_dir = pathlib.Path("~/.config/iambrowser").expanduser()
    path = config_dir / pathlib.Path(filename)
    if path.exists():
        with path.open() as fp:
            return tuple(line.strip() for line in fp.readlines())
    else:
        return tuple()


IGNORE_PROFILES: Final[tuple[str]] = read_text_config("ignore")
