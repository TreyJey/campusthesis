"""Создаёт таблицы и заполняет базу тестовыми данными. Для всех пользователей пароль 123.

Run: python seed.py
Сид повторяет то, что пользователи сделали бы через сайт: закрепляет темы, сдаёт и проверяет этапы.
"""
from datetime import date, timedelta
from pathlib import Path

from database import Base, SessionLocal, engine
from models import (
    Department, Direction, Notification, Review, Role, StageFile, StageType, StudentProfile,
    SupervisorProfile, SupervisorRating, Thesis, ThesisStage, Topic, TopicRequest, User,
)
from security import hash_password

UPLOAD_DIR = Path(__file__).parent / "uploads"

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
UPLOAD_DIR.mkdir(exist_ok=True)
for f in UPLOAD_DIR.iterdir():  # старые файлы удаляются
    f.unlink()
 
db = SessionLocal()

# Вспомогательные фенкции
def add_user(login, full_name, role):
    user = User(login=login, password_hash=hash_password("123"), full_name=full_name,
                email=f"{login}@campus.example", role_id=role.id)
    db.add(user)
    db.flush()
    return user


def add_supervisor(login, full_name, position, department):
    user = add_user(login, full_name, supervisor_role)
    profile = SupervisorProfile(user_id=user.id, department_id=department.id, position=position)
    db.add(profile)
    db.flush()
    return profile


def add_student(login, full_name, group, direction):
    user = add_user(login, full_name, student_role)
    profile = StudentProfile(user_id=user.id, direction_id=direction.id, group_name=group, course=4)
    db.add(profile)
    db.flush()
    return profile



def add_topic(title, description, requirements, supervisor, direction):
    topic = Topic(title=title, description=description, requirements=requirements,
                  supervisor_id=supervisor.id, direction_id=direction.id)
    db.add(topic)
    db.flush()
    return topic


def give_topic(student, topic, days_ago):
    """Руководитель одобрил заявку days_ago дней назад: создаём ВКР и 7 этапов, как в decide_topic_request."""
    db.add(TopicRequest(topic_id=topic.id, student_id=student.id, status="approved"))
    topic.is_available = False
    thesis = Thesis(student_id=student.id, topic_id=topic.id, supervisor_id=topic.supervisor_id)
    db.add(thesis)
    db.flush()
    deadline = date.today() - timedelta(days=days_ago)
    stages = []
    for stage_type in stage_types:
        deadline = deadline + timedelta(days=stage_type.default_days)
        stage = ThesisStage(thesis_id=thesis.id, stage_type_id=stage_type.id, deadline=deadline,
                            status="open" if stage_type.order_num == 1 else "locked")
        db.add(stage)
        stages.append(stage)
    db.flush()
    return stages


def submit(stages, number, file_name):
    """Студент сдал этап: пустой файл и статус на проверке."""
    stage = stages[number - 1]
    thesis = db.get(Thesis, stage.thesis_id)
    stored = f"demo_{stage.id}.pdf"
    (UPLOAD_DIR / stored).write_bytes(b"")
    db.add(StageFile(thesis_stage_id=stage.id, uploaded_by=thesis.student.user_id, original_name=file_name,
                     stored_path=stored, size_bytes=0))
    stage.status = "submitted"
    db.add(Notification(user_id=thesis.supervisor.user_id, type="status", link="/supervisor.html",
                        text=f'{thesis.student.user.full_name} сдал(а) этап "{stage.stage_type.name}" на проверку'))


def approve(stages, number, grade, comment):
    """Руководитель одобрил этап: открывается следующий."""
    stage = stages[number - 1]
    thesis = db.get(Thesis, stage.thesis_id)
    db.add(Review(thesis_stage_id=stage.id, supervisor_id=thesis.supervisor_id, decision="approved",
                  grade=grade, comment=comment))
    stage.status = "approved"
    stages[number].status = "open"
    # уведомления руководителю о сдаче этого студента уже неактуальны — отмечаем прочитанными
    db.flush()
    db.query(Notification).filter(
        Notification.user_id == thesis.supervisor.user_id,
        Notification.text.startswith(thesis.student.user.full_name),
    ).update({"is_read": True})


