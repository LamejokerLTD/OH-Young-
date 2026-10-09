"""Keep-segment maths and cut-list exporters (CMX3600 EDL, FCPXML 1.9, Premiere xmeml v4).

Cut lists describe the source timeline: each keep segment is one clip, placed
back to back on a new timeline. Speed and clarity are not written into the
list; they belong to the rendered file.
"""
from math import gcd
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

from app.prep.media import MediaInfo


def keep_segments(duration: float, silences, pad: float, min_keep: float = 0.1):
    """Complement of the silences, leaving `pad` seconds of silence at each edge of speech."""
    # Without any speech there is nothing to keep; padding must not turn silence into a clip.
    cursor = 0.0
    speech = 0.0
    for start, end in sorted(silences):
        speech += max(0.0, start - cursor)
        cursor = max(cursor, end)
    speech += max(0.0, duration - cursor)
    if speech < min_keep:
        return []
    removed = []
    for start, end in silences:
        cut_from, cut_to = start + pad, end - pad
        if cut_to > cut_from:
            removed.append((cut_from, cut_to))
    keep = []
    cursor = 0.0
    for cut_from, cut_to in removed:
        if cut_from > cursor:
            keep.append((cursor, cut_from))
        cursor = max(cursor, cut_to)
    if cursor < duration:
        keep.append((cursor, duration))
    return [(a, b) for a, b in keep if b - a >= min_keep]


def timeline(keep, fps):
    """Frame-accurate placement shared by every exporter, so all formats agree."""
    rate = float(fps)
    rows = []
    record = 0
    for start, end in keep:
        src_in = round(start * rate)
        src_out = round(end * rate)
        length = src_out - src_in
        rows.append({'src_in': src_in, 'src_out': src_out, 'rec_in': record, 'rec_out': record + length})
        record += length
    return rows


def _timecode(frames: int, fps) -> str:
    base = round(float(fps))
    frame = frames % base
    seconds = frames // base
    return f'{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}:{frame:02d}'


def edl(name: str, fps, keep) -> str:
    lines = [f'TITLE: {name}', 'FCM: NON-DROP FRAME', '']
    for number, row in enumerate(timeline(keep, fps), 1):
        lines.append(
            f'{number:03d}  AX       AA/V  C        '
            f'{_timecode(row["src_in"], fps)} {_timecode(row["src_out"], fps)} '
            f'{_timecode(row["rec_in"], fps)} {_timecode(row["rec_out"], fps)}'
        )
        lines.append(f'* FROM CLIP NAME:  {name}')
        lines.append('')
    return '\n'.join(lines)


def _rational(frames: int, fps) -> str:
    """FCPXML time: frames * frame duration, expressed as an exact rational."""
    numerator = frames * fps.denominator
    denominator = fps.numerator
    if numerator == 0:
        return '0s'
    divisor = gcd(numerator, denominator)
    numerator //= divisor
    denominator //= divisor
    return f'{numerator}s' if denominator == 1 else f'{numerator}/{denominator}s'


def fcpxml(name: str, source: Path, info: MediaInfo, keep) -> str:
    fps = info.fps
    rows = timeline(keep, fps)
    total = rows[-1]['rec_out'] if rows else 0
    source_frames = round(info.duration * float(fps))
    uri = source.resolve().as_uri()
    layout = 'mono' if info.audio_channels == 1 else 'stereo'
    clips = []
    for index, row in enumerate(rows, 1):
        clips.append(
            f'        <asset-clip name={quoteattr(f"{name} {index}")} ref="r2" '
            f'offset="{_rational(row["rec_in"], fps)}" start="{_rational(row["src_in"], fps)}" '
            f'duration="{_rational(row["src_out"] - row["src_in"], fps)}" format="r1" tcFormat="NDF"/>'
        )
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE fcpxml>',
        '<fcpxml version="1.9">',
        '  <resources>',
        f'    <format id="r1" frameDuration="{_rational(1, fps)}" width="{info.width}" height="{info.height}"/>',
        f'    <asset id="r2" name={quoteattr(name)} src={quoteattr(uri)} start="0s" '
        f'duration="{_rational(source_frames, fps)}" hasVideo="1" hasAudio="1" format="r1" '
        f'audioSources="1" audioChannels="{info.audio_channels}" audioRate="{info.audio_rate}"/>',
        '  </resources>',
        '  <library>',
        f'    <event name={quoteattr(name)}>',
        f'      <project name={quoteattr(name)}>',
        f'        <sequence format="r1" duration="{_rational(total, fps)}" tcStart="0s" tcFormat="NDF" '
        f'audioLayout="{layout}" audioRate="48k">',
        '          <spine>',
        *clips,
        '          </spine>',
        '        </sequence>',
        '      </project>',
        '    </event>',
        '  </library>',
        '</fcpxml>',
        '',
    ]
    return '\n'.join(lines)


