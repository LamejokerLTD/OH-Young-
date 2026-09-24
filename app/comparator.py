import re


class TranscriptComparator:

    def __init__(self):

        # ====================================================
        # 可能改變語意的重要差異
        # ====================================================

        self.critical_keywords = re.compile(
            r'('
            r'不|沒|無|未|是|否|'
            r'\d+|'
            r'測試|麥克風|投影機|音響|視訊|燈光|'
            r'DVI|HDMI|訊號'
            r')',
            re.IGNORECASE
        )


    # ========================================================
    # Normalize
    # ========================================================

    def _normalize_text(
        self,
        text
    ):

        if not text:
            return ''


        text = str(
            text
        ).strip()


        # 移除一般空白
        text = re.sub(
            r'\s+',
            '',
            text
        )


        return text


    # ========================================================
    # Critical Difference
    # ========================================================

    def _critical_tokens(
        self,
        text
    ):

        normalized = (
            self._normalize_text(
                text
            )
        )


        return set(
            self.critical_keywords.findall(
                normalized
            )
        )


    # ========================================================
    # Build Segment
    #
    # 核心原則：
    #
    # Whisper A = Primary Evidence
    #
    # 所以：
    # start / end / words / 其他時間資訊
    # 全部保留 A 軌原始資料。
    #
    # B 軌只負責提供第二份文字證據。
    # ========================================================

    def _build_segment(
        self,
        seg_a,
        seg_b=None
    ):

        # ----------------------------------------------------
        # 完整複製 A
        # ----------------------------------------------------

        result = dict(
            seg_a
        )


        text_a = (
            seg_a
            .get(
                'text',
                ''
            )
            .strip()
        )


        text_b = ''

        if seg_b is not None:

            text_b = (
                seg_b
                .get(
                    'text',
                    ''
                )
                .strip()
            )


        # ----------------------------------------------------
        # 確保字幕系統需要的欄位存在
        # ----------------------------------------------------

        result['text'] = (
            text_a
        )


        result['start'] = (
            seg_a.get(
                'start',
                seg_a.get(
                    'start_time',
                    0
                )
            )
        )


        result['end'] = (
            seg_a.get(
                'end',
                seg_a.get(
                    'end_time',
                    result['start']
                )
            )
        )


        # ----------------------------------------------------
        # 保留 Whisper A Word Timestamp
        # ----------------------------------------------------

        words = (
            seg_a.get(
                'words'
            )
        )


        if not isinstance(
            words,
            list
        ):

            words = []


        result['words'] = (
            words
        )


        # ----------------------------------------------------
        # UI / Comparator 資料
        # ----------------------------------------------------

        result['start_time'] = (
            result['start']
        )


        result['end_time'] = (
            result['end']
        )


        result['transcript_a'] = (
            text_a
        )


        result['transcript_b'] = (
            text_b
        )


        result['confidence_a'] = (
            seg_a.get(
                'avg_logprob'
            )
        )


        result['confidence_b'] = (
            seg_b.get(
                'avg_logprob'
            )
            if seg_b
            else None
        )


        # ----------------------------------------------------
        # B 不存在
        # ----------------------------------------------------

        if seg_b is None:

            result['status'] = (
                'LOW_CONFIDENCE'
            )


            result['difference_type'] = (
                'MISSING_SECONDARY_EVIDENCE'
            )


            return result


        # ----------------------------------------------------
        # Compare
        # ----------------------------------------------------

        normalized_a = (
            self._normalize_text(
                text_a
            )
        )


        normalized_b = (
            self._normalize_text(
                text_b
            )
        )


        # ----------------------------------------------------
        # 完全一致
        # ----------------------------------------------------

        if (
            normalized_a ==
            normalized_b
        ):

            result['status'] = (
                'MATCH'
            )


            result['difference_type'] = (
                None
            )


            return result


        # ----------------------------------------------------
        # 關鍵語意比較
        # ----------------------------------------------------

        critical_a = (
            self._critical_tokens(
                text_a
            )
        )


        critical_b = (
            self._critical_tokens(
                text_b
            )
        )


        if (
            critical_a !=
            critical_b
        ):

            difference_type = (
                'CRITICAL_DIFFERENCE'
            )

        else:

            difference_type = (
                'MINOR_DIFFERENCE'
            )


        result['status'] = (
            'LOW_CONFIDENCE'
        )


        result['difference_type'] = (
            difference_type
        )


        return result


    # ========================================================
    # Align And Compare
    # ========================================================

    def align_and_compare(
        self,
        segments_a: list,
        segments_b: list
    ) -> list:

        final_transcript = []


        # ====================================================
        # Primary Evidence = A
        #
        # 不再直接使用：
        #
        # zip(segments_a, segments_b)
        #
        # 因為 B 比 A 少一段時，
        # zip 會直接把 A 多出來的段落丟掉。
        # ====================================================

        for index, seg_a in enumerate(
            segments_a
        ):

            seg_b = (
                segments_b[index]
                if index <
                len(segments_b)
                else None
            )


            compared = (
                self._build_segment(
                    seg_a,
                    seg_b
                )
            )


            final_transcript.append(
                compared
            )


        return final_transcript