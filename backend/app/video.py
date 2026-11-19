"""ffmpeg helpers."""
from __future__ import annotations
import subprocess
from pathlib import Path

FPS = 16


def _run(cmd: list[str]):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {p.stderr[-800:]}")


def frames_to_mp4(frame_dir: Path, out: Path, fps: int = FPS):
    _run(["ffmpeg", "-y", "-framerate", str(fps), "-i", str(frame_dir / "%05d.png"),
          "-c:v", "libx264", "-crf", "12", "-preset", "medium", "-pix_fmt", "yuv420p",
          "-movflags", "+faststart", str(out)])


def extract_last_frame(video: Path, out: Path):
    """Grab the final frame of a clip with ffmpeg (seek to the tail, keep overwriting one image)."""
    out.unlink(missing_ok=True)
    _run(["ffmpeg", "-y", "-sseof", "-1", "-i", str(video), "-update", "1", "-q:v", "1", str(out)])
    if not out.exists():
        raise RuntimeError("could not extract last frame")


def concat(videos: list[Path], out: Path):
    lst = out.parent / "concat.txt"
    lst.write_text("".join(f"file '{v.resolve()}'\n" for v in videos))
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
          "-movflags", "+faststart", str(out)])
