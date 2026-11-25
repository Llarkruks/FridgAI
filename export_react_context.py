from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "frontend-react"
OUT_FILE = PROJECT_ROOT / "react_context.txt"

SKIP_PARTS = {"node_modules", "dist", ".git", ".vite", "__pycache__"}
TARGET_ROOT_FILES = {"package.json", "index.html"}
TARGET_EXTS = {".js", ".jsx", ".ts", ".tsx", ".css", ".json", ".html"}


def should_skip(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts)


def main() -> None:
    if not FRONTEND_DIR.exists():
        print(f"No se encontró la carpeta: {FRONTEND_DIR}")
        return

    lines = ["=== ESTRUCTURA FRONTEND-REACT ==="]
    all_files = []

    for p in sorted(FRONTEND_DIR.rglob("*")):
        if p.is_file() and not should_skip(p.relative_to(FRONTEND_DIR)):
            rel = p.relative_to(FRONTEND_DIR).as_posix()
            lines.append(rel)
            all_files.append(p)

    for p in all_files:
        rel = p.relative_to(FRONTEND_DIR).as_posix()
        is_target = (
            (p.parent == FRONTEND_DIR and (p.name in TARGET_ROOT_FILES or p.name.startswith("vite.config.")))
            or ("src" in p.relative_to(FRONTEND_DIR).parts and p.suffix.lower() in TARGET_EXTS)
        )
        if not is_target:
            continue

        lines.append(f"\n\n==================== FILE: {rel} ====================")
        try:
            content = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = p.read_text(encoding="latin-1", errors="replace")
        lines.append(content)

    OUT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"Contexto generado en: {OUT_FILE}")
    print(f"Archivos incluidos en el volcado: {sum(1 for l in lines if l.startswith('\n\n==================== FILE:'))}")


if __name__ == "__main__":
    main()
