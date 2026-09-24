import json
import re


# ============================================================
# Timestamp
# ============================================================

def stamp(
    seconds,
    separator=','
):

    value = max(
        0,
        round(
            seconds * 1000
        )
    )


    hours, value = divmod(
        value,
        3600000
    )


    minutes, value = divmod(
        value,
        60000
    )


    secs, ms = divmod(
        value,
        1000
    )


    return (
        f'{hours:02}:'
        f'{minutes:02}:'
        f'{secs:02}'
        f'{separator}'
        f'{ms:03}'
    )


# ============================================================
# Subtitle Generator
# ============================================================

def subtitles(
    segments,
    convert=lambda x: x
):

    result = []


    for seg in segments:

        # ====================================================
        # Basic Segment Data
        # ====================================================

        text = str(
            seg.get(
                'text',
                ''
            )
            or ''
        )


        start = seg.get(
            'start',
            seg.get(
                'start_time',
                0
            )
        )


        end = seg.get(
            'end',
            seg.get(
                'end_time',
                start
            )
        )


        words = seg.get(
            'words',
            []
        )


        # ====================================================
        # words 資料不存在
        #
        # 直接使用 Segment 級時間碼。
        #
        # 這樣即使未來 Comparator / Pipeline B
        # 沒有 Word Timestamp，
        # 也不會讓整個工作失敗。
        # ====================================================

        if not isinstance(
            words,
            list
        ):

            words = []


        if not words:

            converted = (
                convert(
                    text
                )
            )


            if (
                end > start
                and
                converted.strip()
            ):

                result.append(
                    dict(
                        start=start,
                        end=end,
                        text=converted
                    )
                )


            continue


        # ====================================================
        # Validate Word Timestamp
        # ====================================================

        valid_words = True


        for word in words:

            if not isinstance(
                word,
                dict
            ):

                valid_words = False

                break


            if (
                'start' not in word
                or
                'end' not in word
                or
                'word' not in word
            ):

                valid_words = False

                break


            if (
                word['end'] <=
                word['start']
            ):

                valid_words = False

                break


        # ====================================================
        # Word Text Check
        # ====================================================

        if valid_words:

            word_text = ''.join(
                str(
                    word.get(
                        'word',
                        ''
                    )
                )
                for word in words
            ).strip()


            if (
                word_text !=
                text.strip()
            ):

                valid_words = False


        # ====================================================
        # Invalid Words → Segment Fallback
        # ====================================================

        if not valid_words:

            converted = (
                convert(
                    text
                )
            )


            if (
                end > start
                and
                converted.strip()
            ):

                result.append(
                    dict(
                        start=start,
                        end=end,
                        text=converted
                    )
                )


            continue


        # ====================================================
        # Word-Level Subtitle Splitting
        # ====================================================

        group = []


        for word in words:

            if group:

                pause_too_long = (
                    word['start']
                    -
                    group[-1]['end']
                    >=
                    .65
                )


                text_too_long = (
                    len(
                        ''.join(
                            str(
                                w['word']
                            )
                            for w in group
                        )
                    )
                    >=
                    38
                )


                punctuation_break = (
                    (
                        group[-1]['end']
                        -
                        group[0]['start']
                    )
                    >=
                    1.2
                    and
                    re.search(
                        r'[，。！？.!?、；;]$',
                        str(
                            group[-1]['word']
                        )
                    )
                )


                if (
                    pause_too_long
                    or
                    text_too_long
                    or
                    punctuation_break
                ):

                    grouped_text = (
                        ''.join(
                            str(
                                w['word']
                            )
                            for w in group
                        )
                    )


                    converted = (
                        convert(
                            grouped_text
                        )
                    )


                    if (
                        group[-1]['end']
                        >
                        group[0]['start']
                        and
                        converted.strip()
                    ):

                        result.append(
                            dict(
                                start=(
                                    group[0][
                                        'start'
                                    ]
                                ),
                                end=(
                                    group[-1][
                                        'end'
                                    ]
                                ),
                                text=converted
                            )
                        )


                    group = []


            group.append(
                word
            )


        # ====================================================
        # Remaining Words
        # ====================================================

        if group:

            grouped_text = (
                ''.join(
                    str(
                        w['word']
                    )
                    for w in group
                )
            )


            converted = (
                convert(
                    grouped_text
                )
            )


            if (
                group[-1]['end']
                >
                group[0]['start']
                and
                converted.strip()
            ):

                result.append(
                    dict(
                        start=(
                            group[0][
                                'start'
                            ]
                        ),
                        end=(
                            group[-1][
                                'end'
                            ]
                        ),
                        text=converted
                    )
                )


    # ========================================================
    # Final Validation
    # ========================================================

    return [
        row
        for row in result
        if (
            row['end'] >
            row['start']
            and
            row['text'].strip()
        )
    ]


# ============================================================
# Export
# ============================================================

def export(
    result,
    directory
):

    cues = result[
        'subtitles'
    ]


    # ========================================================
    # SRT
    # ========================================================

    srt = (
        '\n\n'.join(

            f"{i}\n"
            f"{stamp(c['start'])} --> "
            f"{stamp(c['end'])}\n"
            f"{c['text'].strip()}"

            for i, c
            in enumerate(
                cues,
                1
            )
        )
        +
        '\n'
    )


    # ========================================================
    # VTT
    # ========================================================

    vtt = (
        'WEBVTT\n\n'
        +
        '\n\n'.join(

            f"{stamp(c['start'], '.')} --> "
            f"{stamp(c['end'], '.')}\n"
            f"{c['text'].strip()}"

            for c in cues
        )
        +
        '\n'
    )


    # ========================================================
    # TXT
    # ========================================================

    plain = (
        '\n\n'.join(
            c['text'].strip()
            for c in cues
        )
    )


    # ========================================================
    # Timed TXT
    # ========================================================

    timed = (
        '\n\n'.join(

            f"["
            f"{stamp(c['start'], '.')} - "
            f"{stamp(c['end'], '.')}"
            f"]\n"
            f"{c['text'].strip()}"

            for c in cues
        )
    )


    # ========================================================
    # JSON
    # ========================================================

    json_content = (
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2
        )
    )


    # ========================================================
    # Write Files
    # ========================================================

    files = {
        'srt':
            srt,

        'vtt':
            vtt,

        'txt':
            plain,

        'timed.txt':
            timed,

        'json':
            json_content
    }


    for name, content in files.items():

        path = (
            directory /
            (
                'transcript.'
                +
                name
            )
        )


        path.write_text(
            content,
            encoding='utf-8'
        )