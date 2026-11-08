"""Edit pre-segmented real HeiXia frames and GPT poses into a transparent motion pack."""
import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
from statistics import median
import subprocess
from zoneinfo import ZoneInfo

from PIL import Image, ImageChops, ImageStat


FPS = 12
CANVAS = (640, 360)
BASELINE = 330


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def open_frame(path):
    with Image.open(path) as frame:
        return frame.convert('RGBA')


def subject_box(frame):
    return frame.getchannel('A').point(lambda value: 255 if value > 8 else 0).getbbox()


def stabilize_paws(frames):
    """Remove camera drift in the seated shot using the stationary front paws."""
    anchors = {}
    for index, frame in frames.items():
        mask = frame.getchannel('A').point(lambda value: 255 if value > 128 else 0)
        left, top, right, bottom = mask.getbbox()
        band = max(8, round((bottom - top) * 0.08))
        paw_left, _, paw_right, _ = mask.crop((left, bottom - band, right, bottom)).getbbox()
        anchors[index] = (left + (paw_left + paw_right) / 2, bottom)
    ref_x, ref_y = (median(anchor[axis] for anchor in anchors.values()) for axis in (0, 1))
    aligned = {}
    for index, frame in frames.items():
        neighbors = [anchors[n] for n in range(index - 1, index + 2) if n in anchors]
        dx, dy = (round(ref - median(p[axis] for p in neighbors))
                  for axis, ref in enumerate((ref_x, ref_y)))
        aligned[index] = Image.new('RGBA', frame.size)
        aligned[index].paste(frame, (dx, dy))
    return aligned


def fit(frames, height):
    boxes = [subject_box(frame) for frame in frames]
    if any(box is None for box in boxes):
        raise ValueError('A source frame has no visible subject')
    w, h = next(iter(frames)).size
    box = (max(0, min(b[0] for b in boxes) - 2), max(0, min(b[1] for b in boxes) - 2),
           min(w, max(b[2] for b in boxes) + 2), min(h, max(b[3] for b in boxes) + 2))
    sw, sh = box[2] - box[0], box[3] - box[1]
    scale = min(height / sh, 600 / sw)
    return box, (max(2, round(sw * scale / 2) * 2), max(2, round(sh * scale / 2) * 2))


