from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db

app = FastAPI(
    title = "CampusThesis API",
    description = "API платформы управления выпускными квалификационными работами",
    version = "0.2.0",
)

@app.get("/api/health", tags = ["Служебная информация"])
def health_check(db: Session = Depends(get_db)):
    """Проверка статуса сервера и доступа к БД"""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}

@app.get("/api/stage-types", tags=["Словари"])
def get_stage_types():
    """Список этапов ВКР по порядку. Пока без базы(тест)."""
    return [
        {"id": 1, "name": "План", "order_num": 1, "default_days": 14},
        {"id": 2, "name": "Первая глава", "order_num": 2, "default_days": 30},
        {"id": 3, "name": "Вторая глава", "order_num": 3, "default_days": 30},
        {"id": 4, "name": "Полный текст", "order_num": 4, "default_days": 30},
        {"id": 5, "name": "Нормоконтроль", "order_num": 5, "default_days": 10},
        {"id": 6, "name": "Предзащита", "order_num": 6, "default_days": 14},
        {"id": 7, "name": "Защита", "order_num": 7, "default_days": 14},
    ]