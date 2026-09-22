"""Extracted PDF paper content."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Author(BaseModel):
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    orcid: str | None = None
    email: str | None = None
    affiliation_refs: list[str] = Field(default_factory=list)
    corresponding: bool = False
    bio: str | None = None
    photo_path: str | None = None


class Affiliation(BaseModel):
    id: str
    department: str | None = None
    institution: str
    city: str | None = None
    state: str | None = None
    post_code: str | None = None
    country: str | None = None


class Section(BaseModel):
    id: str
    label: str | None = None
    title: str
    level: int
    paragraphs: list[str] = Field(default_factory=list)
    equations: list[str] = Field(default_factory=list)
    figure_refs: list[str] = Field(default_factory=list)
    table_refs: list[str] = Field(default_factory=list)
    subsections: list[Section] = Field(default_factory=list)


class Reference(BaseModel):
    id: str
    number: int
    raw_text: str
    parsed: dict | None = None


class Figure(BaseModel):
    id: str
    number: int
    caption: str
    image_path: str | None = None
    suggested_filename: str = ""


class Table(BaseModel):
    id: str
    number: int
    title: str = ""
    rows: list[list[str]] = Field(default_factory=list)
    caption: str = ""


class Equation(BaseModel):
    id: str
    number: int
    latex: str
    display: bool = True


class PaperData(BaseModel):
    title: str = ""
    authors: list[Author] = Field(default_factory=list)
    affiliations: list[Affiliation] = Field(default_factory=list)
    abstract: str = ""
    keywords: list[str] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    equations: list[Equation] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    extraction_warnings: list[str] = Field(default_factory=list)
