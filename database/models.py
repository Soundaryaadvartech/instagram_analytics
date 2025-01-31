from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from database.database import Base

class SocialMedia(Base):
    __tablename__ = 'social_profile'
    __table_args__ = {"schema":"zing"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255))
    followers = Column(Integer)
    impressions = Column(Integer)
    reach = Column(Integer)
    accounts_engaged = Column(Integer)
    website_clicks = Column(Integer)
    created_ts = Column(DateTime)

    engaged_audience_ages = relationship("EngagedAudienceAge", back_populates="social_profile", cascade="all, delete-orphan")
    engaged_audience_genders = relationship("EngagedAudienceGender", back_populates="social_profile", cascade="all, delete-orphan")
    engaged_audience_locations = relationship("EngagedAudienceLocation", back_populates="social_profile", cascade="all, delete-orphan")

class EngagedAudienceAge(Base):
    __tablename__ = "social_engaged_audience_age"
    __table_args__ = {"schema": "zing"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    socialmedia_id = Column(Integer, ForeignKey("zing.social_profile.id"), nullable=False)
    age_group = Column(String(50), nullable=False)
    count = Column(Integer, nullable=False)
    created_ts = Column(DateTime, default=datetime.now(timezone.utc))

    social_profile = relationship("SocialMedia", back_populates="engaged_audience_ages")

class EngagedAudienceGender(Base):
    __tablename__ = "social_engaged_audience_gender"
    __table_args__ = {"schema": "zing"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    socialmedia_id = Column(Integer, ForeignKey("zing.social_profile.id"), nullable=False)
    gender = Column(String(10), nullable=False)
    count = Column(Integer, nullable=False)
    created_ts = Column(DateTime, default=datetime.now(timezone.utc))


    social_profile = relationship("SocialMedia", back_populates="engaged_audience_genders")

class EngagedAudienceLocation(Base):
    __tablename__ = "social_engaged_audience_location"
    __table_args__ = {"schema": "zing"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    socialmedia_id = Column(Integer, ForeignKey("zing.social_profile.id"), nullable=False)
    city = Column(String(255), nullable=False)
    count = Column(Integer, nullable=False)
    created_ts = Column(DateTime, default=datetime.now(timezone.utc))


    social_profile = relationship("SocialMedia", back_populates="engaged_audience_locations")

class Posts(Base):
    __tablename__ = "social_posts"
    __table_args__ = {"schema":"zing"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(String(255), nullable=False)
    media_type = Column(String(50))
    media_url = Column(Text)
    post_created = Column(DateTime)
    created_ts = Column(DateTime, default=datetime.now(timezone.utc))

    social_postinsights = relationship("PostInsights", back_populates="social_posts", cascade="all, delete-orphan")

class PostInsights(Base):
    __tablename__ = "social_postinsights"
    __table_args__ = {"schema":"zing"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    posts_id = Column(Integer, ForeignKey("zing.social_posts.id", ondelete="CASCADE"))
    reach = Column(Integer)
    likes = Column(Integer)
    saves = Column(Integer)
    created_ts = Column(DateTime, default=datetime.now(timezone.utc))

    social_posts = relationship("Posts", back_populates="social_postinsights")