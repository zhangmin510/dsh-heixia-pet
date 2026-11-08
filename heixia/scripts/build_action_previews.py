#!/usr/bin/env python3
"""Render looping GIFs for video actions and PNGs for static photo poses.

Requires Python 3.9+ and FFmpeg/ffprobe with libvpx-vp9. All paths default to
this package's pet/ directory and can be overridden with command arguments.
No original photo, original video or screenshot is read or distributed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PACKAGE = Path(__file__).resolve().parent.parent
BACKGROUND = '#eff3ed'
MARGIN = 16
FRAME_INDEX = {
    'idle': 0, 'working': 0, 'belly_rest': 0,
    'thinking': 13, 'waiting': 11, 'success': 14, 'sleep': 14,
    'pet': 15, 'play': 11, 'wash_face': 12, 'tail_sway': 15,
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_png(path, ffprobe):
    result = subprocess.run(
        [ffprobe, '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height,pix_fmt', '-of', 'json', str(path)],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return json.loads(result.stdout)['streams'][0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=PACKAGE / 'pet/media_manifest.json')
    parser.add_argument('--media-root', type=Path, default=PACKAGE / 'pet/heixia-animation')
    parser.add_argument('--output-dir', type=Path, default=PACKAGE / 'pet/action-previews')
    parser.add_argument('--copy-to', type=Path, help='Optional second preview directory; GIF, PNG and JSON bytes stay identical')
    args = parser.parse_args()
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        parser.error('FFmpeg and ffprobe are required')
    manifest = json.loads(args.manifest.resolve().read_text(encoding='utf-8'))
    rows = manifest['items']
    if not rows:
        parser.error('Manifest has no action items')
    media_root = args.media_root.resolve()
    output_dir = args.output_dir.resolve()
    copy_dir = args.copy_to.resolve() if args.copy_to else None
    states, inputs = set(), []
    # Validate every source before writing preview files.
    for row in rows:
        state = row['state']
        if not isinstance(state, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', state):
            raise ValueError(f'Expected a safe English state filename: {state!r}')
        if state.casefold() in states:
            raise ValueError(f'Duplicate preview state: {state}')
        states.add(state.casefold())
        source = media_root / Path(row['filename']).name
        if source.suffix.lower() != '.webm' or not source.is_file():
            raise ValueError(f'Finished WebM missing for {state}')
        expected_sha = row['sha256']
        if sha256(source) != expected_sha:
            raise ValueError(f'Source WebM hash mismatch for {state}')
        inputs.append((row, source, expected_sha, source.stat().st_mtime_ns))
    output_dir.mkdir(parents=True, exist_ok=True)
    if copy_dir:
        copy_dir.mkdir(parents=True, exist_ok=True)
    previews = []
    for row, source, expected_sha, original_mtime in inputs:
        state = row['state']
        processing = row.get('processing', {})
        dimensions = row.get('display_dimensions_px', processing.get('display_dimensions_px'))
        canvas = row.get('canvas', processing.get('canvas'))
        if dimensions is None or canvas is None:
            raise ValueError(f'Canvas/display dimensions missing for {state}')
        width, height = map(int, dimensions)
        canvas_width, canvas_height = int(canvas['width']), int(canvas['height'])
        feet_y = int(canvas['feet_y'])
        if not (0 < width <= canvas_width and 0 < height <= feet_y <= canvas_height):
            raise ValueError(f'Invalid canvas/display geometry for {state}')
        left, top = (canvas_width - width) // 2, feet_y - height
        x0, y0 = max(0, left - MARGIN), max(0, top - MARGIN)
        x1, y1 = min(canvas_width, left + width + MARGIN), min(canvas_height, feet_y + MARGIN)
        crop_width, crop_height = x1 - x0, y1 - y0
        validation = row.get('alpha_validation', row.get('validation', {}))
        frame_count = validation.get('all_decoded_frames_checked')
        frame = (int(frame_count) // 2 if frame_count else 0) if 'preview' in row else (
            FRAME_INDEX.get(state, int(frame_count) // 2 if frame_count else 0))
        if frame_count is not None and not 0 <= frame < int(frame_count):
            raise ValueError(f'Preview frame outside the verified video for {state}')
        if row.get('preview') == 'gif' or ('preview' not in row and 'video_id' in row.get('source', {})):
            target = output_dir / (state + '.gif')
            temporary = output_dir / (state + '.partial.gif')
            # Both layers use the source timestamps, so all source frames reach
            # the GIF. The shared palette keeps the background and fur stable.
            graph = (
                f'[0:v]format=rgba,crop={crop_width}:{crop_height}:{x0}:{y0},split[cat][ground];'
                '[ground]lutrgb=r=239:g=243:b=237,format=rgb24[bg];'
                '[bg][cat]overlay=shortest=1:format=auto,format=rgb24,split[frames][colors];'
                '[colors]palettegen=stats_mode=full[palette];'
                '[frames][palette]paletteuse=dither=sierra2_4a:diff_mode=rectangle[out]'
            )
            subprocess.run(
                [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
                 '-c:v', 'libvpx-vp9', '-i', str(source),
                 '-filter_complex_threads', '1', '-filter_complex', graph,
                 '-map', '[out]', '-loop', '0', '-y', str(temporary)], check=True,
            )
            probe = json.loads(subprocess.run(
                [ffprobe, '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                 '-show_entries', 'stream=width,height,nb_read_frames:format=duration',
                 '-of', 'json', str(temporary)], check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            ).stdout)
            stream = probe['streams'][0]
            frames = int(stream['nb_read_frames'])
            duration = float(probe['format']['duration'])
            source_duration = float(row['duration_s'])
            if frames != frame_count or frames < 2:
                raise ValueError(f'GIF lost source frames for {state}: {frames}/{frame_count}')
            if abs(duration - source_duration) > .03:
                raise ValueError(f'GIF timing changed beyond 10ms format quantization: {state}')
            if b'NETSCAPE2.0\x03\x01\x00\x00\x00' not in temporary.read_bytes():
                raise ValueError(f'GIF does not declare infinite looping: {state}')
            temporary.replace(target)
            preview_sha = sha256(target)
            if copy_dir and copy_dir != output_dir:
                shutil.copyfile(target, copy_dir / target.name)
                if sha256(copy_dir / target.name) != preview_sha:
                    raise ValueError(f'Copied GIF hash mismatch for {state}')
            previews.append({
                'state': state, 'name': row['name'], 'source_webm': source.name,
                'source_sha256': expected_sha, 'media_type': 'video', 'format': 'gif',
                'filename': target.name, 'sha256': preview_sha, 'bytes': target.stat().st_size,
                'width': stream['width'], 'height': stream['height'],
                'frame_count': frames, 'source_frame_count': frame_count,
                'duration_s': duration, 'source_duration_s': source_duration, 'loop': 0,
                'timing_quantization_s': round(duration - source_duration, 6),
                'crop_px': [x0, y0, crop_width, crop_height],
                'display_dimensions_px': [width, height], 'feet_y': feet_y,
                'margin_px': MARGIN, 'background': BACKGROUND,
                'source_sha_and_mtime_preserved': True,
            })
            print(f'{state}: GIF {frames} frames, {duration:.3f}s, {target.stat().st_size} bytes', flush=True)
            continue
        if row.get('preview') != 'png' and 'photo_id' not in row.get('source', {}):
            raise ValueError(f'Unknown photo/video source for {state}')
        target = output_dir / (state + '.png')
        temporary = output_dir / (state + '.partial.png')
        # Decode alpha explicitly. Reset the chosen frame to t=0 before overlay
        # so a later representative frame never yields an empty background.
        graph = (
            f"[0:v]select='eq(n,{frame})',setpts=PTS-STARTPTS,format=rgba,"
            f'crop={crop_width}:{crop_height}:{x0}:{y0}[cat];'
            '[1:v]format=rgb24[bg];'
            '[bg][cat]overlay=shortest=1:format=auto,format=rgb24[out]'
        )
        if 'preview' in row or not target.exists():
            subprocess.run(
                [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
                 '-c:v', 'libvpx-vp9', '-i', str(source),
                 '-f', 'lavfi', '-i', f'color=c=0x{BACKGROUND[1:]}:s={crop_width}x{crop_height}:r=1,format=rgb24',
                 '-filter_complex_threads', '1', '-filter_complex', graph,
                 '-map', '[out]', '-frames:v', '1', '-c:v', 'png', '-y', str(temporary)],
                check=True,
            )
            if not temporary.is_file():
                raise ValueError(f'No preview frame was rendered for {state}')
            temporary.replace(target)
        info = inspect_png(target, ffprobe)
        if [info['width'], info['height']] != [crop_width, crop_height]:
            raise ValueError(f'Preview dimensions mismatch for {state}')
        corner = subprocess.run(
            [ffmpeg, '-v', 'error', '-i', str(target), '-vf', 'crop=1:1:0:0',
             '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout
        if corner != bytes.fromhex(BACKGROUND[1:]):
            raise ValueError(f'Background RGB changed during rendering {state}')
        preview_sha = sha256(target)
        if copy_dir and copy_dir != output_dir:
            copy_target = copy_dir / target.name
            if not copy_target.exists() or sha256(copy_target) != preview_sha:
                shutil.copyfile(target, copy_target)
            if sha256(copy_target) != preview_sha:
                raise ValueError(f'Copied preview hash mismatch for {state}')
        if sha256(source) != expected_sha or source.stat().st_mtime_ns != original_mtime:
            raise ValueError(f'Source WebM changed while rendering {state}')
        previews.append({
            'state': state, 'name': row['name'], 'source_webm': source.name,
            'source_sha256': expected_sha, 'frame_index': frame,
            'media_type': 'static' if 'preview' in row else 'photo', 'format': 'png', 'frame_count': 1,
            'filename': target.name, 'sha256': preview_sha, 'bytes': target.stat().st_size,
            'width': crop_width, 'height': crop_height, 'crop_px': [x0, y0, crop_width, crop_height],
            'display_dimensions_px': [width, height], 'feet_y': feet_y,
            'margin_px': MARGIN, 'background': BACKGROUND,
            'source_sha_and_mtime_preserved': True,
        })
        print(f'{state}: frame {frame}, {crop_width}x{crop_height}, {target.stat().st_size} bytes')
    for row, source, expected_sha, original_mtime in inputs:
        if sha256(source) != expected_sha or source.stat().st_mtime_ns != original_mtime:
            raise ValueError(f'Source WebM changed before completion: {row["state"]}')
    report = {
        'schema_version': 2,
        'generated_at': datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds'),
        'method': 'Finished WebM decoded using libvpx-vp9; GIF for video actions, PNG for held poses; shared clean background and fixed crop',
        'count': len(previews), 'original_media_untouched': True,
        'gif_count': sum(r['format'] == 'gif' for r in previews),
        'png_count': sum(r['format'] == 'png' for r in previews),
        'timing_note': 'GIF delays are quantized to 10ms; source frame order/count retained.',
        'background': BACKGROUND, 'margin_px': MARGIN, 'items': previews,
    }
    encoded = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if b'/Users/' in encoded or b'/private/' in encoded:
        raise ValueError('Private path in public preview manifest')
    (output_dir / 'preview_manifest.json').write_bytes(encoded)
    if copy_dir and copy_dir != output_dir:
        (copy_dir / 'preview_manifest.json').write_bytes(encoded)
    print(f'Created {len(previews)} previews; source WebM SHA-256 and mtimes preserved')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
