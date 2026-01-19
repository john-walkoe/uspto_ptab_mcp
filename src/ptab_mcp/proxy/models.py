"""
Pydantic models for PTAB proxy server.

Models for document registration with PFW centralized proxy.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
import re


class PTABDocumentRegistration(BaseModel):
    """Model for registering PTAB documents with centralized proxy."""

    source: str = Field(..., description="Must be 'ptab'")
    identifier: str = Field(..., description="Trial/appeal/interference number")
    identifier_type: str = Field(..., description="One of: trial, appeal, interference")
    document_identifier: str = Field(..., description="Document ID from documentBag")
    download_url: str = Field(..., description="USPTO API download URL (HTTPS)")
    api_key: str = Field(..., description="USPTO API key for fetching document")
    patent_number: Optional[str] = Field(None, description="Patent number if available")
    enhanced_filename: Optional[str] = Field(
        None,
        description="Enhanced human-readable filename",
        max_length=255
    )

    @field_validator('source')
    @classmethod
    def validate_source(cls, v):
        """Ensure source is 'ptab'"""
        if v != 'ptab':
            raise ValueError("source must be 'ptab'")
        return v

    @field_validator('identifier_type')
    @classmethod
    def validate_identifier_type(cls, v):
        """Validate identifier type"""
        valid_types = ['trial', 'appeal', 'interference']
        if v not in valid_types:
            raise ValueError(f"identifier_type must be one of: {', '.join(valid_types)}")
        return v

    @field_validator('download_url')
    @classmethod
    def validate_download_url(cls, v):
        """Ensure download URL is from USPTO domain"""
        if not v.startswith('https://'):
            raise ValueError("download_url must use HTTPS")
        if 'uspto.gov' not in v:
            raise ValueError("download_url must be from uspto.gov domain")
        return v

    @field_validator('enhanced_filename')
    @classmethod
    def validate_filename(cls, v):
        """Validate enhanced filename format"""
        if v is None:
            return v

        if not v.endswith('.pdf'):
            raise ValueError("enhanced_filename must end with .pdf")

        if len(v) > 255:
            raise ValueError("enhanced_filename too long (max 255 chars)")

        # Only allow safe characters: uppercase, digits, underscore, hyphen, dot
        if not re.match(r'^[A-Z0-9_.-]+\.pdf$', v):
            raise ValueError("enhanced_filename contains invalid characters (use uppercase, digits, underscore, hyphen, dot only)")

        return v


class DocumentDownloadResponse(BaseModel):
    """Response model for document download requests."""

    success: bool
    download_url: str
    proxy_info: dict
    document_info: dict
    error: Optional[str] = None
