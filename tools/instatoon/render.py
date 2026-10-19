from copy import deepcopy
from pathlib import Path
import math
import re
import unicodedata
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont, ImageOps
from .common import new_directory, require, write_json, digest

SIZE = 1920


def number(value, label, low=0, high=SIZE):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high, f"Invalid {label}")
    return value


def rectangle(box):
    x, y, w, h = [number(box[k], k) for k in ("x", "y", "width", "height")]
    require(w > 0 and h > 0 and x + w <= SIZE and y + h <= SIZE, "Box extends outside canvas", "layout_overflow")
    return x, y, x + w, y + h


def intersects(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def font_for(ws, item, text):
    value = item["font_path"]
    path = Path(value) if Path(value).is_absolute() else ws.path(value)
    require(path.is_file(), f"Font not found: {value}", "missing_font")
    size = item["font_size"]
    require(type(size) is int and 1 <= size <= 512, "font_size must be an integer from 1 to 512")
    index = item.get("font_index", 0)
    require(type(index) is int and index >= 0, "Invalid font_index")
    with TTFont(path, fontNumber=index, lazy=True) as tt:
        cmap = tt.getBestCmap() or {}
        missing = sorted({c for c in text if not c.isspace() and ord(c) not in cmap})
    require(not missing, f"Font lacks glyphs: {''.join(missing)}", "missing_glyph")
    return ImageFont.truetype(str(path), size=size, index=index), {"font_path": str(path), "sha256": digest(path), "font_index": index}


def wrap_text(draw, text, font, width):
    """Prefer spaces; split long Korean words only when needed. Preserve paragraphs."""
    lines = []
    for paragraph in text.split("\n"):
        current = ""
        for token in re.findall(r"\S+| +", paragraph):
            if draw.textlength(current + token, font=font) <= width:
                current += token
                continue
            if current.strip():
                lines.append(current.rstrip())
                current = ""
            token = token.lstrip()
            for char in token:
                if draw.textlength(current + char, font=font) > width:
                    require(bool(current), "A single glyph exceeds the text area", "text_overflow")
                    lines.append(current)
                    current = ""
                current += char
        lines.append(current.rstrip())
    return lines


def tail_polygon(item, box):
    tail = item.get("tail")
    if tail is None:
        return None
    tip = (number(tail["x"], "tail x"), number(tail["y"], "tail y"))
    x1, y1, x2, y2 = box
    require(not (x1 <= tip[0] <= x2 and y1 <= tip[1] <= y2), "Tail tip must be outside balloon")
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    half = min(24, (x2 - x1) / 6, (y2 - y1) / 6)
    margin = min(48, (x2 - x1) / 4, (y2 - y1) / 4) + half
    if abs((tip[0] - cx) / (x2 - x1)) > abs((tip[1] - cy) / (y2 - y1)):
        x = x2 - 2 if tip[0] > cx else x1 + 2
        base = max(y1 + margin, min(tip[1], y2 - margin))
        return [(x, base - half), tip, (x, base + half)]
    y = y2 - 2 if tip[1] > cy else y1 + 2
    base = max(x1 + margin, min(tip[0], x2 - margin))
    return [(base - half, y), tip, (base + half, y)]


def draw_item(ws, image, item, text, kind):
    require(isinstance(text, str) and text.strip(), "Text cannot be empty")
    text = unicodedata.normalize("NFC", text)
    require(not any(ord(c) < 32 and c != "\n" for c in text), "Unsupported control character")
    box = rectangle(item["box"])
    font, font_record = font_for(ws, item, text)
    padding = number(item.get("padding", 28), "padding")
    width, height = box[2] - box[0] - 2 * padding, box[3] - box[1] - 2 * padding
    require(width > 0 and height > 0, "Padding exceeds balloon dimensions", "text_overflow")
    draw = ImageDraw.Draw(image)
    lines = item.get("lines")
    if lines is None:
        lines = wrap_text(draw, text, font, width)
    require(isinstance(lines, list) and lines and all(isinstance(line, str) and '\n' not in line for line in lines), "Invalid lines")
    require(re.sub(r"\s", "", "".join(lines)) == re.sub(r"\s", "", text), "Layout lines changed original text")
    boxes = [draw.textbbox((0, 0), line, font=font, anchor="lt") for line in lines]
    heights = [max(0, b[3] - b[1]) for b in boxes]
    line_height = number(item.get("line_height", round(item["font_size"] * 1.35)), "line height", 1)
    require(all(h <= line_height for h in heights), "Lines overlap vertically", "text_overflow")
    block_height = line_height * (len(lines) - 1) + max(heights, default=0)
    require(block_height <= height and all(b[2] - b[0] <= width for b in boxes), "Text does not fit balloon; adjust layout or storyboard", "text_overflow")
    stroke = item.get("stroke_width", 4)
    require(type(stroke) is int and 0 <= stroke <= 24, "Invalid stroke width")
    fill, outline = item.get("fill", "white"), item.get("outline", "#222222")
    require(kind in {"dialogue", "narration", "disclosure", "sfx"}, "Unknown text kind")
    container = item.get("container", "auto")
    require(container in {"auto", "none"}, "container must be auto or none")
    tail = tail_polygon(item, box) if kind == "dialogue" and container != "none" else None
    if container == "none":
        pass
    elif kind == "dialogue":
        if tail:
            draw.polygon(tail, fill=fill)
            draw.line(tail, fill=outline, width=stroke)
        draw.rounded_rectangle(box, radius=min(48, (box[2]-box[0])/4, (box[3]-box[1])/4), fill=fill, outline=outline, width=stroke)
        if tail:
            draw.line([tail[0], tail[2]], fill=fill, width=stroke + 4)
    elif kind in {"narration", "disclosure"}:
        draw.rounded_rectangle(box, radius=12, fill=fill, outline=outline, width=stroke)
    else:
        require(kind == "sfx", "Unknown text kind")
    y = box[1] + padding + (height - block_height) / 2
    actual_bounds = []
    for line, bounds in zip(lines, boxes):
        x = box[0] + padding + (width - (bounds[2] - bounds[0])) / 2 - bounds[0]
        # lt anchor includes a top offset for certain glyphs; offset by measured top.
        origin = (x, y - bounds[1])
        draw.text(origin, line, font=font, anchor="lt", fill=item.get("color", "#111111"))
        actual_bounds.append(list(draw.textbbox(origin, line, font=font, anchor="lt")))
        y += line_height
    return {"lines": lines, "line_height": line_height, "text_bounds": actual_bounds, "box": list(box),
            "tail": tail, "container": container, "font": font_record}


def render_panel(ws, req):
    panel = req["panel"]
    layout = deepcopy(req["layout"])
    require(layout.get("schema_version") == 1, "layout schema_version must be 1")
    require(layout.get("panel_id") == panel["panel_id"], "Panel/layout ID mismatch")
    require(layout.get("canvas") == {"width": SIZE, "height": SIZE}, "Canvas must be 1920×1920")
    texts = panel["texts"]
    require(len({t['text_id'] for t in texts}) == len(texts), "Duplicate text IDs")
    items = layout["items"]
    require(len({i['text_id'] for i in items}) == len(items), "Duplicate layout IDs")
    require({i["text_id"] for i in items} == {t["text_id"] for t in texts}, "Every text needs exactly one layout item")
    text_by_id = {t["text_id"]: t for t in texts}
    require(len({t['reading_order'] for t in texts}) == len(texts), "Duplicate reading order")
    art_path = ws.verify(req["art"])
    with Image.open(art_path) as source:
        source = ImageOps.exif_transpose(source)
        original_size = source.size
        require(source.width == source.height, "Artwork must be square; do not silently crop")
        image = source.convert("RGBA").resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    protected = [rectangle(r) for r in layout.get("protected_regions", [])]
    boxes = []
    reports, fonts, warnings = [], [], []
    for item in sorted(items, key=lambda i: text_by_id[i['text_id']]['reading_order']):
        text = text_by_id[item["text_id"]]
        require(item.get("reading_order") == text["reading_order"], "Reading order differs from storyboard")
        box = rectangle(item["box"])
        require(not any(intersects(box, p) for p in protected), "Balloon covers a protected region", "layout_collision")
        require(not any(intersects(box, other) for other in boxes), "Text regions overlap", "layout_collision")
        boxes.append(box)
        report = draw_item(ws, image, item, text["text"], text["kind"])
        report["text_id"] = item["text_id"]
        if report["tail"]:
            xs, ys = zip(*report["tail"])
            envelope = (min(xs), min(ys), max(xs), max(ys))
            if any(intersects(envelope, p) for p in protected):
                warnings.append(f"Tail near protected region: {item['text_id']}; visually verify speaker and occlusion")
        item["lines"], item["line_height"] = report["lines"], report["line_height"]
        reports.append(report)
        fonts.append(report["font"])
    disclosure = layout.get("disclosure")
    require(isinstance(disclosure, dict), "AI disclosure configuration required")
    require(type(disclosure.get("enabled", True)) is bool, "Disclosure enabled must be boolean")
    disclosure_report = {"enabled": False}
    if disclosure.get("enabled", True):
        require(disclosure.get("text", "").strip(), "AI disclosure text and layout required")
        box = rectangle(disclosure["box"])
        require(not any(intersects(box, p) for p in protected + boxes), "Disclosure overlaps artwork or text", "layout_collision")
        disclosure_report = draw_item(ws, image, disclosure, disclosure["text"], "disclosure")
        fonts.append(disclosure_report["font"])
    output = ws.output(req["output_dir"])
    report = {"schema_version": 1, "status": "pass", "panel_id": panel["panel_id"], "panel": panel,
              "inputs": [req["art"]], "fonts": fonts, "source_dimensions": list(original_size),
              "transforms": ["resize_to_1920"] if original_size != (SIZE, SIZE) else [],
              "text_checks": reports, "disclosure": disclosure_report,
              "warnings": warnings, "visual_qa": "not_performed"}
    with new_directory(output) as temp:
        image.save(temp / "composed.png", format="PNG")
        image.resize((1080, 1080), Image.Resampling.LANCZOS).save(temp / "composed-1080.png", format="PNG")
        report["layout"] = layout
        report["outputs"] = {}
        for size, name in ((1920, "composed.png"), (1080, "composed-1080.png")):
            report["outputs"][str(size)] = {"path": ws.relative(output / name), "sha256": digest(temp / name),
                                           "role": "composed", "width": size, "height": size}
        if req.get("metadata_files", False):
            write_json(temp / "layout.json", layout)
            report["inputs"].append({"path": ws.relative(output / "layout.json"), "sha256": digest(temp / "layout.json"), "role": "layout"})
            write_json(temp / "render-report.json", report)
    artifacts = list(report["outputs"].values())
    if req.get("metadata_files", False):
        artifacts.append(ws.artifact(output / "render-report.json", "render_report"))
    return {"artifacts": artifacts, "report": report, "warnings": warnings}


def build_preview(ws, req):
    panels = req["panels"]
    require(isinstance(panels, list) and 1 <= len(panels) <= 10, "Preview requires 1–10 images in reading order")
    require(len({p['panel_id'] for p in panels}) == len(panels), "Duplicate panel ID")
    require([p['order'] for p in panels] == list(range(1, len(panels)+1)), "Preview order must be contiguous")
    columns = min(3, len(panels))
    tile, gap, header = 480, 24, 30
    preview = Image.new("RGB", (columns*(tile+gap)+gap, math.ceil(len(panels)/columns)*(tile+gap+header)+gap), "#eeeeee")
    draw = ImageDraw.Draw(preview)
    for i, panel in enumerate(panels):
        path = ws.verify(panel["image"])
        x, y = gap + (i % columns)*(tile+gap), gap + (i // columns)*(tile+gap+header)
        draw.text((x,y), f"{panel['order']:02d} / {panel['panel_id']}", fill="black", font=ImageFont.load_default(size=18))
        with Image.open(path) as im:
            require(im.width == im.height, "Preview panel must be square")
            preview.paste(im.convert("RGB").resize((tile,tile), Image.Resampling.LANCZOS), (x,y+header))
    output = ws.output(req["output_dir"])
    with new_directory(output) as temp:
        preview.save(temp / "preview.png")
    return {"artifacts": [ws.artifact(output / "preview.png", "preview")], "panels": panels}
