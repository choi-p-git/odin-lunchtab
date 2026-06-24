from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_inno_installer_exposes_uninstall_support() -> None:
    definition = (PROJECT_ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")

    assert "Uninstallable=yes" in definition
    assert "CreateUninstallRegKey=yes" in definition
    assert "UninstallDisplayName={#AppName}" in definition
    assert 'Filename: "{uninstallexe}"' in definition


def test_release_builder_detects_inno_setup_7() -> None:
    build_script = (PROJECT_ROOT / "scripts" / "build-release.ps1").read_text(encoding="utf-8")

    assert "Inno Setup 7\\ISCC.exe" in build_script
    assert "Inno Setup 6\\ISCC.exe" in build_script
    assert '@("_tcl_data", "_tk_data")' in build_script
    assert "Frozen bundle is missing required Tcl/Tk runtime data." in build_script
    assert "ProductVersion" in build_script
    assert "RELEASE_NOTES.md" in build_script
