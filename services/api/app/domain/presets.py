from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class DownloadPreset:
    """A named, reusable set of download options a user can apply in one tap
    instead of reselecting quality and performance knobs every time -- e.g.
    "Reel -> best MP4" or "Audio only, fast".

    Deliberately holds only options that are stable across URLs: a specific
    format_id comes from analyzing one particular URL, so it is never part of
    a saved preset.
    """

    id: str
    name: str
    preset: str
    concurrent_fragments: int
    retries: int
    use_aria2: bool
    created_at: datetime
