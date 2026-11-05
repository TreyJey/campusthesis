from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel

import models
from database import get_db, Base, engine
from security import hash_password

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title = "CampusThesis API",
    description = "API платформы управления выпускными квалификационными работами",
    version = "0.6.0",
)

@app.get("/api/health", tags = ["Служебная информация"])
def health_check(db: Session = Depends(get_db)):
    """Проверка статуса сервера и доступа к БД"""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}

@app.get("/api/stage-types", tags=["Словари"])
def get_stage_types(db: Session = Depends(get_db)):
    """Список этапов ВКР по порядку."""
    stages = db.query(models.StageType).order_by(models.StageType.order_num).all()
    return [
        {"id": s.id, "name": s.name, "order_num": s.order_num, "default_days": s.default_days}
        for s in stages
    ]


@app.get("/api/directions", tags=["Словари"])
def get_directions(db: Session = Depends(get_db)):
    """Список направлений подготовки с кафедрами."""
    directions = db.query(models.Direction).all()
    return [
        {"id": d.id, "code": d.code, "name": d.name, "department": d.department.name}
        for d in directions
    ]

# Темы
# функция, чтобы не дублировать в двух следующих геттерах
def topic_to_dict(topic: models.Topic) -> dict:
    """Превращает тему из базы в словарь для ответа API"""
    return {
        "id": topic.id,
        "title": topic.title,
        "description": topic.description,
        "requirements": topic.requirements,
        "is_available": topic.is_available,
        "direction": {"id": topic.direction.id, "code": topic.direction.code, "name": topic.direction.name},
        "supervisor": {
            "id": topic.supervisor.id,
            "full_name": topic.supervisor.user.full_name,
            "position": topic.supervisor.position,
            "department": topic.supervisor.department.name,
        }
    }

@app.get("/api/topics", tags = ["Темы"])
def get_topics(
    direction_id: int | None = None,
    search: str | None = None,
    db: Session = Depends(get_db)
):
    """Каталог свободных тем. Есть фильтр по направлению и по словам в названии."""
    query = db.query(models.Topic).filter(models.Topic.is_available == True)
    if direction_id is not None:
        query = query.filter(models.Topic.direction_id == direction_id)
    topics = query.order_by(models.Topic.title).all()
    if search:
        # искать пришлось в питоне SQLite не умеет сравнивать русские буквы без учёта регистра
        topics = [t for t in topics if search.lower() in t.title.lower()]
    return [topic_to_dict(t) for t in topics]

@app.get("/api/topics/{topic_id}", tags=["Темы"])
def get_topic(topic_id: int, db: Session = Depends(get_db)):
    """Одна тема со всеми подробностями."""
    topic = db.get(models.Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Тема не найдена")
    return topic_to_dict(topic)

# Вход
class LoginRequest(BaseModel):
    """Тело запроса на вход."""
    login: str
    password: str


@app.post("/api/login", tags=["Вход"])
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """Проверяет логин и пароль. Возвращает информацию пользователя."""
    user = db.query(models.User).filter(models.User.login == data.login).first()
    if user is None or user.password_hash != hash_password(data.password):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    if user.role.name == "student":
        profile = db.query(models.StudentProfile).filter(models.StudentProfile.user_id == user.id).first()
    else:
        profile = db.query(models.SupervisorProfile).filter(models.SupervisorProfile.user_id == user.id).first()

    return {
        "user_id": user.id,
        "login": user.login,
        "full_name": user.full_name,
        "role": user.role.name,
        "profile_id": profile.id,
    }                                   # переделать на JWT токен если будет время ! ! !

# Заявки на темы
class TopicRequestCreate(BaseModel):
    """Тело запроса на подачу заявки."""
    student_id: int
    topic_id: int
    message: str | None = None


@app.post("/api/topic-requests", status_code=201, tags=["Заявки"])
def create_topic_request(data: TopicRequestCreate, db: Session = Depends(get_db)):
    """Студент подаёт заявку руководителю на выбранную тему."""
    student = db.get(models.StudentProfile, data.student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Студент не найден")

    topic = db.get(models.Topic, data.topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Тема не найдена")
    if not topic.is_available:
        raise HTTPException(status_code=400, detail="Тема уже закреплена за другим студентом")

    has_thesis = db.query(models.Thesis).filter(models.Thesis.student_id == student.id).first()
    if has_thesis is not None:
        raise HTTPException(status_code=400, detail="У студента уже есть закреплённая тема")

    duplicate = (
        db.query(models.TopicRequest)
        .filter(
            models.TopicRequest.student_id == student.id,
            models.TopicRequest.topic_id == topic.id,
            models.TopicRequest.status == "pending",
        )
        .first()
    )
    if duplicate is not None:
        raise HTTPException(status_code=400, detail="Заявка на эту тему уже подана и ждёт решения")

    request = models.TopicRequest(student_id=student.id, topic_id=topic.id, message=data.message)
    db.add(request)
    db.commit()
    db.refresh(request)

    return {
        "id": request.id,
        "topic_id": request.topic_id,
        "student_id": request.student_id,
        "message": request.message,
        "status": request.status,
        "created_at": request.created_at,
    }