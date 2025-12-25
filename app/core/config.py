from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Participation Architecture"
    VERSION: str = "0.1.0"
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:password@db:5432/participation_arch"
    
    # External APIs
    OPENAI_API_KEY: str = "sk-placeholder"
    SNAPSHOT_GRAPHQL_URL: str = "https://hub.snapshot.org/graphql"

    class Config:
        env_file = ".env"

settings = Settings()