def _pathurl(source: Path) -> str:
    return 'file://localhost/' + quote(source.resolve().as_posix(), safe='/')


def premiere(name: str, source: Path, info: MediaInfo, keep) -> str:
    fps = info.fps
    base = round(float(fps))
    ntsc = 'TRUE' if fps.denominator != 1 else 'FALSE'
    rows = timeline(keep, fps)
    total = rows[-1]['rec_out'] if rows else 0
    source_frames = round(info.duration * float(fps))
    url = _pathurl(source)
    channels = info.audio_channels

    def clip(row, index, track_type, channel=None, full=False):
        file_xml = ''
        if full:
            media = []
            if track_type == 'video':
                media.append(
                    f'<video><samplecharacteristics><rate><timebase>{base}</timebase><ntsc>{ntsc}</ntsc></rate>'
                    f'<width>{info.width}</width><height>{info.height}</height></samplecharacteristics></video>'
                )
            media.append(
                f'<audio><samplecharacteristics><depth>16</depth><samplerate>{info.audio_rate}</samplerate>'
                f'</samplecharacteristics><channelcount>{channels}</channelcount></audio>'
            )
            file_xml = (
                f'<file id="file-1"><name>{escape(source.name)}</name><pathurl>{escape(url)}</pathurl>'
                f'<rate><timebase>{base}</timebase><ntsc>{ntsc}</ntsc></rate>'
                f'<duration>{source_frames}</duration><media>{"".join(media)}</media></file>'
            )
        else:
            file_xml = '<file id="file-1"/>'
        source_track = (
            f'<sourcetrack><mediatype>audio</mediatype><trackindex>{channel}</trackindex></sourcetrack>'
            if track_type == 'audio' else ''
        )
        return (
            f'<clipitem id="{track_type}-{index}-{channel or 1}">'
            f'<name>{escape(name)}</name><enabled>TRUE</enabled><duration>{source_frames}</duration>'
            f'<rate><timebase>{base}</timebase><ntsc>{ntsc}</ntsc></rate>'
            f'<start>{row["rec_in"]}</start><end>{row["rec_out"]}</end>'
            f'<in>{row["src_in"]}</in><out>{row["src_out"]}</out>'
            f'{file_xml}{source_track}</clipitem>'
        )

    video_items = []
    if info.has_video:
        video_items = [clip(row, i, 'video', full=(i == 1)) for i, row in enumerate(rows, 1)]
    audio_tracks = []
    for channel in range(1, channels + 1):
        # Audio-only sources have no video track to carry the full <file> definition.
        items = [
            clip(row, i, 'audio', channel, full=(not info.has_video and channel == 1 and i == 1))
            for i, row in enumerate(rows, 1)
        ]
        audio_tracks.append(f'<track>{"".join(items)}</track>')

    video_block = ''
    if info.has_video:
        video_block = (
            '<video>'
            f'<format><samplecharacteristics><rate><timebase>{base}</timebase><ntsc>{ntsc}</ntsc></rate>'
            f'<width>{info.width}</width><height>{info.height}</height></samplecharacteristics></format>'
            f'<track>{"".join(video_items)}</track>'
            '</video>'
        )
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE xmeml>',
        '<xmeml version="4">',
        '<sequence>',
        f'<name>{escape(name)}</name>',
        f'<duration>{total}</duration>',
        f'<rate><timebase>{base}</timebase><ntsc>{ntsc}</ntsc></rate>',
        '<media>',
        video_block,
        '<audio>',
        f'<format><samplecharacteristics><depth>16</depth><samplerate>{info.audio_rate}</samplerate>'
        '</samplecharacteristics></format>',
        *audio_tracks,
        '</audio>',
        '</media>',
        '</sequence>',
        '</xmeml>',
        '',
    ]
    return '\n'.join(lines)
