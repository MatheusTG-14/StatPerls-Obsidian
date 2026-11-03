"""Unpack every image/video from the tarball once into data/media/ (DEC-07).

Names come from the registry's "attachments" namespace, assigned in sorted
member order, so case-colliding members get stable `__2` suffixes. Builds then
hard-link from here instead of re-reading the 2 GB archive.
"""
import sys
import tarfile
from pathlib import Path

from src import progress
from src.common import write_json
from src.render.names import Registry, sanitize

MEDIA_EXT = (".jpg", ".mp4", ".mov")


def attachment_name(registry, src):
    stem, _, ext = src.rpartition(".")
    base, ext = sanitize(stem), ext.lower()
    return registry.assign_with("attachments", src, lambda n: f"{base}.{ext}" if n == 1 else f"{base}__{n}.{ext}")


def unpack(tar_path, out_dir, members_json, registry_path):
    sys.stdout.reconfigure(encoding="utf-8")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    reg = Registry(registry_path)
    with tarfile.open(tar_path, "r:gz") as tf:
        members = [m for m in tf.getmembers() if m.isfile() and m.name.lower().endswith(MEDIA_EXT)]
        sizes = {m.name.split("/", 1)[1]: m.size for m in members}
        names = {src: attachment_name(reg, src) for src in sorted(sizes)}
        written = 0
        for k, m in enumerate(members, 1):  # archive order: sequential read of the gzip stream
            progress.tick("figures", k, len(members), "figures")
            src = m.name.split("/", 1)[1]
            dest = out / names[src]
            with tf.extractfile(m) as fh:
                data = fh.read()
            if dest.exists() and dest.stat().st_size == len(data) and dest.read_bytes() == data:
                continue  # identical bytes; equal size alone could hide a replaced image
            with open(dest, "wb") as fo:
                fo.write(data)
            written += 1
    reg.save()
    write_json(members_json, {src: {"file": names[src], "size": sizes[src]} for src in sorted(sizes)})
    print(f"media members {len(sizes)}, written {written}, files on disk {len(list(out.iterdir()))}")
