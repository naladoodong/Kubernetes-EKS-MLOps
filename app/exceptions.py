class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


class DatasetNotFound(AppError):
    def __init__(self):
        super().__init__(404, "DATASET_NOT_FOUND", "Dataset was not found.")


class DatasetNameConflict(AppError):
    def __init__(self):
        super().__init__(409, "DATASET_NAME_CONFLICT", "An active Dataset with this name already exists.")
