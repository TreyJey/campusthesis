from datetime import date, datetime, timedelta
from typing import Literal # enum
from fastapi import Depends, FastAPI, HTTPException, File, UploadFile, Form
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel
from pathlib import Path
import uuid

import models
from database import get_db, Base, engine
from security import hash_password

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title = "CampusThesis API",
    description = "API платформы управления выпускными квалификационными работами",
    version = "0.9.1",
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


# Лог и уведомления
def log_action(db: Session, user_id: int, action: str, text: str) -> None:
    """Записывает действие пользователя в журнал. Сохраняется вместе с остальными изменениями на комите."""
    db.add(models.ActivityLog(user_id=user_id, action=action, text=text))


# Какая настройка пользоватля отвечает за какой тип уведомлений
NOTIFY_SETTINGS = {
    "status": "notify_status",
    "comment": "notify_comments",
    "deadline": "notify_deadlines",
}


def notify(db: Session, user: models.User, type_: str, text: str, link: str | None = None) -> None:
    """Создаёт уведомление, если пользователь не отключил этот тип в настройках."""
    if not getattr(user, NOTIFY_SETTINGS[type_]):
        return
    db.add(models.Notification(user_id=user.id, type=type_, text=text, link=link))


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
    query = db.query(models.Topic).filter(
        models.Topic.is_available == True,
        models.Topic.is_archived == False,
    )
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

    profile = None
    if user.role.name == "student":
        profile = db.query(models.StudentProfile).filter(models.StudentProfile.user_id == user.id).first()
    elif user.role.name == "supervisor":
        profile = db.query(models.SupervisorProfile).filter(models.SupervisorProfile.user_id == user.id).first()

    return {
        "user_id": user.id,
        "login": user.login,
        "full_name": user.full_name,
        "role": user.role.name,
        "profile_id": profile.id if profile else None,  # у админа профиля нет
    }                                                                                   # переделать на JWT токен если будет время ! ! !


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
    if topic.direction_id != student.direction_id:
        raise HTTPException(status_code=400, detail="Тема относится к другому направлению подготовки")

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
    log_action(db, student.user_id, "request_created", f'Подана заявка на тему "{topic.title}"')
    notify(db, topic.supervisor.user, "status",
           f'{student.user.full_name} подал(а) заявку на тему "{topic.title}"', "/supervisor.html")
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


def request_to_dict(req: models.TopicRequest) -> dict:
    """Превращает заявку в словарь с темой, студентом и руководителем."""
    return {
        "id": req.id,
        "status": req.status,
        "message": req.message,
        "supervisor_comment": req.supervisor_comment,
        "created_at": req.created_at,
        "decided_at": req.decided_at,
        "topic": {"id": req.topic.id, "title": req.topic.title},
        "student": {
            "id": req.student.id,
            "full_name": req.student.user.full_name,
            "group_name": req.student.group_name,
        },
        "supervisor": {"id": req.topic.supervisor.id, "full_name": req.topic.supervisor.user.full_name},
    }


@app.get("/api/students/{student_id}/requests", tags=["Заявки"])
def get_student_requests(student_id: int, db: Session = Depends(get_db)):
    """Все заявки студента со статусами, сорт - новые сверху."""
    if db.get(models.StudentProfile, student_id) is None:
        raise HTTPException(status_code=404, detail="Студент не найден")
    requests = (
        db.query(models.TopicRequest)
        .filter(models.TopicRequest.student_id == student_id)
        .order_by(models.TopicRequest.created_at.desc())
        .all()
    )
    return [request_to_dict(r) for r in requests]


