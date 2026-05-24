from datetime import datetime

from pydantic import BaseModel, model_validator


class ReplayTesterSessionIn(BaseModel):
    sport_id: int
    season_year: int
    week_number: int
    task_text: str
    task_completed: bool = False
    time_to_complete_seconds: int | None = None
    bug_found: bool = False
    bug_severity: int | None = None  # 1..4 valid; validated when bug_found
    feature_gap_text: str | None = None
    screenshot_url: str | None = None

    @model_validator(mode="after")
    def _validate_bug_severity(self) -> "ReplayTesterSessionIn":
        if self.bug_found:
            if self.bug_severity is None:
                raise ValueError("bug_severity is required when bug_found is true")
            if self.bug_severity < 1 or self.bug_severity > 4:
                raise ValueError("bug_severity must be between 1 and 4")
        elif self.bug_severity is not None:
            if self.bug_severity < 1 or self.bug_severity > 4:
                raise ValueError("bug_severity must be between 1 and 4")
        return self


class ReplayTesterSessionOut(ReplayTesterSessionIn):
    id: int
    user_id: int
    created_at: datetime

    model_config = {"from_attributes": True}
