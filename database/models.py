from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from database.database import Base

class SocialMedia(Base):
    __tablename__ = 'socialmedia'
    __table_args__ = {"schema":"zing"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255))
    followers = Column(Integer)
    impressions = Column(Integer)
    reach = Column(Integer)
    accounts_engaged = Column(Integer)
    website_clicks = Column(Integer)
    created_ts = Column(DateTime)

# class Posts(Base):
#     __tablename__ = "posts"
#     __tableargs__ = {"schema":"zing"}

#     id = Column(Integer, primary_key=True, autoincrement=True)
#     post_id = Column(String(255), nullable=False)
#     media_type = Column(String(50))
#     media_url = Column(Text)
#     post_created = Column(DateTime)

#     insights = relationship("PostInsights", back_populates="posts", cascade="all, delete-orphan")

# class PostInsights(Base):
#     __tablename__ = "postinsights"
#     __table_args__ = {"schema":"zing"}

#     id = Column(Integer, primary_key=True, autoincrement=True)
#     posts_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"))
#     reach = Column(Integer)
#     likes = Column(Integer)
#     saves = Column(Integer)

#     posts = relationship("Posts", back_populates="insights")