@app.get("/api/supervisors/{supervisor_id}/requests", tags=["Заявки"])
def get_supervisor_requests(
    supervisor_id: int,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """Заявки на темы руководителя. Можно отфильтровать по статусу: pending, approved, rejected."""
    if db.get(models.SupervisorProfile, supervisor_id) is None:
        raise HTTPException(status_code=404, detail="Руководитель не найден")
    query = (
        db.query(models.TopicRequest)
        .join(models.Topic)
        .filter(models.Topic.supervisor_id == supervisor_id)
    )
    if status is not None:
        query = query.filter(models.TopicRequest.status == status)
    requests = query.order_by(models.TopicRequest.created_at.desc()).all()
    return [request_to_dict(r) for r in requests]


class TopicRequestDecision(BaseModel):
    """Тело запроса на решение по заявке."""
    supervisor_id: int
    decision: Literal["approved", "rejected"]
    comment: str | None = None


@app.patch("/api/topic-requests/{request_id}", tags=["Заявки"])
def decide_topic_request(request_id: int, data: TopicRequestDecision, db: Session = Depends(get_db)):
    """Руководитель одобряет или отклоняет заявку.

    При одобрении: создаётся ВКР и 7 этапов с дедлайнами, тема уходит из каталога,
    остальные заявки на эту тему и другие заявки студента отклоняются.
    """
    req = db.get(models.TopicRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if req.topic.supervisor_id != data.supervisor_id:
        raise HTTPException(status_code=403, detail="Это заявка на тему другого руководителя")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="Решение по заявке уже принято")

    supervisor = req.topic.supervisor
    if data.decision == "approved":
        if not req.topic.is_available:
            raise HTTPException(status_code=400, detail="Тема уже закреплена за другим студентом")
        has_thesis = db.query(models.Thesis).filter(models.Thesis.student_id == req.student_id).first()
        if has_thesis is not None:
            raise HTTPException(status_code=400, detail="У студента уже есть закреплённая тема")
        taken = db.query(models.Thesis).filter(models.Thesis.supervisor_id == supervisor.id).count()
        if taken >= supervisor.max_students:
            raise HTTPException(status_code=400, detail="У руководителя не осталось мест")

    # Все проверки пройдены - меняем данные
    now = datetime.now()
    req.status = data.decision
    req.supervisor_comment = data.comment
    req.decided_at = now

    thesis = None
    if data.decision == "approved":
        # 1. ВКР
        thesis = models.Thesis(student_id=req.student_id, topic_id=req.topic_id, supervisor_id=supervisor.id)
        db.add(thesis)
        db.flush()

        # 2. Семь этапов: дедлайны цепочкой, открыт пока токо первый
        deadline = date.today()
        stage_types = db.query(models.StageType).order_by(models.StageType.order_num).all()
        for stage_type in stage_types:
            deadline = deadline + timedelta(days=stage_type.default_days)
            db.add(models.ThesisStage(
                thesis_id=thesis.id,
                stage_type_id=stage_type.id,
                deadline=deadline,
                status="open" if stage_type.order_num == 1 else "locked",
            ))

        # 3. Тема уходит из каталога
        req.topic.is_available = False

        # 4. Остальные ожидающие заявки на эту тему и другие заявки студента отклоняются
        others = (
            db.query(models.TopicRequest)
            .filter(
                models.TopicRequest.id != req.id,
                models.TopicRequest.status == "pending",
                (models.TopicRequest.topic_id == req.topic_id) | (models.TopicRequest.student_id == req.student_id),
            )
            .all()
        )
        for other in others:
            other.status = "rejected"
            other.supervisor_comment = "Тема или студент уже закреплены"
            other.decided_at = now
            notify(db, other.student.user, "status",
                   f'Заявка на тему "{other.topic.title}" отклонена: тема или студент уже закреплены", "/student.html')

    decision = "одобрена" if data.decision == "approved" else "отклонена"
    log_action(db, supervisor.user_id, "request_decided",
               f'Заявка {req.student.user.full_name} на тему "{req.topic.title}" {decision}')
    notify(db, req.student.user, "status", f'Ваша заявка на тему "{req.topic.title}" {decision}', "/student.html")

    db.commit()

    result = request_to_dict(req)
    result["thesis_id"] = thesis.id if thesis else None
    return result


# Рабочая область студента
def stage_to_dict(stage: models.ThesisStage) -> dict:
    """Этап ВКР со всеми файлами и отзывами."""
    is_finished = stage.status == "approved"
    return {
        "id": stage.id,
        "name": stage.stage_type.name,
        "order_num": stage.stage_type.order_num,
        "deadline": stage.deadline,
        "status": stage.status,
        "is_overdue": not is_finished and stage.deadline < date.today(),
        "submitted_at": stage.submitted_at,
        "approved_at": stage.approved_at,
        "files": [
            {"id": f.id, "original_name": f.original_name, "size_bytes": f.size_bytes, "uploaded_at": f.uploaded_at}
            for f in sorted(stage.files, key=lambda f: f.uploaded_at, reverse=True)
        ],
        "reviews": [
            {"id": r.id, "decision": r.decision, "comment": r.comment, "created_at": r.created_at}
            for r in sorted(stage.reviews, key=lambda r: r.created_at, reverse=True)
        ],
    }


def current_stage(thesis: models.Thesis) -> models.ThesisStage | None:
    """Первый неодобренный этап. =None если пройдены все."""
    for stage in thesis.stages:
        if stage.status != "approved":
            return stage
    return None


def thesis_to_dict(thesis: models.Thesis) -> dict:
    """ВКР целиком: тема, студент, руководитель, текущий этап и все этапы."""
    current = current_stage(thesis)
    return {
        "id": thesis.id,
        "status": thesis.status,
        "created_at": thesis.created_at,
        "topic": {"id": thesis.topic.id, "title": thesis.topic.title},
        "student": {
            "id": thesis.student.id,
            "full_name": thesis.student.user.full_name,
            "group_name": thesis.student.group_name,
        },
        "supervisor": {"id": thesis.supervisor.id, "full_name": thesis.supervisor.user.full_name},
        "current_stage_id": current.id if current else None,
        "stages": [stage_to_dict(s) for s in thesis.stages],
    }


@app.get("/api/students/{student_id}/thesis", tags=["ВКР"])
def get_student_thesis(student_id: int, db: Session = Depends(get_db)):
    """Рабочая область студента: его вкр со всеми этапами, файлами и отзывами."""
    if db.get(models.StudentProfile, student_id) is None:
        raise HTTPException(status_code=404, detail="Студент не найден")
    thesis = db.query(models.Thesis).filter(models.Thesis.student_id == student_id).first()
    if thesis is None:
        raise HTTPException(status_code=404, detail="У студента ещё нет закреплённой темы")
    return thesis_to_dict(thesis)


# Студенты руководителя
@app.get("/api/supervisors/{supervisor_id}/theses", tags=["ВКР"])
def get_supervisor_theses(supervisor_id: int, db: Session = Depends(get_db)):
    """Студенты руководителя: тема и текущий этап каждого."""
    supervisor = db.get(models.SupervisorProfile, supervisor_id)
    if supervisor is None:
        raise HTTPException(status_code=404, detail="Руководитель не найден")
    theses = db.query(models.Thesis).filter(models.Thesis.supervisor_id == supervisor_id).all()

    result = []
    for thesis in theses:
        current = current_stage(thesis)
        result.append({
            "id": thesis.id,
            "topic": {"id": thesis.topic.id, "title": thesis.topic.title},
            "student": {
                "id": thesis.student.id,
                "full_name": thesis.student.user.full_name,
                "group_name": thesis.student.group_name,
            },
            "current_stage": stage_to_dict(current) if current else None,
        })
    return {"max_students": supervisor.max_students, "theses": result}


@app.get("/api/theses/{thesis_id}", tags=["ВКР"])
def get_thesis(thesis_id: int, db: Session = Depends(get_db)):
    """Одна ВКР целиком. Руководитель открывает её из своих студентов."""
    thesis = db.get(models.Thesis, thesis_id)
    if thesis is None:
        raise HTTPException(status_code=404, detail="ВКР не найдена")
    return thesis_to_dict(thesis)


# Файлы этапов
UPLOAD_DIR = Path(__file__).parent / "uploads"  # папка uploads рядом с main.py
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".zip", ".7z", ".rar"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20мб


@app.post("/api/stages/{stage_id}/files", status_code=201, tags=["Файлы"])
def upload_stage_file(
    stage_id: int,
    student_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Студент загружает файл этапа. Этап переходит в статус "на проверке"."""
    stage = db.get(models.ThesisStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=404, detail="Этап не найден")
    thesis = db.get(models.Thesis, stage.thesis_id)
    if thesis.student_id != student_id:
        raise HTTPException(status_code=403, detail="Это не ваша ВКР")
    if stage.status not in ("open", "revision"):
        raise HTTPException(status_code=400, detail="Сейчас загрузить файл на этот этап нельзя")

    extension = Path(file.filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Допустимые форматы: PDF, DOC, DOCX, ZIP, 7Z, RAR")
    content = file.file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Файл больше 20 МБ")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Файл пустой")

    # Сохраняем на диск под уникальным именем
    stored_name = f"{uuid.uuid4().hex}{extension}"
    (UPLOAD_DIR / stored_name).write_bytes(content)

    stage_file = models.StageFile(
        thesis_stage_id=stage.id,
        uploaded_by=thesis.student.user_id,
        original_name=file.filename,
        stored_path=stored_name,
        size_bytes=len(content),
    )
    db.add(stage_file)
    stage.status = "submitted"
    stage.submitted_at = datetime.now()

    log_action(db, thesis.student.user_id, "file_uploaded",
               f'Загружен файл "{file.filename}" на этап "{stage.stage_type.name}"')
    notify(db, thesis.supervisor.user, "status",
           f'{thesis.student.user.full_name} сдал(а) этап "{stage.stage_type.name}" на проверку', "/supervisor.html")
    db.commit()
    db.refresh(stage_file)

    return {
        "id": stage_file.id,
        "original_name": stage_file.original_name,
        "size_bytes": stage_file.size_bytes,
        "uploaded_at": stage_file.uploaded_at,
        "stage_status": stage.status,
    }


@app.get("/api/files/{file_id}", tags=["Файлы"])
def download_file(file_id: int, db: Session = Depends(get_db)):
    """Скачать файл этапа под исходным именем."""
    stage_file = db.get(models.StageFile, file_id)
    if stage_file is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    path = UPLOAD_DIR / stage_file.stored_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл удалён с сервера")
    return FileResponse(path, filename=stage_file.original_name)