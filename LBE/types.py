from dataclasses import dataclass
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



type ResourceType = int
Entity = 0
Script = 1