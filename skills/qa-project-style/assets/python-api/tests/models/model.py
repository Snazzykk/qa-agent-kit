from pydantic import BaseModel, Field


class DemoItemCreateSchema(BaseModel):
    name: str = Field(min_length=1)


class DemoItemResponseSchema(BaseModel):
    id: str
    name: str