def send_back(stages, number, comment):
    """Руководитель вернул этап на доработку."""
    stage = stages[number - 1]
    thesis = db.get(Thesis, stage.thesis_id)
    db.add(Review(thesis_stage_id=stage.id, supervisor_id=thesis.supervisor_id, decision="revision",
                  grade=3, comment=comment))
    stage.status = "revision"
    db.add(Notification(user_id=thesis.student.user_id, type="comment", link="/student.html",
                        text=f'Комментарий руководителя к этапу "{stage.stage_type.name}": {comment}'))



def request_topic(student, topic, message):
    """Студент подал заявку, руководитель её ещё не рассмотрел."""
    db.add(TopicRequest(topic_id=topic.id, student_id=student.id, message=message))
    db.add(Notification(user_id=topic.supervisor.user_id, type="status", link="/supervisor.html",
                        text=f'{student.user.full_name} подал(а) заявку на тему "{topic.title}"'))


def rate(student, score, comment):
    thesis = db.query(Thesis).filter(Thesis.student_id == student.id).first()
    db.add(SupervisorRating(thesis_id=thesis.id, student_id=student.id, supervisor_id=thesis.supervisor_id,
                            score=score, comment=comment))


# Словари
student_role, supervisor_role, admin_role = Role(name="student"), Role(name="supervisor"), Role(name="admin")
db.add_all([student_role, supervisor_role, admin_role])
 
dep_it = Department(name="Кафедра информационных технологий")
dep_phys = Department(name="Кафедра физики")
db.add_all([dep_it, dep_phys])
db.flush()
dir_pi = Direction(code="09.03.03", name="Прикладная информатика", department_id=dep_it.id)
dir_se = Direction(code="09.03.04", name="Программная инженерия", department_id=dep_it.id)
dir_phys = Direction(code="03.03.02", name="Физика", department_id=dep_phys.id)
db.add_all([dir_pi, dir_se, dir_phys])
 
stage_types = []
for order, (name, days) in enumerate([("План", 14), ("Первая глава", 30), ("Вторая глава", 30),
                                      ("Полный текст", 30), ("Нормоконтроль", 10), ("Предзащита", 14),
                                      ("Защита", 14)], start=1):
    stage_types.append(StageType(name=name, order_num=order, default_days=days))
db.add_all(stage_types)


# Люди
add_user("admin", "Валиев Артур Марсельевич", admin_role)
ivanova = add_supervisor("ivanova", "Иванова Мария Петровна", "доцент", dep_it)
smirnov = add_supervisor("smirnov", "Смирнов Алексей Викторович", "профессор", dep_it)
petrov = add_student("petrov", "Петров Илья Сергеевич", "РИ-410000", dir_pi)
kuznetsova = add_student("kuznetsova", "Кузнецова Анна Дмитриевна", "РИ-420000", dir_pi)
sokolov = add_student("sokolov", "Соколов Даниил Андреевич", "РИ-410001", dir_se)
kozlova = add_supervisor("kozlova", "Козлова Ольга Игоревна", "старший преподаватель", dep_it)
morozova = add_student("morozova", "Морозова Екатерина Олеговна", "РИ-410000", dir_pi)
volkov = add_student("volkov", "Волков Артём Денисович", "РИ-420000", dir_pi)
zaitsev = add_student("zaitsev", "Зайцев Максим Игоревич", "РИ-410001", dir_se)
tarasov = add_student("tarasov", "Тарасов Егор Валерьевич", "РИ-420000", dir_pi)
dudkov = add_supervisor("dudkov", "Дудков Андрей Николаевич", "доцент", dep_phys)
trubnikov = add_student("trubnikov", "Трубников Василий Александрович", "профессор", dep_phys)


#Темы
booking = add_topic("Разработка системы бронирования аудиторий университета",
                    "Веб-приложение для бронирования аудиторий с учётом расписания занятий.",
                    "Python или JavaScript, основы баз данных.", ivanova, dir_pi)
ml_grades = add_topic("Анализ успеваемости студентов методами машинного обучения",
                      "Модель, предсказывающая риск отчисления по оценкам и посещаемости.",
                      "Python, pandas, scikit-learn.", ivanova, dir_pi)
