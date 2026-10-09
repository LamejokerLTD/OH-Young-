"""Validated processing parameters. Anything outside these bounds is rejected with 422."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Clarity(BaseModel):
    model_config = ConfigDict(extra='forbid')

    denoise: Literal['off', 'light', 'strong'] = 'off'
    eq: bool = False        # high-pass + mud cut + presence boost
    balance: bool = False   # gentle compression to even out volume
    loudness: bool = False  # EBU R128 loudness normalisation (single pass)


class Silence(BaseModel):
    model_config = ConfigDict(extra='forbid')

    enabled: bool = False
    threshold_db: float = Field(-35.0, ge=-60.0, le=-15.0)
    min_silence: float = Field(0.8, ge=0.2, le=10.0)   # shortest gap that counts as silence (s)
    pad: float = Field(0.15, ge=0.0, le=2.0)           # silence kept on each side of speech (s)


class Transcript(BaseModel):
    model_config = ConfigDict(extra='forbid')

    enabled: bool = False
    language: Literal['auto', 'zh', 'en', 'ja', 'ko'] = 'zh'
    traditional: bool = True


class Params(BaseModel):
    model_config = ConfigDict(extra='forbid')

    speed: float = Field(1.0, ge=1.0, le=2.0)   # pitch-preserving; above 2.0 is not offered
    clarity: Clarity = Field(default_factory=Clarity)
    silence: Silence = Field(default_factory=Silence)
    transcript: Transcript = Field(default_factory=Transcript)

    @property
    def needs_render(self) -> bool:
        clarity = self.clarity
        return (
            self.speed != 1.0
            or self.silence.enabled
            or clarity.denoise != 'off'
            or clarity.eq
            or clarity.balance
            or clarity.loudness
        )


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    inputs: list[str] = Field(min_length=1, max_length=20)
    params: Params = Field(default_factory=Params)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    input: str = Field(min_length=1, max_length=500)
    params: Params = Field(default_factory=Params)


PREVIEW_SECONDS = 30
