from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as file:
        version = tomllib.load(file)["project"]["version"]
    parts = [int(part) for part in version.split(".")]
    numeric = tuple((parts + [0, 0, 0, 0])[:4])
    comma_version = ", ".join(str(part) for part in numeric)
    output = PROJECT_ROOT / "build" / "version_info.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({comma_version}),
    prodvers=({comma_version}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        "040904B0",
        [
          StringStruct("CompanyName", "Odin Lunchtab"),
          StringStruct("FileDescription", "Odin to Lunchtab Balance Transfer"),
          StringStruct("FileVersion", "{version}"),
          StringStruct("InternalName", "OdinLunchtab"),
          StringStruct("OriginalFilename", "OdinLunchtab.exe"),
          StringStruct("ProductName", "Odin to Lunchtab Balance Transfer"),
          StringStruct("ProductVersion", "{version}"),
        ],
      )
    ]),
    VarFileInfo([VarStruct("Translation", [1033, 1200])]),
  ],
)
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
