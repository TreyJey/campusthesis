from datetime import date, datetime, timedelta
from typing import Literal # enum
from fastapi import Depends, FastAPI, HTTPException, File, UploadFile, Form
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from pathlib import Path
import uuid

import models
from database import get_db, Base, engine
from security import hash_password

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title = "CampusThesis API",
    description = "API платформы управления выпускными квалификационными работами",
    version = "0.12.0",
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


@app.get("/api/departments", tags=["Словари"])
def get_departments(db: Session = Depends(get_db)):
    """Список кафедр."""
    return [{"id": d.id, "name": d.name} for d in db.query(models.Department).order_by(models.Department.name).all()]


@app.get("/api/supervisors", tags=["Словари"])
def get_supervisors(db: Session = Depends(get_db)):
    """Список руководителей с кафедрой и рейтингом (для фильтров)."""
    supervisors = db.query(models.SupervisorProfile).all()
    return [
        {
            "id": s.id,
            "full_name": s.user.full_name,
            "position": s.position,
            "department": {"id": s.department.id, "name": s.department.name},
            "rating": supervisor_rating(s),
        }
        for s in sorted(supervisors, key=lambda s: s.user.full_name)
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
def topic_to_dict(topic: models.Topic) -> dict:
    """Превращает тему из базы в словарь для ответа API"""
    return {
        "id": topic.id,
        "title": topic.title,
        "description": topic.description,
        "requirements": topic.requirements,
        "is_available": topic.is_available,
        "is_archived": topic.is_archived,
        "direction": {"id": topic.direction.id, "code": topic.direction.code, "name": topic.direction.name},
        "supervisor": {
            "id": topic.supervisor.id,
            "full_name": topic.supervisor.user.full_name,
            "position": topic.supervisor.position,
            "department": topic.supervisor.department.name,
            "rating": supervisor_rating(topic.supervisor)
        }
    }


def matches(search: str | None, *texts: str | None) -> bool:
    """True, если поиск пустой или строка найдена хотя бы в одном из текстов (без учёта регистра)."""
    if not search:
        return True
    query_text = search.lower().strip()
    return any(query_text in (t or "").lower() for t in texts)


# Рейтинг руководителя
def supervisor_rating(supervisor: models.SupervisorProfile) -> dict:
    """Средняя оценка руководителя и число оценок."""
    scores = [r.score for r in supervisor.ratings]
    average = round(sum(scores) / len(scores), 1) if scores else None
    return {"average": average, "count": len(scores)}


@app.get("/api/topics", tags=["Темы"])
def get_topics(
    search: str | None = None,
    direction_id: int | None = None,
    department_id: int | None = None,
    supervisor_id: int | None = None,
    min_rating: float | None = None,
    sort: Literal["title", "rating", "newest"] = "title",
    db: Session = Depends(get_db),
):
    """Каталог свободных тем.

    Поиск по названию, описанию, требованиям и ФИО руководителя.
    Фильтры: направление, кафедра, руководитель, минимальный рейтинг руководителя.
    Сортировка: по названию, по рейтингу руководителя, сначала новые.
    """
    query = (
        db.query(models.Topic)
        .join(models.SupervisorProfile)
        .filter(models.Topic.is_available == True, models.Topic.is_archived == False)
    )
    if direction_id is not None:
        query = query.filter(models.Topic.direction_id == direction_id)
    if department_id is not None:
        query = query.filter(models.SupervisorProfile.department_id == department_id)
    if supervisor_id is not None:
        query = query.filter(models.Topic.supervisor_id == supervisor_id)
    topics = query.all()

    # искать пришлось в питоне SQLite не умеет сравнивать русские буквы без учёта регистра
    topics = [
        t for t in topics
        if matches(search, t.title, t.description, t.requirements, t.supervisor.user.full_name)
    ]
    if min_rating is not None:
        topics = [t for t in topics if (supervisor_rating(t.supervisor)["average"] or 0) >= min_rating]

    if sort == "rating":
        topics.sort(key=lambda t: supervisor_rating(t.supervisor)["average"] or 0, reverse=True)
    elif sort == "newest":
        topics.sort(key=lambda t: t.created_at, reverse=True)
    else:
        topics.sort(key=lambda t: t.title)
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
def get_student_requests(
    student_id: int,
    status: Literal["pending", "approved", "rejected"] | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
):
    """Все заявки студента со статусами, новые сверху. Фильтр по статусу и поиск по теме."""
    if db.get(models.StudentProfile, student_id) is None:
        raise HTTPException(status_code=404, detail="Студент не найден")
    query = db.query(models.TopicRequest).filter(models.TopicRequest.student_id == student_id)
    if status is not None:
        query = query.filter(models.TopicRequest.status == status)
    requests = query.order_by(models.TopicRequest.created_at.desc()).all()
    requests = [r for r in requests if matches(search, r.topic.title)]
    return [request_to_dict(r) for r in requests]


@app.get("/api/supervisors/{supervisor_id}/requests", tags=["Заявки"])
def get_supervisor_requests(
    supervisor_id: int,
    search: str | None = None,
    status: Literal["pending", "approved", "rejected"] | None = None,
    topic_id: int | None = None,
    group_name: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    """Заявки на темы руководителя, новые сверху.

    Поиск по ФИО студента, названию темы и сообщению.
    Фильтры: статус, тема, группа студента, период подачи.
    """
    if db.get(models.SupervisorProfile, supervisor_id) is None:
        raise HTTPException(status_code=404, detail="Руководитель не найден")
    query = (
        db.query(models.TopicRequest)
        .join(models.Topic)
        .filter(models.Topic.supervisor_id == supervisor_id)
    )
    if status is not None:
        query = query.filter(models.TopicRequest.status == status)
    if topic_id is not None:
        query = query.filter(models.TopicRequest.topic_id == topic_id)
    requests = query.order_by(models.TopicRequest.created_at.desc()).all()

    result = []
    for r in requests:
        if group_name and r.student.group_name != group_name:
            continue
        if date_from and r.created_at.date() < date_from:
            continue
        if date_to and r.created_at.date() > date_to:
            continue
        if not matches(search, r.student.user.full_name, r.topic.title, r.message):
            continue
        result.append(request_to_dict(r))
    return result


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
                   f'Заявка на тему "{other.topic.title}" отклонена: тема или студент уже закреплены', "/student.html")

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
    in_work = stage.status in ("open", "revision")
    return {
        "id": stage.id,
        "name": stage.stage_type.name,
        "order_num": stage.stage_type.order_num,
        "deadline": stage.deadline,
        "status": stage.status,
        "is_overdue": not in_work and stage.deadline < date.today(),
        "submitted_at": stage.submitted_at,
        "approved_at": stage.approved_at,
        "files": [
            {"id": f.id, "original_name": f.original_name, "size_bytes": f.size_bytes, "uploaded_at": f.uploaded_at}
            for f in sorted(stage.files, key=lambda f: f.uploaded_at, reverse=True)
        ],
        "reviews": [
            {"id": r.id, "decision": r.decision, "grade": r.grade, "comment": r.comment, "created_at": r.created_at}
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
        "rating": (
            {"score": thesis.rating.score,
            "comment": thesis.rating.comment}
            if thesis.rating else None
        ),
        "stages": [stage_to_dict(s) for s in thesis.stages],
    }


def thesis_passes_filters(
    thesis: models.Thesis,
    search: str | None,
    stage_num: int | None,
    overdue_only: bool,
    status: str | None,
) -> bool:
    """Общие фильтры для списков ВКР: поиск, текущий этап, только просроченные, статус ВКР."""
    current = current_stage(thesis)
    if not matches(search, thesis.student.user.full_name, thesis.topic.title, thesis.student.group_name):
        return False
    if stage_num is not None and (current is None or current.stage_type.order_num != stage_num):
        return False
    if overdue_only and not (current and current.deadline < date.today()):  
        return False
    if status is not None and thesis.status != status:
        return False
    return True


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
def get_supervisor_theses(
    supervisor_id: int,
    search: str | None = None,
    stage_num: int | None = None,
    overdue_only: bool = False,
    status: Literal["in_progress", "defended"] | None = None,
    db: Session = Depends(get_db),
):
    """Студенты руководителя: тема и текущий этап каждого.

    Поиск по ФИО, теме и группе.
    Фильтры: номер текущего этапа (1–7), только просроченные, статус ВКР."""
    supervisor = db.get(models.SupervisorProfile, supervisor_id)
    if supervisor is None:
        raise HTTPException(status_code=404, detail="Руководитель не найден")
    theses = db.query(models.Thesis).filter(models.Thesis.supervisor_id == supervisor_id).all()

    result = []
    for thesis in theses:
        if not thesis_passes_filters(thesis, search, stage_num, overdue_only, status):
            continue
        current = current_stage(thesis)
        result.append({
            "id": thesis.id,
            "status": thesis.status,
            "topic": {"id": thesis.topic.id, "title": thesis.topic.title},
            "student": {
                "id": thesis.student.id,
                "full_name": thesis.student.user.full_name,
                "group_name": thesis.student.group_name,
            },
            "current_stage": stage_to_dict(current) if current else None,
        })
    return {"max_students": supervisor.max_students, "taken": len(theses), "theses": result}


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


# Отзывы руководителя
class ReviewCreate(BaseModel):
    """Тело запроса на отзыв по этапу."""
    supervisor_id: int
    decision: Literal["approved", "revision"]
    grade: int | None = Field(default=None, ge=2, le=5)
    comment: str | None = None


@app.post("/api/stages/{stage_id}/reviews", status_code=201, tags=["Отзывы"])
def review_stage(stage_id: int, data: ReviewCreate, db: Session = Depends(get_db)):
    """Руководитель проверяет этап: одобряет(открывается следующий) или возвращает на доработку."""
    stage = db.get(models.ThesisStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=404, detail="Этап не найден")
    thesis = db.get(models.Thesis, stage.thesis_id)
    if thesis.supervisor_id != data.supervisor_id:
        raise HTTPException(status_code=403, detail="Это этап студента другого руководителя")
    if stage.status != "submitted":
        raise HTTPException(status_code=400, detail="Этап не ждёт проверки")
    if data.decision == "revision" and not data.comment:
        raise HTTPException(status_code=400, detail="При возврате на доработку нужен комментарий")

    # Все проверки пройдены - сохраняем отзыв и меняем статусы
    db.add(models.Review(
        thesis_stage_id=stage.id,
        supervisor_id=data.supervisor_id,
        decision=data.decision,
        grade=data.grade,
        comment=data.comment,
    ))

    stage_name = stage.stage_type.name
    next_stage = None
    if data.decision == "approved":
        stage.status = "approved"
        stage.approved_at = datetime.now()
        # Открываем следующий этап по порядку
        for s in thesis.stages:
            if s.stage_type.order_num == stage.stage_type.order_num + 1:
                next_stage = s
        if next_stage is not None:
            next_stage.status = "open"
        else:
            thesis.status = "defended"  # этапа больше нет— защита пройдена
        decision_text = "одобрен"
    else:
        stage.status = "revision"
        decision_text = "возвращён на доработку"

    student_user = thesis.student.user
    log_action(db, thesis.supervisor.user_id, "stage_reviewed",
               f'Этап "{stage_name}" студента {student_user.full_name} {decision_text}')
    notify(db, student_user, "status", f'Этап "{stage_name}" {decision_text}', "/student.html")
    if data.comment:
        notify(db, student_user, "comment", f'Комментарий руководителя к этапу "{stage_name}": {data.comment}',
                "/student.html")
    db.commit()

    result = stage_to_dict(stage)
    result["next_stage_id"] = next_stage.id if next_stage else None
    return result


# Личный кабинет: профиль, настройки, уведомления, история
def get_user_or_404(db: Session, user_id: int) -> models.User:
    """Находит пользователя или сразу отвечает 404."""
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user


@app.get("/api/users/{user_id}/profile", tags=["Личный кабинет"])
def get_profile(user_id: int, db: Session = Depends(get_db)):
    """Профиль пользователя: общие данные, данные по роли и настройки уведомлений."""
    user = get_user_or_404(db, user_id)
    result = {
        "user_id": user.id,
        "login": user.login,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role.name,
        "created_at": user.created_at,
        "settings": {
            "notify_status": user.notify_status,
            "notify_comments": user.notify_comments,
            "notify_deadlines": user.notify_deadlines,
        },
    }
    if user.role.name == "student":
        profile = db.query(models.StudentProfile).filter(models.StudentProfile.user_id == user.id).first()
        result["student"] = {
            "profile_id": profile.id,
            "group_name": profile.group_name,
            "course": profile.course,
            "direction": f"{profile.direction.code} {profile.direction.name}",
        }
    elif user.role.name == "supervisor":
        profile = db.query(models.SupervisorProfile).filter(models.SupervisorProfile.user_id == user.id).first()
        result["supervisor"] = {
            "profile_id": profile.id,
            "position": profile.position,
            "department": profile.department.name,
            "max_students": profile.max_students,
        }
    return result


class ProfileUpdate(BaseModel):
    """Что можно поменять в профиле"""
    email: str | None = None
    notify_status: bool | None = None
    notify_comments: bool | None = None
    notify_deadlines: bool | None = None


@app.patch("/api/users/{user_id}/profile", tags=["Личный кабинет"])
def update_profile(user_id: int, data: ProfileUpdate, db: Session = Depends(get_db)):
    """Меняет почту и настройки уведомлений."""
    user = get_user_or_404(db, user_id)
    if data.email is not None:
        if "@" not in data.email:
            raise HTTPException(status_code=400, detail="Некорректный адрес почты")
        user.email = data.email
    if data.notify_status is not None:
        user.notify_status = data.notify_status
    if data.notify_comments is not None:
        user.notify_comments = data.notify_comments
    if data.notify_deadlines is not None:
        user.notify_deadlines = data.notify_deadlines
    log_action(db, user.id, "profile_updated", "Изменены настройки профиля")
    db.commit()
    return get_profile(user_id, db)


class PasswordChange(BaseModel):
    """Тело запроса на смену пароля."""
    old_password: str
    new_password: str = Field(min_length=6)


@app.post("/api/users/{user_id}/password", tags=["Личный кабинет"])
def change_password(user_id: int, data: PasswordChange, db: Session = Depends(get_db)):
    """Смена пароля: нужен старый пароль, новый — не короче 6 символов."""
    user = get_user_or_404(db, user_id)
    if user.password_hash != hash_password(data.old_password):
        raise HTTPException(status_code=400, detail="Старый пароль указан неверно")
    user.password_hash = hash_password(data.new_password)
    log_action(db, user.id, "password_changed", "Изменён пароль")
    db.commit()
    return {"status": "ok"}


DEADLINE_WARNING_DAYS = 3  # за сколько дней напоминать о дедлайне


def create_deadline_reminders(db: Session, user: models.User) -> None:
    """Напоминания студенту о близком или просроченном дедлайне текущего этапа (без повторов)."""
    if user.role.name != "student":
        return
    profile = db.query(models.StudentProfile).filter(models.StudentProfile.user_id == user.id).first()
    thesis = db.query(models.Thesis).filter(models.Thesis.student_id == profile.id).first()
    if thesis is None:
        return
    stage = current_stage(thesis)
    if stage is None or stage.status not in ("open", "revision"):
        return  # всё сдано или этап на проверке — напоминать не о чем

    days_left = (stage.deadline - date.today()).days
    if days_left < 0:
        text = f'Дедлайн этапа "{stage.stage_type.name}" прошёл {stage.deadline:%d.%m.%Y}'
    elif days_left <= DEADLINE_WARNING_DAYS:
        text = f'До дедлайна этапа "{stage.stage_type.name}" осталось дней: {days_left}'
    else:
        return  # время еще не пришло

    # already - защита от дублирования уведомлений
    already = (
        db.query(models.Notification)
        .filter(models.Notification.user_id == user.id, models.Notification.text == text)
        .first()
    )
    if already is None:
        notify(db, user, "deadline", text, "/student.html")


@app.get("/api/users/{user_id}/notifications", tags=["Личный кабинет"])
def get_notifications(user_id: int, unread_only: bool = False, db: Session = Depends(get_db)):
    """Уведомления пользователя, новые сверху, и число непрочитанных."""
    user = get_user_or_404(db, user_id)
    create_deadline_reminders(db, user)
    db.commit()

    query = db.query(models.Notification).filter(models.Notification.user_id == user_id)
    if unread_only:
        query = query.filter(models.Notification.is_read == False)
    notifications = query.order_by(models.Notification.created_at.desc()).all()
    unread_count = (
        db.query(models.Notification)
        .filter(models.Notification.user_id == user_id, models.Notification.is_read == False)
        .count()
    )
    return {
        "unread_count": unread_count,
        "items": [
            {"id": n.id, "type": n.type, "text": n.text, "link": n.link, "is_read": n.is_read,
             "created_at": n.created_at}
            for n in notifications
        ],
    }


@app.patch("/api/users/{user_id}/notifications/{notification_id}/read", tags=["Личный кабинет"])
def mark_notification_read(user_id: int, notification_id: int, db: Session = Depends(get_db)):
    """Отмечает одно уведомление прочитанным."""
    notification = db.get(models.Notification, notification_id)
    if notification is None or notification.user_id != user_id:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    notification.is_read = True
    db.commit()
    return {"status": "ok"}


@app.post("/api/users/{user_id}/notifications/read-all", tags=["Личный кабинет"])
def mark_all_notifications_read(user_id: int, db: Session = Depends(get_db)):
    """Отмечает все уведомления пользователя прочитанными."""
    get_user_or_404(db, user_id)
    count = (
        db.query(models.Notification)
        .filter(models.Notification.user_id == user_id, models.Notification.is_read == False)
        .update({"is_read": True})
    )
    db.commit()
    return {"marked": count}


@app.get("/api/users/{user_id}/history", tags=["Личный кабинет"])
def get_history(user_id: int, limit: int = 50, db: Session = Depends(get_db)):
    """История действий пользователя, новые сверху."""
    get_user_or_404(db, user_id)
    records = (
        db.query(models.ActivityLog)
        .filter(models.ActivityLog.user_id == user_id)
        .order_by(models.ActivityLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [{"id": r.id, "action": r.action, "text": r.text, "created_at": r.created_at} for r in records]


# Админка
def require_admin(db: Session, admin_id: int) -> models.User:
    """Проверяет, является ли пользователь админом(методистом)"""
    admin = get_user_or_404(db, admin_id)
    if admin.role.name != "admin":
        raise HTTPException(status_code=403, detail="У вас нет прав администратора")
    return admin


@app.get("/api/admin/theses", tags=["Админ"])
def get_admin_theses(
    admin_id: int,
    search: str | None = None,
    direction_id: int | None = None,
    supervisor_id: int | None = None,
    stage_num: int | None = None,
    overdue_only: bool = False,
    status: Literal["in_progress", "defended"] | None = None,
    db: Session = Depends(get_db),
):
    """Список всех ВКР.

    Поиск по ФИО студента, теме и группе.
    Фильтры: направление, руководитель, номер текущего этапа (1–7), только просроченные, статус ВКР."""
    require_admin(db, admin_id)
    query = db.query(models.Thesis)
    if supervisor_id is not None:
        query = query.filter(models.Thesis.supervisor_id == supervisor_id)
    theses = query.all()

    result = []
    for thesis in theses:
        if direction_id is not None and thesis.topic.direction_id != direction_id:
            continue
        if not thesis_passes_filters(thesis, search, stage_num, overdue_only, status):
            continue
        current = current_stage(thesis)
        result.append({
            "id": thesis.id,
            "status": thesis.status,
            "topic": {"id": thesis.topic.id, "title": thesis.topic.title},
            "student": {
                "id": thesis.student.id,
                "full_name": thesis.student.user.full_name,
                "group_name": thesis.student.group_name
            },
            "supervisor": {
                "id": thesis.supervisor.id,
                "full_name": thesis.supervisor.user.full_name,
                "department": thesis.supervisor.department.name
            },
            "current_stage": stage_to_dict(current) if current else None,
        })
    return {"theses": result}


class DeadlineChange(BaseModel):
    """Тело для смены дедлайна."""
    admin_id: int
    new_deadline: date
    reason: str | None = None


@app.patch("/api/admin/stages/{stage_id}/deadline", tags=["Админ"])
def change_deadline(data: DeadlineChange, stage_id: int, db: Session = Depends(get_db)):
    """Изменить дедлайн, можно уквзвть причину"""
    require_admin(db, data.admin_id)
    stage = db.get(models.ThesisStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=404, detail="Этап не найден")
    if stage.status == "approved":
        raise HTTPException(status_code=400, detail="Этап уже пройден, дедлайн менять нет смысла")
    if stage.deadline >= data.new_deadline:
        raise HTTPException(status_code=400, detail="Нельзя установить дедлайн на дату раньше или равную текущему")
    deadline_before_changes = stage.deadline
    stage.deadline = data.new_deadline
    thesis = db.get(models.Thesis, stage.thesis_id)
    reason_text = ""
    if data.reason:
        reason_text = f' по причине: "{data.reason}"'
    log_action(db, data.admin_id, "deadline_changed",
            f'Дедлайн этапа "{stage.stage_type.name}" студента {thesis.student.user.full_name} '
            f'изменен{reason_text}. Был {deadline_before_changes:%d.%m.%Y}, стал {stage.deadline:%d.%m.%Y}')
    notify(db, thesis.student.user, "deadline", 
           f'Дедлайн этапа "{stage.stage_type.name}" был перенесен с {deadline_before_changes:%d.%m.%Y} на '
           f'{stage.deadline:%d.%m.%Y}{reason_text}', "/student.html")
    db.commit()

    result = stage_to_dict(stage)
    return result


# Админ: управление темами
@app.get("/api/admin/topics", tags=["Админ"])
def get_admin_topics(
    admin_id: int,
    search: str | None = None,
    direction_id: int | None = None,
    department_id: int | None = None,
    supervisor_id: int | None = None,
    state: Literal["available", "taken", "archived"] | None = None,
    db: Session = Depends(get_db),
):
    """Все темы: свободные, занятые и архивные. У занятых указан студент.

    Поиск по названию, описанию и ФИО руководителя.
    Фильтры: направление, кафедра, руководитель, состояние (свободна / занята / в архиве).
    """
    require_admin(db, admin_id)
    query = db.query(models.Topic).join(models.SupervisorProfile)
    if direction_id is not None:
        query = query.filter(models.Topic.direction_id == direction_id)
    if department_id is not None:
        query = query.filter(models.SupervisorProfile.department_id == department_id)
    if supervisor_id is not None:
        query = query.filter(models.Topic.supervisor_id == supervisor_id)
    if state == "archived":
        query = query.filter(models.Topic.is_archived == True)
    elif state == "taken":
        query = query.filter(models.Topic.is_available == False, models.Topic.is_archived == False)
    elif state == "available":
        query = query.filter(models.Topic.is_available == True, models.Topic.is_archived == False)
    topics = query.order_by(models.Topic.title).all()

    result = []
    for topic in topics:
        if not matches(search, topic.title, topic.description, topic.supervisor.user.full_name):
            continue
        item = topic_to_dict(topic)
        thesis = db.query(models.Thesis).filter(models.Thesis.topic_id == topic.id).first()
        item["student"] = thesis.student.user.full_name if thesis else None
        result.append(item)
    return {"topics": result}


class TopicCreate(BaseModel):
    """Тело запроса на новую тему."""
    admin_id: int
    title: str = Field(min_length=10, max_length=300)
    description: str = Field(min_length=10)
    requirements: str | None = None
    supervisor_id: int
    direction_id: int


@app.post("/api/admin/topics", status_code=201, tags=["Админ"])
def create_topic(data: TopicCreate, db: Session = Depends(get_db)):
    """Методист добавляет тему в каталог."""
    require_admin(db, data.admin_id)
    supervisor = db.get(models.SupervisorProfile, data.supervisor_id)
    if supervisor is None:
        raise HTTPException(status_code=404, detail="Руководитель не найден")
    if db.get(models.Direction, data.direction_id) is None:
        raise HTTPException(status_code=404, detail="Направление не найдено")

    topic = models.Topic(
        title=data.title,
        description=data.description,
        requirements=data.requirements,
        supervisor_id=data.supervisor_id,
        direction_id=data.direction_id,
    )
    db.add(topic)
    log_action(db, data.admin_id, "topic_created", f'Добавлена тема "{data.title}"')
    notify(db, supervisor.user, "status", f'Методист добавил вашу тему "{data.title}" в каталог', "/supervisor.html")
    db.commit()
    db.refresh(topic)
    return topic_to_dict(topic)


class TopicUpdate(BaseModel):
    """Что можно поменять в теме. Все поля необязательные, кроме admin_id."""
    admin_id: int
    title: str | None = Field(default=None, min_length=10, max_length=300)
    description: str | None = Field(default=None, min_length=10)
    requirements: str | None = None
    supervisor_id: int | None = None
    direction_id: int | None = None
    is_archived: bool | None = None


@app.patch("/api/admin/topics/{topic_id}", tags=["Админ"])
def update_topic(topic_id: int, data: TopicUpdate, db: Session = Depends(get_db)):
    """Методист меняет тему или убирает её в архив (is_archived = true)."""
    require_admin(db, data.admin_id)
    topic = db.get(models.Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Тема не найдена")

    # У занятой темы нельзя менять руководителя и направление тк по ней уже идёт ВКР
    if not topic.is_available and (data.supervisor_id is not None or data.direction_id is not None):
        raise HTTPException(status_code=400,
                             detail="Тема закреплена за студентом: руководителя и направление менять нельзя")
    if data.supervisor_id is not None and db.get(models.SupervisorProfile, data.supervisor_id) is None:
        raise HTTPException(status_code=404, detail="Руководитель не найден")
    if data.direction_id is not None and db.get(models.Direction, data.direction_id) is None:
        raise HTTPException(status_code=404, detail="Направление не найдено")

    # Меняем только переданные поля
    if data.title is not None:
        topic.title = data.title
    if data.description is not None:
        topic.description = data.description
    if data.requirements is not None:
        topic.requirements = data.requirements
    if data.supervisor_id is not None:
        topic.supervisor_id = data.supervisor_id
    if data.direction_id is not None:
        topic.direction_id = data.direction_id
    if data.is_archived is not None:
        topic.is_archived = data.is_archived

    if data.is_archived is True:
        action_text = f'Тема "{topic.title}" убрана в архив'
    elif data.is_archived is False:
        action_text = f'Тема "{topic.title}" возвращена из архива'
    else:
        action_text = f'Изменена тема "{topic.title}"'
    log_action(db, data.admin_id, "topic_updated", action_text)
    db.commit()
    db.refresh(topic)
    return topic_to_dict(topic)


# Оценка руководителя студентом
class RatingCreate(BaseModel):
    """Тело запроса на оценку руководителя."""
    student_id: int
    score: int = Field(ge=1, le=5)
    comment: str | None = None


@app.put("/api/theses/{thesis_id}/rating", tags=["Рейтинг"])
def rate_supervisor(thesis_id: int, data: RatingCreate, db: Session = Depends(get_db)):
    """Студент оценивает руководителя по своей ВКР. Повторный запрос меняет оценку."""
    thesis = db.get(models.Thesis, thesis_id)
    if thesis is None:
        raise HTTPException(status_code=404, detail="ВКР не найдена")
    if thesis.student_id != data.student_id:
        raise HTTPException(status_code=403, detail="Оценить руководителя может только автор ВКР")

    rating = thesis.rating
    if rating is None:
        rating = models.SupervisorRating(
            thesis_id=thesis.id,
            student_id=thesis.student_id,
            supervisor_id=thesis.supervisor_id,
            score=data.score,
            comment=data.comment,
        )
        db.add(rating)
        action_text = f"Поставлена оценка руководителю {thesis.supervisor.user.full_name}: {data.score}"
    else:
        rating.score = data.score
        rating.comment = data.comment
        rating.updated_at = datetime.now()
        action_text = f"Изменена оценка руководителю {thesis.supervisor.user.full_name}: {data.score}"

    log_action(db, thesis.student.user_id, "supervisor_rated", action_text)
    notify(db, thesis.supervisor.user, "comment", f"Студент оценил работу с вами: {data.score} из 5", "/supervisor.html")
    db.commit()
    return {"score": rating.score, "comment": rating.comment, "supervisor_rating": supervisor_rating(thesis.supervisor)}


@app.get("/api/supervisors/{supervisor_id}/ratings", tags=["Рейтинг"])
def get_supervisor_ratings(supervisor_id: int, db: Session = Depends(get_db)):
    """Средняя оценка руководителя и отзывы студентов."""
    supervisor = db.get(models.SupervisorProfile, supervisor_id)
    if supervisor is None:
        raise HTTPException(status_code=404, detail="Руководитель не найден")
    reviews = sorted(supervisor.ratings, key=lambda r: r.created_at, reverse=True)
    return {
        "supervisor": {"id": supervisor.id, "full_name": supervisor.user.full_name},
        "rating": supervisor_rating(supervisor),
        "reviews": [
            {"score": r.score, "comment": r.comment, "student": r.student.user.full_name, "created_at": r.created_at}
            for r in reviews
        ],
    }


# Фронтенд: страницы из папки static
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

