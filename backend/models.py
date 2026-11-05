from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database import Base

# Словари

class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(20), nullable=False, unique=True) #student/supervisor
    
class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, unique=True)

class Direction(Base):
    __tablename__ = "directions"

    id = Column(Integer, primary_key=True)
    code = Column(String(20), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)

    department = relationship("Department")

class StageType(Base):
    __tablename__ = "stage_types"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    order_num = Column(Integer, nullable=False, unique=True)
    default_days = Column(Integer, nullable=False)

# Пользователи

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    login = Column(String(50), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(200), nullable=False)
    email = Column(String(200))
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    role = relationship("Role")


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    direction_id = Column(Integer, ForeignKey("directions.id"), nullable=False)
    group_name = Column(String(30), nullable=False)
    course = Column(Integer, nullable=False)

    user = relationship("User")
    direction = relationship("Direction")


class SupervisorProfile(Base):
    __tablename__ = "supervisor_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    position = Column(String(100), nullable=False)
    max_students = Column(Integer, nullable=False, default=5)

    user = relationship("User")
    department = relationship("Department")

# Темы и заявки

class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True)
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=False)
    requirements = Column(Text)
    supervisor_id = Column(Integer, ForeignKey("supervisor_profiles.id"), nullable=False)
    direction_id = Column(Integer, ForeignKey("directions.id"), nullable=False)
    is_available = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    supervisor = relationship("SupervisorProfile")
    direction = relationship("Direction")


class TopicRequest(Base):
    __tablename__ = "topic_requests"

    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("student_profiles.id"), nullable=False)
    message = Column(Text)
    status = Column(String(20), nullable=False, default="pending")  # pending / approved / rejected
    supervisor_comment = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    decided_at = Column(DateTime)

    topic = relationship("Topic")
    student = relationship("StudentProfile")

# ВКР и этапы

class Thesis(Base):
    __tablename__ = "theses"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("student_profiles.id"), nullable=False, unique=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=False, unique=True)
    supervisor_id = Column(Integer, ForeignKey("supervisor_profiles.id"), nullable=False)
    status = Column(String(20), nullable=False, default="in_progress")  # in_progress / defended
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    student = relationship("StudentProfile")
    topic = relationship("Topic")
    supervisor = relationship("SupervisorProfile")
    stages = relationship("ThesisStage", order_by="ThesisStage.stage_type_id")


class ThesisStage(Base):
    __tablename__ = "thesis_stages"

    id = Column(Integer, primary_key=True)
    thesis_id = Column(Integer, ForeignKey("theses.id"), nullable=False)
    stage_type_id = Column(Integer, ForeignKey("stage_types.id"), nullable=False)
    deadline = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="locked") # locked / open / submitted / revision / approved
    submitted_at = Column(DateTime)
    approved_at = Column(DateTime)

    stage_type = relationship("StageType")
    files = relationship("StageFile")
    reviews = relationship("Review")

class StageFile(Base):
    __tablename__ = "stage_files"

    id = Column(Integer, primary_key=True)
    thesis_stage_id = Column(Integer, ForeignKey("thesis_stages.id"), nullable=False)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    original_name = Column(String(255), nullable=False)
    stored_path = Column(String(500), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    uploaded_at = Column(DateTime, nullable=False, default=datetime.now)


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    thesis_stage_id = Column(Integer, ForeignKey("thesis_stages.id"), nullable=False)
    supervisor_id = Column(Integer, ForeignKey("supervisor_profiles.id"), nullable=False)
    decision = Column(String(20), nullable=False)  # approved / revision
    comment = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


# Уведомленич

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String(30), nullable=False)  # deadline / comment / status
    text = Column(String(500), nullable=False)
    link = Column(String(300))
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)