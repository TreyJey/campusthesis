from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

import models
from database import get_db, Base, engine

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title = "CampusThesis API",
    description = "API платформы управления выпускными квалификационными работами",
    version = "0.4.0",
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