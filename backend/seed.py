"""Создаёт таблицы и заполняет базу тестовыми данными.

Run: python seed.py
"""
import hashlib

from database import Base, SessionLocal, engine
from models import (
    Department, Direction, Role, StageType, StudentProfile,
    SupervisorProfile, Topic, User,
)

# пока sha, если будет врремя - то на bcrypt перенести
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def seed():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    # Роли
    student_role = Role(name="student")
    supervisor_role = Role(name="supervisor")
    db.add_all([student_role, supervisor_role])

    # Кафедры и направления
    dep_it = Department(name="Кафедра информационных технологий")
    dep_se = Department(name="Кафедра программной инженерии")
    db.add_all([dep_it, dep_se])
    db.flush()  # чтобы у объектов появились id

    dir_pi = Direction(code="09.03.03", name="Прикладная информатика", department_id=dep_it.id)
    dir_se = Direction(code="09.03.04", name="Программная инженерия", department_id=dep_se.id)
    db.add_all([dir_pi, dir_se])

    # Этапы ВКР
    stages = [
        ("План", 14), ("Первая глава", 30), ("Вторая глава", 30),
        ("Полный текст", 30), ("Нормоконтроль", 10), ("Предзащита", 14), ("Защита", 14),
    ]
    for order, (name, days) in enumerate(stages, start=1):
        db.add(StageType(name=name, order_num=order, default_days=days))
    db.flush()

    # Руководители
    supervisors = [
        ("ivanova", "Иванова Мария Петровна", "доцент", dep_it),
        ("smirnov", "Смирнов Алексей Викторович", "профессор", dep_se),
    ]
    sup_profiles = {}
    for login, name, position, dep in supervisors:
        user = User(login=login, password_hash=hash_password("123"), full_name=name,
                    email=f"{login}@campus.example", role_id=supervisor_role.id) # для всех тестовых юзеров пароль 123 !!!
        db.add(user)
        db.flush()
        profile = SupervisorProfile(user_id=user.id, department_id=dep.id, position=position)
        db.add(profile)
        sup_profiles[login] = profile

    # Студенты
    students = [
        ("petrov", "Петров Илья Сергеевич", "РИ-410000", dir_pi),
        ("kuznetsova", "Кузнецова Анна Дмитриевна", "РИ-420000", dir_pi),
        ("sokolov", "Соколов Даниил Андреевич", "РИ-410001", dir_se),
    ]
    for login, name, group, direction in students:
        user = User(login=login, password_hash=hash_password("123"), full_name=name,
                    email=f"{login}@campus.example", role_id=student_role.id)
        db.add(user)
        db.flush()
        db.add(StudentProfile(user_id=user.id, direction_id=direction.id,
                              group_name=group, course=4))
    db.flush()

    # Темы ВКР
    topics = [
        ("Разработка системы бронирования аудиторий университета",
         "Веб-приложение для бронирования аудиторий с учётом расписания занятий и конфликтов.",
         "Знание Python или JavaScript, основы баз данных.", "ivanova", dir_pi),
        ("Анализ успеваемости студентов методами машинного обучения",
         "Построение модели, предсказывающей риск отчисления по данным об оценках и посещаемости.",
         "Python, pandas, scikit-learn.", "ivanova", dir_pi),
        ("Чат-бот для приёмной комиссии",
         "Telegram-бот, отвечающий абитуриентам на частые вопросы о поступлении.",
         "Python, опыт работы с API.", "ivanova", dir_pi),
        ("Мобильное приложение для учёта посещаемости",
         "Отметка присутствия на занятии по QR-коду с выгрузкой отчётов для преподавателя.",
         "Kotlin или Flutter.", "smirnov", dir_se),
        ("Сравнение архитектур микросервисов и монолита",
         "Исследование производительности и сложности сопровождения на примере учебного сервиса.",
         "Docker, любой серверный язык.", "smirnov", dir_se),
        ("Система автоматической проверки задач по программированию",
         "Сервис, запускающий решения студентов в изолированной среде и проверяющий их тестами.",
         "C++ или Python, Linux.", "smirnov", dir_se),
    ]
    for title, description, requirements, sup_login, direction in topics:
        db.add(Topic(title=title, description=description, requirements=requirements,
                     supervisor_id=sup_profiles[sup_login].id, direction_id=direction.id))

    db.commit()
    db.close()
    print("БД создана и заполнена тестовыми данными.")


if __name__ == "__main__":
    seed()