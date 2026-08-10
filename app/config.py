from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://argmax:argmax-local-only@localhost:5432/argmax"
    model_config = SettingsConfigDict(env_file=None)


settings = Settings()
