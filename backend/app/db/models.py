from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, JSON, Enum, Text
from sqlalchemy.sql import func
from app.db.database import Base
import enum
from datetime import datetime

class DownloadStatus(str, enum.Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    ARCHIVED = "archived" # Local archive successful
    OUTDATED = "outdated" # Has newer version

class DownloadMode(str, enum.Enum):
    ARCHIVE = "archive"
    NATIVE_CRAWL = "native_crawl"  # Native Python crawler (supports cancellation)

class Gallery(Base):
    __tablename__ = "galleries"

    gid = Column(Integer, primary_key=True, index=True)
    token = Column(String, primary_key=True) # Composite key just in case, or just index
    
    title = Column(String, index=True)
    title_jpn = Column(String, nullable=True)
    category = Column(String, index=True)
    uploader = Column(String, index=True)
    posted = Column(DateTime)
    filecount = Column(Integer)
    rating = Column(Float)
    tags = Column(JSON) # List of tags
    
    # Download Info
    status = Column(String, default=DownloadStatus.PENDING)
    download_mode = Column(String, default=DownloadMode.ARCHIVE)
    priority = Column(Integer, default=0) # Higher = sooner
    download_path = Column(String, nullable=True) # Path to .cbz
    downloaded_at = Column(DateTime, nullable=True)
    favorited_at = Column(DateTime, nullable=True)  # When added to favorites (from E-H page)
    favcat = Column(Integer, nullable=True)
    requested_quality = Column(String, nullable=True)
    resolved_quality = Column(String, nullable=True)

    # Update Tracking
    parent_gid = Column(String, nullable=True)
    replaced_by = Column(String, nullable=True) # "newer version" URL or GID
    last_checked = Column(DateTime, default=datetime.utcnow)
    
    # Error tracking
    error_msg = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    
    # Download logs (JSON array of log entries)
    download_logs = Column(Text, nullable=True)  # JSON serialized log entries

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    telegram_id = Column(Integer, nullable=True, unique=True)

class AppConfig(Base):
    """
    Store internal runtime state that should persist across restarts.
    User-editable configuration now lives in config.yaml.
    """
    __tablename__ = "app_config"
    
    key = Column(String, primary_key=True)
    value = Column(String) # JSON serialized value
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
