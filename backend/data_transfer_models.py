from pydantic import BaseModel, ConfigDict, Field, field_validator


class Mappings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    columns: dict[str, dict[str, str]] = Field(default_factory=dict, max_length=6)
    references: dict[str, str] = Field(default_factory=dict, max_length=100_000)

    @field_validator("columns", "references")
    @classmethod
    def bounded_mapping(cls, value):
        for key, item in value.items():
            pairs = item.items() if isinstance(item, dict) else [(key, item)]
            if len(key) > 250 or (isinstance(item, dict) and len(item) > 100):
                raise ValueError("Feldzuordnung ist zu groß.")
            for name, target in pairs:
                if not name or not target or max(len(name), len(target)) > 250 or any(ord(c) < 32 for c in name + target):
                    raise ValueError("Ungültige Feld- oder Referenzzuordnung.")
        return value


class BatchOptions(Mappings):
    source_system: str = Field(min_length=1, max_length=100)
    portfolio_id: str | None = None

    @field_validator("source_system")
    @classmethod
    def source_name(cls, value):
        if any(ord(char) < 32 for char in value):
            raise ValueError("Unzulässiges Steuerzeichen im Quellsystem.")
        return value


class PreviewChange(Mappings):
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=16, max_length=100)


class CommitImport(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=16, max_length=100)
    acknowledge_warnings: bool = False
    reason: str = Field(min_length=10, max_length=2000)


class CreatePortabilityExport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=16, max_length=100)
