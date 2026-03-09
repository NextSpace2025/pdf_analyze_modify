"""스팸 파일을 격리 폴더 또는 휴지통으로 이동."""
from pathlib import Path

import send2trash


def _unique_path(target_dir: Path, file_path: Path) -> Path:
    """동일 파일명 충돌 시 번호를 붙여 유일한 경로 반환."""
    dest = target_dir / file_path.name
    if not dest.exists():
        return dest
    stem = file_path.stem
    suffix = file_path.suffix
    for i in range(1, 10000):
        candidate = target_dir / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
    return target_dir / f"{stem}_9999{suffix}"


def move_to_quarantine(file_path: Path, quarantine_dir: Path) -> Path:
    """파일을 격리 폴더로 이동. 반환값은 최종 이동 경로."""
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique_path(quarantine_dir, file_path)
    file_path.rename(dest)
    return dest


def move_to_trash(file_path: Path) -> None:
    """파일을 휴지통으로 이동."""
    send2trash.send2trash(str(file_path))