def compose(frame, box, size):
    layer = frame.crop(box).resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', CANVAS)
    canvas.alpha_composite(layer, ((CANVAS[0] - size[0]) // 2, BASELINE - size[1]))
    return canvas


def light_preview(frame):
    canvas = Image.new('RGBA', (160, 90), '#eff3ed')
    canvas.alpha_composite(frame.resize(canvas.size, Image.Resampling.LANCZOS))
    return canvas.convert('RGB')


def difference(a, b):
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


def encode(ffmpeg, ffprobe, frames, output):
    encoded = output.with_suffix('.partial.webm')
    raw = b''.join(frame.tobytes() for frame in frames)
    subprocess.run([
        ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'rawvideo',
        '-pixel_format', 'rgba', '-video_size', '640x360', '-framerate', str(FPS), '-i', 'pipe:0',
        '-an', '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-lossless', '1', '-auto-alt-ref', '0',
        '-lag-in-frames', '0', '-threads', '2', '-row-mt', '1', '-y', str(encoded),
    ], input=raw, check=True)
    probe = json.loads(subprocess.check_output([
        ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(encoded),
    ]))
    stream, = probe['streams']
    if (stream['codec_name'], stream['width'], stream['height']) != ('vp9', *CANVAS):
        raise ValueError(f'Wrong codec or dimensions in {output.name}')
    if not any(k.lower() == 'alpha_mode' and v == '1' for k, v in stream['tags'].items()):
        raise ValueError(f'No alpha tag in {output.name}')
    pixels = subprocess.check_output([
        ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-c:v', 'libvpx-vp9',
        '-i', str(encoded), '-vf', 'alphaextract', '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1',
    ])
    plane = CANVAS[0] * CANVAS[1]
    if len(pixels) != plane * len(frames):
        raise ValueError(f'Decoded frame count changed in {output.name}')
    for offset in range(0, len(pixels), plane):
        low, high = Image.frombytes('L', CANVAS, pixels[offset:offset + plane]).getextrema()
        if low != 0 or high < 200:
            raise ValueError(f'Invalid alpha frame in {output.name}')
    encoded.replace(output)
    return float(probe['format']['duration'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--sources', type=Path, required=True, help='Folder of numbered RGBA frame sequences')
    parser.add_argument('--output', type=Path, required=True, help='New staging folder')
    args = parser.parse_args()
    ffmpeg, ffprobe = (shutil.which(tool) for tool in ('ffmpeg', 'ffprobe'))
    if not ffmpeg or not ffprobe:
        parser.error('FFmpeg and ffprobe are required')
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    groups = defaultdict(set)
    rows = plan['items']
    states, names = set(), set()
    for row in rows:
        name, state, key = row['name'], row['state'], row['source']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', state) or not re.fullmatch(r'[A-Za-z0-9_-]+', key):
            raise ValueError('State and source must be safe folder names')
        if not name or re.search(r'[\\/:*?"<>|\x00-\x1f]', name) or name.startswith('.'):
            raise ValueError('Animation name must be a local filename')
        if state in states or name in names:
            raise ValueError(f'Duplicate animation: {state}/{name}')
        states.add(state)
        names.add(name)
        start, end = row['frames']
        if not 1 <= start <= end or row['playback'] not in ('hold', 'loop', 'return', 'once'):
            raise ValueError(f'Invalid edit for {state}')
        if row['playback'] == 'hold' and start != end:
            raise ValueError(f'Hold must reference one frame for {state}')
        groups[key].update(range(start, end + 1))
    media = args.output / 'heixia-animation'
    media.mkdir(parents=True, exist_ok=False)
    fitted = {}
    for key, numbers in groups.items():
        frames = {n: open_frame(args.sources / key / f'{n:06}.png') for n in sorted(numbers)}
        settings = plan['sources'][key]
        if settings.get('stabilize_paws'):
            frames = stabilize_paws(frames)
        box, size = fit(frames.values(), settings['height'])
        fitted[key] = ({n: compose(frame, box, size) for n, frame in frames.items()}, size)
    items = []
    for row in rows:
        key, mode = row['source'], row['playback']
        frames, size = fitted[key]
        start, end = row['frames']
        sequence = [frames[n] for n in range(start, end + 1)]
        if mode == 'hold':
            sequence *= 24
        elif mode == 'return':
            # Only subtle, naturally reversible gestures use the same frames on the return.
            if row.get('start_at_end'):
                sequence.reverse()
            sequence += sequence[-2:0:-1]
        elif mode == 'once':
            sequence += [sequence[-1]] * 2
        preview = [light_preview(frame) for frame in sequence]
        seam = difference(preview[-1], preview[0])
        peak = max(difference(a, b) for a, b in zip(preview, preview[1:]))
        if mode in ('loop', 'return') and seam > max(1.5, peak * 1.25):
            raise ValueError(f'{row["state"]}: jump at loop seam ({seam:.2f} > {peak:.2f})')
        destination = media / (row['name'] + '.webm')
        duration = encode(ffmpeg, ffprobe, sequence, destination)
        settings = plan['sources'][key]
        provenance = dict(settings['provenance'])
        if 'video_id' in provenance:
            provenance['start_s'] = round(provenance.get('start_s', 0) + (start - 1) / FPS, 4)
            provenance['duration_s'] = round((end - start + 1) / FPS, 4)
        items.append({
            'state': row['state'], 'name': row['name'], 'filename': destination.name,
            'description': row['description'], 'source': provenance, 'source_frames': [start, end],
            'sha256': file_hash(destination), 'bytes': destination.stat().st_size,
            'width': CANVAS[0], 'height': CANVAS[1], 'fps': FPS, 'duration_s': duration,
            'playback': mode, 'preview': 'png' if mode == 'hold' else 'gif',
            'processing': {
                'display_dimensions_px': size, 'canvas': {'width': CANVAS[0], 'height': CANVAS[1], 'feet_y': BASELINE},
                'no_mirror': True, 'seam_rgb_delta_0_255': round(seam, 4),
                'peak_adjacent_rgb_delta_0_255': round(peak, 4),
            },
            'validation': {'all_decoded_frames_checked': len(sequence), 'alpha_mode': True},
            'full_decode_passed': True,
        })
        print(f'{row["state"]}: {mode} {len(sequence)} frames, seam {seam:.3f}, peak {peak:.3f}', flush=True)
    if len({item['sha256'] for item in items}) != len(items):
        raise ValueError('Duplicate encoded motion')
    report = {'schema_version': 3, 'character': '黑侠',
              'generated_at': datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds'),
              'items': items}
    (args.output / 'media_manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
