"""图片资产落盘 — 从 MinerU zip 对齐 content_list 并写入 storage/media/{doc_id}/images/"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app.config import settings
from app.services import media_store


class ImageAssetError(Exception):
    pass


@dataclass(frozen=True)
class ImageAsset:
    image_id: str
    local_path: Path
    origin_relpath: str
    width: int
    height: int
    ext: str


def images_dir(doc_id: str) -> Path:
    return media_store.images_dir(doc_id)


def make_image_id(doc_id: str, seq: int) -> str:
    return f"img_{media_store.doc8(doc_id)}_{seq:04d}"


def iter_image_blocks(content_list: list[dict] | None) -> list[dict]:
    blocks: list[dict] = []
    for block in content_list or []:
        if isinstance(block, dict) and block.get("type") == "image":
            blocks.append(block)
    return blocks


def _normalize_relpath(raw) -> str:
    """zip 内路径归一化：去掉前导 ./ 与顶层目录前缀中的空白，统一用 /"""
    if raw is None:
        path = ""
    elif isinstance(raw, (list, tuple)):
        path = " ".join(str(x).strip() for x in raw if x is not None and str(x).strip())
    else:
        path = str(raw).strip()
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def _lookup_zip_member(names: list[str], img_path: str) -> str | None:
    target = _normalize_relpath(img_path)
    if not target:
        return None
    name_map = {_normalize_relpath(n): n for n in names}
    if target in name_map:
        return name_map[target]
    # 兼容 zip 顶层多包一层目录（如 <task_id>/images/xxx.jpg）
    basename = target.rsplit("/", 1)[-1]
    for norm, orig in name_map.items():
        if norm.endswith("/" + basename) or norm == basename:
            return orig
    return None


def _ext_from_name(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return suffix.lstrip(".") or "png"


def _decode_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def _meets_min_size(img: Image.Image) -> bool:
    w, h = img.size
    min_side = settings.IMAGE_MIN_SIDE_PX
    min_area = settings.IMAGE_MIN_AREA_PX
    if w < min_side or h < min_side:
        return False
    if w * h < min_area:
        return False
    return True


def load_existing_assets(doc_id: str) -> dict[str, ImageAsset]:
    """读取已落盘的图片，供 zip 失败时复用。按 image_id 索引。"""
    dir_path = images_dir(doc_id)
    if not dir_path.exists():
        return {}
    assets: dict[str, ImageAsset] = {}
    for path in sorted(dir_path.iterdir()):
        if path.suffix == ".json" or not path.is_file():
            continue
        if path.name.endswith("_vlm.png") or path.name.endswith("_vlm.jpg"):
            continue
        image_id = path.stem
        try:
            img = Image.open(path)
            img.load()
            w, h = img.size
        except Exception:
            continue
        assets[image_id] = ImageAsset(
            image_id=image_id,
            local_path=path,
            origin_relpath="",
            width=w,
            height=h,
            ext=path.suffix.lstrip(".").lower(),
        )
    return assets


def ensure_zip_assets(doc_id: str, content_list: list[dict], zip_bytes: bytes | None) -> dict[str, ImageAsset]:
    """将 zip 中被 content_list 引用的图片写入 media 目录。

    返回 image_id → ImageAsset。失败文件跳过；zip 不可用时尝试复用历史落盘。
    """
    image_blocks = iter_image_blocks(content_list)
    out_dir = images_dir(doc_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not zip_bytes:
        return load_existing_assets(doc_id) if image_blocks else {}

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ImageAssetError(f"无效的 zip 数据: {exc}") from exc

    assets: dict[str, ImageAsset] = {}
    names = zf.namelist()
    seq = 0
    for block in image_blocks:
        img_path = block.get("img_path") or ""
        image_id = make_image_id(doc_id, seq)
        seq += 1
        member = _lookup_zip_member(names, img_path)
        if not member:
            continue
        try:
            data = zf.read(member)
        except KeyError:
            continue
        try:
            img = _decode_image(data)
        except Exception:
            continue
        ext = _ext_from_name(member)
        local_path = out_dir / f"{image_id}.{ext}"
        if ext in ("jpg", "jpeg", "png", "webp", "bmp"):
            local_path.write_bytes(data)
        else:
            # 统一规范化为 PNG 副本
            ext = "png"
            local_path = out_dir / f"{image_id}.png"
            img.save(local_path, format="PNG")
        assets[image_id] = ImageAsset(
            image_id=image_id,
            local_path=local_path,
            origin_relpath=_normalize_relpath(member),
            width=img.size[0],
            height=img.size[1],
            ext=ext,
        )
    return assets


def resolve(block: dict, doc_id: str, seq: int, assets: dict[str, ImageAsset] | None = None) -> tuple[str, Path | None]:
    """返回 (image_id, local_path)。local_path 可能为 None（missing_asset）。"""
    image_id = make_image_id(doc_id, seq)
    if assets and image_id in assets:
        return image_id, assets[image_id].local_path
    return image_id, None


def is_too_small(width: int, height: int) -> bool:
    return width < settings.IMAGE_MIN_SIDE_PX or height < settings.IMAGE_MIN_SIDE_PX or (
        width * height < settings.IMAGE_MIN_AREA_PX
    )


def resize_for_vlm(image_bytes: bytes, max_side: int | None = None) -> bytes:
    """最长边缩放到 ≤ max_side，返回 PNG bytes。"""
    max_side = max_side or settings.VLM_MAX_IMAGE_SIDE
    img = Image.open(io.BytesIO(image_bytes))
    img.load()
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    w, h = img.size
    longest = max(w, h)
    if longest <= max_side:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    scale = max_side / float(longest)
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    resized = img.resize(new_size, Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    resized.save(buf, format="PNG")
    return buf.getvalue()


def read_image_bytes(path: Path) -> bytes:
    return path.read_bytes()


def cleanup_doc_media(doc_id: str) -> None:
    import shutil

    doc_media = media_store.media_root(doc_id)
    if doc_media.exists():
        shutil.rmtree(doc_media, ignore_errors=True)
