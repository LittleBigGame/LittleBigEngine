from dataclasses import dataclass, field
from typing import Annotated, Any


type StorageID = Annotated[bytes, 16]
type RuntimeID = int


@dataclass(slots=True)
class Error(Exception):
    message: str
    description: str
    data: Any
    code: int = -1


StorageIDNotFoundOnMemoryError = 1
StorageIDNotFoundOnDiskError = 2
RuntimeIDNotFoundOnMemoryError = 3
RuntimeIDNotFoundOnDiskError = 4
FolderNotFoundOnDiskError = 5
FolderNotFoundOnMemoryError = 6
InvalidResourceDataError = 7
ResourceAlreadyExistsOnDiskError = 8
FailedToSaveResourceOnDiskError = 9
EntityTypeMismatchError = 10
ComponentNotFoundOnEntityError = 11
MissingComponentRequirementError = 12
InvalidProjectManifestError = 13
BrokenReferenceError = 14
ProjectLoadError = 15


type ResourceType = int
Entity = 0
Script = 1


@dataclass(slots=True)
class BrokenReference:
    source_storage_id: StorageID
    target_storage_id: StorageID
    reference_type: str  # "dependency", "child", "component_ref", or "root"
    details: str = ""


@dataclass(slots=True)
class ProjectManifest:
    name: str = "Untitled Project"
    format_version: int = 1
    root_entity_ids: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