chat_bot = add_topic("Чат-бот для приёмной комиссии",
                     "Telegram-бот, отвечающий абитуриентам на частые вопросы о поступлении.",
                     "Python, опыт работы с API.", ivanova, dir_pi)
library = add_topic("Рекомендательная система для научной библиотеки вуза",
                    "Подбор литературы по теме работы на основе истории выдачи.",
                    "Python, основы NLP.", ivanova, dir_pi)
dorm = add_topic("Информационная система учёта заселения в общежития",
                 "Автоматизация заявок на заселение и распределения мест.",
                 "Любой серверный язык, SQL.", kozlova, dir_pi)
attendance = add_topic("Мобильное приложение для учёта посещаемости",
                       "Отметка присутствия на занятии по QR-коду с отчётами для преподавателя.",
                       "Kotlin или Flutter.", smirnov, dir_se)
autograder = add_topic("Система автоматической проверки задач по программированию",
                       "Запуск решений студентов в изолированной среде и проверка тестами.",
                       "C++ или Python, Linux.", smirnov, dir_se)
ci_cd = add_topic("CI/CD-конвейер для учебных проектов студентов",
                  "Шаблоны репозиториев с автоматической сборкой и тестами.", "Git, GitHub Actions.", smirnov, dir_se)
phys_proc = add_topic("Моделирование физического процесса - теплопроводности в многослойных материалах",
                      "численное моделирование распределения температуры",
                      "Python, MathCad", dudkov, dir_phys)
crm = add_topic("Внедрение CRM для отдела практик",
                "Учёт договоров с предприятиями и распределения на практику.", None, kozlova, dir_pi)
crm.is_archived = True  # методист убрал устаревшую тему из каталога


# История работ над ВКР
 
# Кузнецова: план и первая глава одобрены, вторая глава ждёт проверки
kuz = give_topic(kuznetsova, ml_grades, days_ago=70)
submit(kuz, 1, "План ВКР.pdf")
approve(kuz, 1, 5, "Хорошо, двигаемся дальше.")
submit(kuz, 2, "Глава 1.pdf")
approve(kuz, 2, 4, "Структура логичная, добавьте выводы.")
submit(kuz, 3, "Глава 2.pdf")
 
# Морозова: план одобрен, первую главу вернули на доработку
mor = give_topic(morozova, library, days_ago=30)
submit(mor, 1, "План ВКР.pdf")
approve(mor, 1, 5, "Принято.")
submit(mor, 2, "Глава 1.pdf")
send_back(mor, 2, "Добавьте обзор аналогов и оформите ссылки по ГОСТу.")
 
# Волков: тему дали 12 дней назад, дедлайн плана через 2 дня — придёт напоминание(3 дня до дедлайна)
give_topic(volkov, dorm, days_ago=12)
 
# Соколов: план и первая глава одобрены, работает над второй
sok = give_topic(sokolov, autograder, days_ago=67)
submit(sok, 1, "План ВКР.pdf")
approve(sok, 1, 5, "Хорошо.")
submit(sok, 2, "Глава 1.pdf")
approve(sok, 2, 5, "Отлично.")
 
# Зайцев: тему дали 88 дней назад, вторую главу не сдал — просрочка
zai = give_topic(zaitsev, ci_cd, days_ago=88)
submit(zai, 1, "План ВКР.pdf")
approve(zai, 1, 4, "Принято с замечаниями.")
submit(zai, 2, "Глава 1.pdf")
approve(zai, 2, 4, "Принято.")
 
# Тарасов подал заявку к Ивановой — ждёт решения
request_topic(tarasov, chat_bot, "Делал ботов для студсовета, хочу развить это в ВКР.")

# Петров - для прогона сценария вручную
 
# Оценки руководителей
rate(kuznetsova, 5, "Всегда на связи, подробно комментирует каждую главу.")
rate(morozova, 4, "Требовательная, но замечания по делу.")
rate(sokolov, 5, "Помог с выбором технологий.")
rate(zaitsev, 3, "Отвечает с задержкой.")
 
db.commit()
db.close()
print("БД создана и заполнена тестовыми данными.")